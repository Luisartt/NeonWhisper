"""Graba lo que suena en tu PC (la voz de los demás en una reunión) con WASAPI loopback.

Windows solo expone dispositivos de entrada «loopback» o «Stereo Mix» si el driver los trae, y
en la mayoría de las PCs modernas no existen: por eso antes solo se grababa el micrófono. Aquí se
abre directamente el altavoz en modo loopback con WASAPI (vía `soundcard`), que funciona con
cualquier salida: bocinas, audífonos USB o HDMI.

La fuente que devuelve `open_system_source()` se comporta igual que `recorder.Source`
(buffer, `level`, `muted`, `take()`…), así que el grabador mezcla las dos sin saber de dónde viene cada una.
"""
import logging
import threading
import time

import numpy as np

from neonwhisper.audio import SAMPLE_RATE, level_of

log = logging.getLogger(__name__)

BLOCK_FRAMES = 1600  # 0.1 s a 16 kHz
OPEN_TIMEOUT = 1.5  # corto a propósito: esto se espera desde el hilo de la interfaz


def _soundcard():
    """Se importa tarde: solo hace falta al grabar una reunión."""
    import soundcard

    # No se toca su gestión de COM: `soundcard` inicializa COM al importarse y lo suelta en su
    # destructor, y ese par tiene que quedar en el MISMO hilo. Por eso la app lo importa temprano
    # desde el hilo principal (ver `app.main`), donde sounddevice y Qt ya dejaron el hilo en STA:
    # así `soundcard` ve otro modelo, no administra COM y no hay nada que soltar al cerrar.
    return soundcard


def available() -> bool:
    try:
        _soundcard()
        return True
    except Exception:  # noqa: BLE001
        log.exception("soundcard no está disponible")
        return False


def list_speakers() -> list[str]:
    """Salidas de audio que se pueden capturar (la primera es la predeterminada)."""
    try:
        sc = _soundcard()
        default = str(sc.default_speaker().name)
        names = [str(s.name) for s in sc.all_speakers()]
    except Exception:  # noqa: BLE001
        log.exception("No se pudieron listar las salidas de audio")
        return []
    return [default] + [n for n in names if n != default]


def default_speaker_name() -> str:
    try:
        return str(_soundcard().default_speaker().name)
    except Exception:  # noqa: BLE001
        return ""


def _loopback_for(name: str = ""):
    """Micrófono virtual que graba lo que sale por ese altavoz (o por el predeterminado)."""
    sc = _soundcard()
    speaker = None
    if name:
        speaker = next((s for s in sc.all_speakers() if str(s.name) == name), None)
        if speaker is None:
            log.info("La salida «%s» ya no existe: se usa la predeterminada", name)
    if speaker is None:
        speaker = sc.default_speaker()
    return sc.get_microphone(str(speaker.name), include_loopback=True), str(speaker.name)


class SystemAudioSource:
    """Lee el loopback del altavoz en un hilo propio y deja el audio listo para mezclar."""

    loopback = True

    def __init__(self, speaker: str = "", muted: bool = False):
        self.speaker = speaker
        self.muted = muted
        self.label = ""
        self.buffer = np.zeros(0, dtype=np.float32)
        self.level = 0.0
        self.last_block = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: Exception | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        # Un Event nuevo por arranque: si se reutilizara, un `clear()` podría revivir al hilo
        # anterior y acabaríamos con dos capturas escribiendo en el mismo buffer.
        self._stop = threading.Event()
        self._ready.clear()
        self._error = None
        with self._lock:  # lo que quedó del intento anterior ya no está alineado con el micrófono
            self.buffer = np.zeros(0, dtype=np.float32)
        self._thread = threading.Thread(target=self._run, args=(self._stop,), name="loopback", daemon=True)
        self._thread.start()
        if not self._ready.wait(OPEN_TIMEOUT):
            self._stop.set()
            thread, self._thread = self._thread, None
            if thread is not None:
                thread.join(timeout=2)
            raise RuntimeError("El audio del sistema tardó demasiado en abrirse")
        if self._error is not None:
            raise RuntimeError(f"No se pudo capturar el audio del sistema: {self._error}")
        self.last_block = time.monotonic()

    def _run(self, stop: threading.Event) -> None:
        com = False
        try:
            import ctypes

            # WASAPI necesita COM en el hilo que lo usa. Se suelta en el `finally` de este mismo
            # hilo: soltarlo desde otro es lo que antes tumbaba la app.
            # S_OK (0) y S_FALSE (1) suman a la cuenta de COM: las dos hay que soltarlas.
            com = ctypes.windll.ole32.CoInitializeEx(None, 0x2) in (0, 1)
        except Exception:  # noqa: BLE001 - fuera de Windows no hace falta
            pass
        try:
            mic, self.label = _loopback_for(self.speaker)
            with mic.recorder(samplerate=SAMPLE_RATE, blocksize=BLOCK_FRAMES) as rec:
                self._ready.set()
                log.info("Audio del sistema: capturando «%s»", self.label)
                while not stop.is_set():
                    block = rec.record(numframes=BLOCK_FRAMES)
                    mono = block.mean(axis=1) if block.ndim > 1 else block
                    mono = mono.astype(np.float32)
                    with self._lock:
                        self.buffer = np.concatenate([self.buffer, mono])
                    self.level = 0.0 if self.muted else level_of(mono)
                    self.last_block = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            self._error = exc
            log.exception("Falló la captura del audio del sistema")
        finally:
            self._ready.set()  # que start() no se quede esperando si falló al abrir
            if com:
                try:
                    import ctypes

                    ctypes.windll.ole32.CoUninitialize()
                except Exception:  # noqa: BLE001
                    log.exception("No se pudo soltar COM del hilo de captura")

    @property
    def alive(self) -> bool:
        """False si el hilo de captura murió (se desconectaron los audífonos, por ejemplo)."""
        return self._thread is not None and self._thread.is_alive() and self._error is None

    @property
    def error(self) -> str:
        return str(self._error) if self._error else ""

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
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2)
        self.level = 0.0

    def retarget(self, speaker: str) -> bool:
        """Cambia a otra salida en caliente (la reunión empezó a sonar por otro dispositivo)."""
        if not speaker or speaker == self.label:
            return False
        muted, previous = self.muted, self.label
        self.stop()
        self.speaker, self.muted = speaker, muted
        try:
            self.start()
        except Exception:  # noqa: BLE001 - si la nueva salida falla, se vuelve a la anterior
            log.exception("No se pudo cambiar la captura a «%s»", speaker)
            self.speaker = previous
            try:
                self.start()
            except Exception:  # noqa: BLE001
                log.exception("Tampoco se pudo volver a «%s»", previous)
            return False
        log.info("Audio del sistema: ahora se captura «%s»", self.label)
        return True


def open_system_source(speaker: str = "", muted: bool = False) -> SystemAudioSource:
    """Abre la captura del sistema y la devuelve lista; lanza excepción si no se puede."""
    source = SystemAudioSource(speaker, muted)
    source.start()
    return source
