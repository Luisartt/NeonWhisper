"""Grabación del micrófono a 16 kHz mono con medidor de nivel en tiempo real."""
import logging
import math
import threading
import time

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
log = logging.getLogger(__name__)


def level_of(samples: np.ndarray) -> float:
    """Nivel visual 0..1 de un bloque de audio (escala logarítmica, -55 dB = 0)."""
    if len(samples) == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(samples * samples))) + 1e-9
    return max(0.0, min(1.0, (20 * math.log10(rms) + 55) / 45)) ** 1.4


def list_input_devices() -> list[tuple[int, str]]:
    """Micrófonos del host API predeterminado (evita duplicados MME/WASAPI/DirectSound)."""
    try:
        default_api = sd.default.hostapi
        devices = sd.query_devices()
    except Exception:  # noqa: BLE001 - PortAudio puede fallar sin dispositivos
        return []
    return [
        (i, d["name"])
        for i, d in enumerate(devices)
        if d["max_input_channels"] > 0 and d["hostapi"] == default_api
    ]


def resolve_input_device(name: str, legacy_index: int | None = None) -> int | None:
    """Busca el micrófono por nombre (los índices de PortAudio cambian entre reinicios)."""
    devices = list_input_devices()
    if name:
        return next((i for i, n in devices if n == name), None)
    if legacy_index is not None and any(i == legacy_index for i, _ in devices):
        return legacy_index
    return None


def device_name(index: int | None) -> str:
    return next((n for i, n in list_input_devices() if i == index), "") if index is not None else ""


class Recorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._rate = SAMPLE_RATE
        self.level = 0.0  # 0..1, último bloque
        self.started_at = 0.0

    @property
    def recording(self) -> bool:
        return self._stream is not None

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at if self.recording else 0.0

    def start(self, device: int | None = None) -> None:
        if self._stream is not None:
            return
        with self._lock:
            self._chunks = []
        self.level = 0.0
        try:
            self._rate = SAMPLE_RATE
            self._stream = self._open(device, SAMPLE_RATE)
        except Exception:  # noqa: BLE001 - el dispositivo no acepta 16 kHz: se remuestrea al final
            info = sd.query_devices(device, "input")
            self._rate = int(info["default_samplerate"])
            self._stream = self._open(device, self._rate)
        self._stream.start()
        self.started_at = time.monotonic()

    def _open(self, device, rate) -> sd.InputStream:
        return sd.InputStream(
            samplerate=rate,
            channels=1,
            dtype="float32",
            device=device,
            blocksize=int(rate * 0.03),
            callback=self._callback,
        )

    def _callback(self, indata, frames, time_info, status):  # hilo de PortAudio
        mono = indata[:, 0].copy()
        with self._lock:
            self._chunks.append(mono)
        self.level = level_of(mono)

    def stop(self) -> tuple[np.ndarray, float]:
        """Detiene la grabación y devuelve (audio 16 kHz float32, duración en segundos)."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                log.exception("Error cerrando el stream de audio")
        with self._lock:
            chunks, self._chunks = self._chunks, []
        self.level = 0.0
        if not chunks:
            return np.zeros(0, dtype=np.float32), 0.0
        audio = np.concatenate(chunks)
        if self._rate != SAMPLE_RATE:
            n = int(len(audio) * SAMPLE_RATE / self._rate)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio
            ).astype(np.float32)
        return audio, len(audio) / SAMPLE_RATE
