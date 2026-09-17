"""Graba una reunión a disco: tu micrófono y lo que suena en tu PC, mezclados en un .wav.

El audio del sistema se captura con los dispositivos *loopback* de WASAPI, que Windows
expone como entradas más (p. ej. «Altavoces (Realtek) [Loopback]»). Si no hay ninguno,
se graba solo el micrófono y se avisa; la reunión se sigue transcribiendo igual.

Se escribe en el .wav según llega (16 kHz mono, 16 bits: ~2 MB por minuto), así una
reunión de dos horas no ocupa memoria y sobrevive a que la app se cierre a lo bruto.
"""
import logging
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from neonwhisper.audio import SAMPLE_RATE, level_of

log = logging.getLogger(__name__)

BLOCK_SECONDS = 0.1
FLUSH_SECONDS = 0.5
STARVE_SECONDS = 2.0  # si una fuente se queda muda tanto tiempo, se escribe la otra sola


def find_loopback_device(output_name: str = "") -> int | None:
    """Entrada *loopback* que graba lo que suena en tu PC (la del altavoz en uso, si se puede)."""
    try:
        devices = sd.query_devices()
    except Exception:  # noqa: BLE001
        return None
    candidates = [
        (i, d["name"]) for i, d in enumerate(devices)
        if d["max_input_channels"] > 0 and "loopback" in d["name"].lower()
    ]
    if not candidates:
        return None
    if not output_name:
        try:
            output_name = sd.query_devices(kind="output")["name"]
        except Exception:  # noqa: BLE001
            output_name = ""
    stem = output_name.split("(")[0].strip().lower()
    if stem:
        for index, name in candidates:
            if stem in name.lower():
                return index
    return candidates[0][0]


def to_mono_16k(block: np.ndarray, rate: int) -> np.ndarray:
    """Mezcla los canales y lleva el bloque a 16 kHz."""
    mono = block.mean(axis=1) if block.ndim > 1 else block
    if rate != SAMPLE_RATE:
        n = max(1, int(round(len(mono) * SAMPLE_RATE / rate)))
        mono = np.interp(np.linspace(0, len(mono) - 1, n), np.arange(len(mono)), mono)
    return mono.astype(np.float32)


class _Source:
    """Una fuente de audio (micrófono o loopback) volcando en un buffer."""

    def __init__(self, device: int | None, loopback: bool = False):
        self.device = device
        self.loopback = loopback
        self.buffer = np.zeros(0, dtype=np.float32)
        self.level = 0.0
        self.last_block = 0.0
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._rate = SAMPLE_RATE

    def start(self) -> None:
        info = sd.query_devices(self.device, "input")
        channels = min(2, max(1, int(info["max_input_channels"])))
        for rate in (SAMPLE_RATE, int(info["default_samplerate"])):
            try:
                self._stream = sd.InputStream(
                    samplerate=rate, channels=channels, dtype="float32", device=self.device,
                    blocksize=int(rate * BLOCK_SECONDS), callback=self._callback,
                )
                self._stream.start()
                self._rate = rate
                self.last_block = time.monotonic()
                return
            except Exception:  # noqa: BLE001 - el dispositivo no acepta 16 kHz: se usa el suyo
                self._stream = None
        raise RuntimeError(f"No se pudo abrir el dispositivo {self.device}")

    def _callback(self, indata, frames, time_info, status):  # hilo de PortAudio
        block = to_mono_16k(indata.copy(), self._rate)
        with self._lock:
            self.buffer = np.concatenate([self.buffer, block])
        self.level = level_of(block)
        self.last_block = time.monotonic()

    def take(self, count: int) -> np.ndarray:
        with self._lock:
            take, self.buffer = self.buffer[:count], self.buffer[count:]
        if len(take) < count:
            take = np.concatenate([take, np.zeros(count - len(take), dtype=np.float32)])
        return take

    def available(self) -> int:
        with self._lock:
            return len(self.buffer)

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                log.exception("Error cerrando la fuente de audio")


class MeetingRecorder:
    """Graba a un .wav hasta que le digas que pare. Devuelve la ruta y la duración."""

    def __init__(self):
        self._sources: list[_Source] = []
        self._wave: wave.Wave_write | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.path: Path | None = None
        self.started_at = 0.0
        self.system_audio = False  # si se está capturando lo que suena en la PC
        self.level = 0.0

    @property
    def recording(self) -> bool:
        return self._wave is not None

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at if self.recording else 0.0

    def start(self, path: Path, mic: int | None = None, system: bool = True) -> None:
        if self.recording:
            return
        sources = [_Source(mic)]
        self.system_audio = False
        if system:
            loopback = find_loopback_device()
            if loopback is None:
                log.warning("Sin dispositivo loopback: se grabará solo el micrófono")
            else:
                sources.append(_Source(loopback, loopback=True))
                self.system_audio = True
        for source in sources:
            try:
                source.start()
            except Exception:  # noqa: BLE001
                log.exception("No se pudo abrir la fuente %s", source.device)
                if not source.loopback:
                    for other in sources:
                        other.stop()
                    raise
                sources.remove(source)
                self.system_audio = False
                break

        path.parent.mkdir(parents=True, exist_ok=True)
        handle = wave.open(str(path), "wb")
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        self._sources, self._wave, self.path = sources, handle, path
        self._stop.clear()
        self.started_at = time.monotonic()
        self._thread = threading.Thread(target=self._writer, name="meeting-writer", daemon=True)
        self._thread.start()

    def _writer(self) -> None:
        while not self._stop.is_set():
            time.sleep(FLUSH_SECONDS)
            self._flush()
        self._flush(final=True)

    def _flush(self, final: bool = False) -> None:
        sources = list(self._sources)
        if not sources or self._wave is None:
            return
        now = time.monotonic()
        alive = [s for s in sources if final or now - s.last_block < STARVE_SECONDS]
        if not alive:
            alive = sources
        count = min(s.available() for s in alive) if not final else max(s.available() for s in alive)
        if count <= 0:
            return
        mix = np.zeros(count, dtype=np.float32)
        for source in alive:
            mix += source.take(count)
        np.clip(mix, -1.0, 1.0, out=mix)
        self.level = level_of(mix[-1600:]) if len(mix) else 0.0
        try:
            self._wave.writeframes((mix * 32767).astype(np.int16).tobytes())
        except Exception:  # noqa: BLE001
            log.exception("Error escribiendo el audio de la reunión")

    def stop(self) -> tuple[Path | None, float]:
        if not self.recording:
            return None, 0.0
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        for source in self._sources:
            source.stop()
        self._flush(final=True)
        handle, self._wave = self._wave, None
        seconds = 0.0
        if handle is not None:
            try:
                seconds = handle.getnframes() / SAMPLE_RATE
                handle.close()
            except Exception:  # noqa: BLE001
                log.exception("Error cerrando el .wav de la reunión")
        self._sources = []
        self.level = 0.0
        path, self.path = self.path, None
        return path, seconds


def read_wav(path: Path, offset: float = 0.0, seconds: float | None = None) -> np.ndarray:
    """Lee un tramo del .wav como float32 16 kHz (para transcribir por partes)."""
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        handle.setpos(min(int(offset * rate), handle.getnframes()))
        frames = handle.getnframes() if seconds is None else int(seconds * rate)
        raw = handle.readframes(frames)
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return to_mono_16k(audio, rate) if rate != SAMPLE_RATE else audio


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / handle.getframerate()
    except Exception:  # noqa: BLE001
        return 0.0
