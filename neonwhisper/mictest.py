"""Pruebas de audio: el micrófono para dictar, y las dos fuentes que se graban en una reunión."""
import logging
import math
import time

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, QTimer, Signal

from neonwhisper.audio import SAMPLE_RATE, Recorder, level_of

log = logging.getLogger(__name__)
RECORD_SECONDS = 4
SILENT_PEAK = 0.18  # ~ -41 dB: por debajo de esto no se escucha voz


def play(audio: np.ndarray) -> None:
    try:
        sd.play(audio, SAMPLE_RATE)
    except sd.PortAudioError:  # la salida no acepta 16 kHz: se remuestrea a 48 kHz
        n = len(audio) * 3
        resampled = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
        sd.play(resampled, 48000)


class MicTester(QObject):
    # estado: recording | playing | ok | silent | error | idle ; mensaje para mostrar
    changed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.state = "idle"
        self._recorder = Recorder()
        self._audio: np.ndarray | None = None
        self._started = 0.0
        self._peak = 0.0
        self._timer = QTimer(self, interval=100, timeout=self._tick)

    @property
    def active(self) -> bool:
        return self.state in ("recording", "playing")

    @property
    def level(self) -> float:
        if self.state == "recording":
            return self._recorder.level
        if self.state == "playing" and self._audio is not None:
            pos = int((time.monotonic() - self._started) * SAMPLE_RATE)
            return level_of(self._audio[pos:pos + 480])
        return 0.0

    def start(self, device: int | None) -> None:
        self.stop()
        try:
            self._recorder.start(device)
        except Exception as exc:  # noqa: BLE001
            log.exception("No se pudo abrir el micrófono para la prueba")
            self._set("error", f"No se pudo abrir el micrófono: {str(exc)[:90]}")
            return
        self._started = time.monotonic()
        self._peak = 0.0
        self._set("recording", f"Habla ahora…  {RECORD_SECONDS}")
        self._timer.start()

    def stop(self) -> None:
        was_active = self.active
        self._timer.stop()
        if self._recorder.recording:
            self._recorder.stop()
        if self.state == "playing":
            sd.stop()
        if was_active:
            self._set("idle", "Prueba detenida.")

    def _tick(self) -> None:
        now = time.monotonic()
        if self.state == "recording":
            self._peak = max(self._peak, self._recorder.level)
            left = RECORD_SECONDS - (now - self._started)
            if left > 0:
                self._set("recording", f"Habla ahora…  {math.ceil(left)}")
                return
            audio, _ = self._recorder.stop()
            if self._peak < SILENT_PEAK:
                self._timer.stop()
                self._set("silent", "⚠ No se detectó sonido. Revisa que el micrófono esté conectado y sin silenciar, o elige otro.")
                return
            self._audio = audio
            try:
                play(audio)
            except Exception as exc:  # noqa: BLE001
                log.exception("No se pudo reproducir la prueba")
                self._timer.stop()
                self._set("ok", f"✓ El micrófono funciona (nivel máx. {int(self._peak * 100)}%), pero no se pudo reproducir: {str(exc)[:60]}")
                return
            self._started = now
            self._set("playing", "Reproduciendo tu grabación…")
        elif self.state == "playing" and self._audio is not None:
            if now - self._started > len(self._audio) / SAMPLE_RATE + 0.3:
                self._timer.stop()
                hint = "  Suena bajo: acércate o sube el volumen del micrófono en Windows." if self._peak < 0.4 else ""
                self._set("ok", f"✓ Tu micrófono funciona · nivel máximo {int(self._peak * 100)}%.{hint}")

    def _set(self, state: str, message: str) -> None:
        self.state = state
        self.changed.emit(state, message)


class MeetingAudioTester(QObject):
    """Comprueba en 5 segundos qué se grabaría de una reunión: tu voz y lo que suena en tu PC.

    Es la forma de saber *antes* de la reunión si Windows expone un dispositivo «loopback»,
    en vez de descubrirlo al escuchar la grabación.
    """

    changed = Signal(str, str)  # estado (testing | ok | warn | error | idle), mensaje
    TEST_SECONDS = 5

    def __init__(self):
        super().__init__()
        self.state = "idle"
        self._sources: dict[str, object] = {}
        self._peaks = {"mic": 0.0, "system": 0.0}
        self._started = 0.0
        self._label = ""
        self._timer = QTimer(self, interval=100, timeout=self._tick)

    @property
    def active(self) -> bool:
        return self.state == "testing"

    @property
    def level(self) -> float:
        return max((getattr(s, "level", 0.0) for s in self._sources.values()), default=0.0)

    def start(self, mic_device: int | None, speaker: str = "") -> None:
        from neonwhisper.meetings import Source, open_system_audio

        self.stop()
        self._peaks = {"mic": 0.0, "system": 0.0}
        self._sources = {}
        try:
            mic = Source(mic_device)
            mic.start()
            self._sources["mic"] = mic
        except Exception as exc:  # noqa: BLE001
            log.exception("No se pudo abrir el micrófono para la prueba de reunión")
            self._set("error", f"No se pudo abrir el micrófono: {str(exc)[:90]}")
            return
        self._label = ""
        try:
            system = open_system_audio(speaker)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo abrir el audio del sistema para la prueba")
            system = None
        if system is not None:
            self._sources["system"] = system
            self._label = getattr(system, "label", "") or "salida de audio"
        self._started = time.monotonic()
        self._set("testing", f"Habla y pon un video o música…  {self.TEST_SECONDS}")
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        for source in self._sources.values():
            source.stop()
        self._sources = {}
        if self.state == "testing":
            self._set("idle", "Prueba detenida.")

    def _tick(self) -> None:
        for kind, source in self._sources.items():
            self._peaks[kind] = max(self._peaks[kind], source.level)
        left = self.TEST_SECONDS - (time.monotonic() - self._started)
        if left > 0:
            self._set("testing", f"Habla y pon un video o música…  {math.ceil(left)}")
            return
        self.stop()
        self._report()

    def _report(self) -> None:
        mic_ok = self._peaks["mic"] >= SILENT_PEAK
        mic = f"{'✓' if mic_ok else '⚠'} Tu micrófono: {int(self._peaks['mic'] * 100)}%"
        if not self._label:
            self._set("warn", f"{mic}  ·  ✗ Audio del sistema: no se pudo capturar la salida de audio, "
                              "así que de una reunión solo se grabaría tu voz. Elige otra salida y vuelve a probar.")
            return
        system_ok = self._peaks["system"] >= SILENT_PEAK
        system = f"{'✓' if system_ok else '⚠'} Audio del sistema: {int(self._peaks['system'] * 100)}% ({self._label})"
        if mic_ok and system_ok:
            self._set("ok", f"{mic}  ·  {system}")
        elif system_ok:
            self._set("warn", f"{mic} — no se te oyó, revisa el micrófono.  ·  {system}")
        else:
            self._set("warn", f"{mic}  ·  {system} — no sonó nada; prueba otra vez con un video puesto.")

    def _set(self, state: str, message: str) -> None:
        self.state = state
        self.changed.emit(state, message)
