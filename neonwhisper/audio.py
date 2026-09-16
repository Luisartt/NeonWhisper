"""Grabación del micrófono a 16 kHz mono con medidor de nivel en tiempo real."""
import logging
import math
import threading
import time

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
log = logging.getLogger(__name__)


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
        rms = float(np.sqrt(np.mean(mono * mono))) + 1e-9
        db = 20 * math.log10(rms)
        self.level = max(0.0, min(1.0, (db + 55) / 45)) ** 1.4

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
