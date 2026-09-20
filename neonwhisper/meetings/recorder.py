"""Graba una reunión a disco: tu micrófono y lo que suena en tu PC, mezclados en un .wav.

El audio del sistema se captura abriendo el altavoz en modo loopback con WASAPI
(ver `system_audio.py`), que funciona con cualquier salida. Si eso falla se prueba con un
dispositivo de entrada «loopback»/«Stereo Mix», y si tampoco hay, se graba solo el micrófono
y se avisa; la reunión se sigue transcribiendo igual.

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
from neonwhisper.meetings.system_audio import open_system_source

log = logging.getLogger(__name__)

BLOCK_SECONDS = 0.1
FLUSH_SECONDS = 0.5
STARVE_SECONDS = 2.0  # si una fuente se queda muda tanto tiempo, se escribe la otra sola


def device_label(index: int | None) -> str:
    """Nombre del dispositivo, para decirle al usuario qué se está grabando."""
    try:
        return str(sd.query_devices(index, "input")["name"])
    except Exception:  # noqa: BLE001
        return "dispositivo desconocido"


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


def open_system_audio(speaker: str = ""):
    """Lo que suena en la PC: primero WASAPI loopback, si no un dispositivo «loopback»/«Stereo Mix»."""
    try:
        return open_system_source(speaker)
    except Exception as exc:  # noqa: BLE001
        log.warning("WASAPI loopback no disponible (%s): se busca un dispositivo de entrada", exc)
    index = find_loopback_device()
    if index is None:
        return None
    source = Source(index, loopback=True)
    source.start()
    source.label = device_label(index)
    return source


_FILTERS: dict[int, np.ndarray] = {}


def _lowpass(rate: int, taps: int = 101) -> np.ndarray:
    """Filtro que quita lo que está por encima de 8 kHz antes de bajar a 16 kHz."""
    if rate not in _FILTERS:
        n = np.arange(taps) - (taps - 1) / 2
        h = np.sinc(2 * (0.45 * SAMPLE_RATE) / rate * n) * np.blackman(taps)
        _FILTERS[rate] = (h / h.sum()).astype(np.float32)
    return _FILTERS[rate]


def to_mono_16k(block: np.ndarray, rate: int, tail: np.ndarray | None = None):
    """Mezcla los canales y baja el bloque a 16 kHz, sin alias.

    Bajar de 48 kHz a 16 kHz sin filtrar antes pliega todo lo que suena por encima de 8 kHz
    dentro de la voz: un chasquido de teclado de 15 kHz aparecía como un tono de 1 kHz casi igual
    de fuerte, justo encima de las frecuencias que Whisper escucha. Con `tail` se guarda el final
    del bloque anterior para que el filtro no deje un chasquido en cada costura.

    Devuelve el audio, o (audio, nueva_cola) si se pasó `tail`.
    """
    mono = (block.mean(axis=1) if block.ndim > 1 else block).astype(np.float32)
    new_tail = None
    if rate != SAMPLE_RATE:
        h = _lowpass(rate)
        if tail is None:
            mono = np.convolve(mono, h, mode="same")
        else:
            padded = np.concatenate([tail, mono])
            new_tail = padded[-(len(h) - 1):].copy() if len(padded) >= len(h) - 1 else padded.copy()
            filtered = np.convolve(padded, h, mode="valid")
            mono = filtered[-len(mono):] if len(filtered) >= len(mono) else filtered
        n = max(1, int(round(len(mono) * SAMPLE_RATE / rate)))
        if len(mono) > 1:
            mono = np.interp(np.linspace(0, len(mono) - 1, n), np.arange(len(mono)), mono)
    mono = mono.astype(np.float32)
    return (mono, new_tail if new_tail is not None else np.zeros(0, dtype=np.float32)) if tail is not None else mono


class Source:
    """Una fuente de audio (micrófono o loopback) volcando en un buffer."""

    def __init__(self, device: int | None, loopback: bool = False, muted: bool = False):
        self.device = device
        self.loopback = loopback
        self.label = ""
        self.muted = muted  # silenciada: se sigue leyendo (para no desincronizar) pero no se graba
        self.buffer = np.zeros(0, dtype=np.float32)
        self.level = 0.0
        self.last_block = 0.0
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._rate = SAMPLE_RATE
        self._tail = np.zeros(0, dtype=np.float32)  # cola del filtro antialias

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
                if self._stream is not None:  # PortAudio no lo cierra solo
                    try:
                        self._stream.close(ignore_errors=True)
                    except Exception:  # noqa: BLE001
                        pass
                self._stream = None
        raise RuntimeError(f"No se pudo abrir el dispositivo {self.device}")

    def _callback(self, indata, frames, time_info, status):  # hilo de PortAudio
        block, self._tail = to_mono_16k(indata.copy(), self._rate, self._tail)
        with self._lock:
            self.buffer = np.concatenate([self.buffer, block])
        self.level = 0.0 if self.muted else level_of(block)
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
        self._sources: list[Source] = []
        self._wave: wave.Wave_write | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.path: Path | None = None
        self.started_at = 0.0
        self.system_audio = False  # si se está capturando lo que suena en la PC
        self.system_label = ""     # qué salida se está capturando
        self.level = 0.0

    @property
    def recording(self) -> bool:
        return self._wave is not None

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at if self.recording else 0.0

    # --- qué entra en la grabación -------------------------------------------
    def _source(self, kind: str) -> "Source | None":
        """kind: "mic" (tu voz) o "system" (lo que suena en tu PC)."""
        return next((s for s in self._sources if s.loopback == (kind == "system")), None)

    def is_muted(self, kind: str) -> bool:
        source = self._source(kind)
        return True if source is None else source.muted

    def set_muted(self, kind: str, muted: bool) -> None:
        """Silencia una fuente en caliente: deja de grabarse, pero la otra sigue igual de sincronizada."""
        source = self._source(kind)
        if source is not None:
            source.muted = muted
            if muted:
                source.level = 0.0
            log.info("Reunión: %s %s", kind, "silenciado" if muted else "activo")

    def source_level(self, kind: str) -> float:
        """Nivel actual de una fuente (0..1): «mic» tu voz, «system» lo que suena en la PC."""
        source = self._source(kind)
        return float(getattr(source, "level", 0.0)) if source is not None else 0.0

    @property
    def sources(self) -> dict[str, bool]:
        """Qué fuentes hay, siguen vivas y no están silenciadas."""
        return {kind: self._is_recording(kind) for kind in ("mic", "system")}

    def _is_recording(self, kind: str) -> bool:
        source = self._source(kind)
        return source is not None and getattr(source, "alive", True) and not source.muted

    def describe_short(self) -> str:
        """Versión corta para el aviso flotante: «micro + sistema»."""
        names = {"mic": "micro", "system": "sistema"}
        active = [names[k] for k, on in self.sources.items() if on]
        return " + ".join(active) if active else "silenciado"

    def describe(self) -> str:
        """«tu micrófono + el audio del sistema», «solo tu micrófono»… para avisos y la interfaz."""
        names = {"mic": "tu micrófono", "system": "el audio del sistema"}
        active = [names[k] for k, on in self.sources.items() if on]
        if not active:
            return "nada: las dos fuentes están silenciadas"
        return " + ".join(active) if len(active) > 1 else f"solo {active[0]}"

    def start(self, path: Path, mic: int | None = None, system: bool = True, mic_muted: bool = False,
              speaker: str = "") -> None:
        if self.recording:
            return
        microphone = Source(mic, muted=mic_muted)
        try:
            microphone.start()
        except Exception:  # noqa: BLE001
            log.exception("No se pudo abrir el micrófono %s", mic)
            raise
        sources = [microphone]
        self.system_audio, self.system_label = False, ""
        if system:
            try:
                loopback = open_system_audio(speaker)
            except Exception:  # noqa: BLE001
                log.exception("No se pudo capturar el audio del sistema")
                loopback = None
            if loopback is None:
                log.warning("Sin audio del sistema: se grabará solo el micrófono")
            else:
                sources.append(loopback)
                self.system_audio = True
                self.system_label = getattr(loopback, "label", "")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = wave.open(str(path), "wb")
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SAMPLE_RATE)
        except Exception:  # noqa: BLE001 - sin esto el micrófono seguiría grabando sin que nadie lo pare
            log.exception("No se pudo crear el archivo de la reunión")
            for source in sources:
                source.stop()
            self.system_audio, self.system_label = False, ""
            raise
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

    def follow_to(self, device_name: str) -> bool:
        """Cambia la captura a esa salida (lo pide el controlador, desde el hilo de la interfaz)."""
        source = self._source("system")
        if source is None or not device_name or not hasattr(source, "retarget"):
            return False
        if device_name == getattr(source, "label", ""):
            return False
        if source.retarget(device_name):
            self.system_label = source.label
            return True
        return False

    def _flush(self, final: bool = False) -> None:
        sources = list(self._sources)
        if not sources or self._wave is None:
            return
        now = time.monotonic()
        alive = [s for s in sources if final or now - s.last_block < STARVE_SECONDS]
        if not alive:
            alive = sources
        for source in sources:
            if source not in alive:
                source.take(source.available())  # su audio viejo iría desfasado para siempre
        count = min(s.available() for s in alive) if not final else max(s.available() for s in alive)
        if count <= 0:
            return
        mix = np.zeros(count, dtype=np.float32)
        grabando = [s for s in alive if not s.muted]
        # Con dos fuentes fuertes, sumarlas a pelo pasaba de 1.0 y la onda se recortaba: eso es
        # justo la distorsión que más confunde a Whisper. Se les deja margen antes de sumar.
        gain = 0.6 if len(grabando) > 1 else 1.0
        for source in alive:
            taken = source.take(count)  # se consume siempre, aunque esté silenciada
            if not source.muted:
                mix += taken * gain
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
        writer, self._thread = self._thread, None
        if writer is not None:
            writer.join(timeout=3)
        for source in self._sources:
            source.stop()
        if writer is not None and writer.is_alive():  # disco lento: mejor perder el último tramo
            log.warning("El hilo que escribe el audio no terminó a tiempo: no se vuelca el final")
        else:
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
