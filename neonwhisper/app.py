"""Punto de entrada: conecta atajo → micrófono → Whisper → pegado → historial."""
import ctypes
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from neonwhisper import APP_NAME, sounds
from neonwhisper.audio import Recorder
from neonwhisper.config import Settings
from neonwhisper.history import History
from neonwhisper.hotkeys import HotkeyManager, is_safe_hotkey
from neonwhisper.paster import Paster
from neonwhisper.paths import LOG_FILE, ROOT
from neonwhisper.transcriber import Transcriber
from neonwhisper.ui import theme as T
from neonwhisper.ui.overlay import Overlay
from neonwhisper.ui.widgets import make_app_icon
from neonwhisper.ui.window import MainWindow

log = logging.getLogger(APP_NAME)
MIN_SECONDS = 0.35
SINGLE_INSTANCE_KEY = "NeonWhisper-single-instance"


class Controller(QObject):
    request_load = Signal(str, str)
    request_transcribe = Signal(object, str, str)

    def __init__(self, app: QApplication, force_minimized: bool = False):
        super().__init__()
        self.app = app
        self.quitting = False
        self.capturing_hotkey = False
        self.settings = Settings.load()
        self.history = History()
        self.recorder = Recorder()
        self.paster = Paster()
        self.model_state = "loading"
        self.pending: list = []
        self.jobs = 0
        self._tray_hint_shown = False
        sounds.generate(self.settings.sound_volume)

        self.worker_thread = QThread()
        self.transcriber = Transcriber()
        self.transcriber.moveToThread(self.worker_thread)
        self.request_load.connect(self.transcriber.load)
        self.request_transcribe.connect(self.transcriber.transcribe)
        self.transcriber.status_changed.connect(self.on_model_status)
        self.transcriber.finished.connect(self.on_transcribed)
        self.transcriber.failed.connect(self.on_failed)
        self.worker_thread.start()

        self.icon_idle = make_app_icon(False)
        self.icon_active = make_app_icon(True)
        self.window = MainWindow(self)
        self.overlay = Overlay(lambda: self.recorder.level)
        self.overlay.cancel_requested.connect(self.cancel_recording)

        self.hotkeys = HotkeyManager()
        try:
            self.hotkeys.set_hotkey(self.settings.hotkey)
        except ValueError:
            self.settings.hotkey = Settings().hotkey
            self.hotkeys.set_hotkey(self.settings.hotkey)
        self.hotkeys.pressed.connect(self.on_hotkey_pressed)
        self.hotkeys.released.connect(self.on_hotkey_released)
        self.hotkeys.escape_pressed.connect(self.cancel_recording)
        self.hotkeys.captured.connect(self.on_hotkey_captured)
        self.hotkeys.capture_cancelled.connect(self.cancel_hotkey_capture)

        self._build_tray()
        self.refresh_stats()
        self._set_ui_state()
        self.request_load.emit(self.settings.model, self.settings.device)

        if not (self.settings.start_minimized or force_minimized):
            self.show_window()

    # --- bandeja --------------------------------------------------------------
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.icon_idle, self)
        menu = QMenu()
        open_action = QAction("Abrir NeonWhisper", menu, triggered=self.show_window)
        self.tray_record = QAction("Empezar a dictar", menu, triggered=self.toggle_recording)
        history_action = QAction("Historial", menu, triggered=lambda: (self.show_window(), self.window.go_to(1)))
        quit_action = QAction("Salir", menu, triggered=self.quit)
        for a in (open_action, self.tray_record, history_action):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        self._tray_menu = menu
        self._update_tray_tooltip()
        self.tray.show()

    def _update_tray_tooltip(self) -> None:
        pretty = " + ".join(p for p in self.settings.hotkey.split("+")).title()
        self.tray.setToolTip(f"NeonWhisper · {pretty}")

    def show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def on_window_hidden(self) -> None:
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.tray.showMessage(
                "NeonWhisper sigue activo",
                "Tu atajo funciona desde la bandeja. Clic derecho en el ícono para salir.",
                self.icon_idle, 3500,
            )

    def quit(self) -> None:
        self.quitting = True
        if self.recorder.recording:
            self.recorder.stop()
        self.hotkeys.shutdown()
        self.tray.hide()
        self.worker_thread.quit()
        self.worker_thread.wait(1500)
        self.app.quit()

    # --- estado visual --------------------------------------------------------
    def _set_ui_state(self, message: str | None = None) -> None:
        home = self.window.home
        recording = self.recorder.recording
        self.window.set_recording_indicator(recording)
        self.tray.setIcon(self.icon_active if recording else self.icon_idle)
        self.tray_record.setText("Detener y pegar" if recording else "Empezar a dictar")
        if recording:
            home.set_state("recording", "Escuchando…")
        elif self.jobs:
            home.set_state("processing", "Transcribiendo…" if self.model_state == "ready" else "Cargando Whisper…")
        elif self.model_state == "error":
            home.set_state("disabled", "No se pudo cargar Whisper")
        elif self.model_state != "ready":
            home.set_state("idle", "Cargando Whisper…")
        else:
            home.set_state("idle", message or "Listo para dictar")

    def refresh_stats(self, seconds: float | None = None) -> None:
        count, words = self.history.stats()
        self.window.home.set_stats(count, words, seconds)

    # --- atajo ---------------------------------------------------------------
    def on_hotkey_pressed(self) -> None:
        if self.settings.mode == "hold":
            self.start_recording()
        else:
            self.toggle_recording()

    def on_hotkey_released(self) -> None:
        if self.settings.mode == "hold" and self.recorder.recording:
            self.stop_recording()

    def begin_hotkey_capture(self) -> None:
        if self.recorder.recording:
            self.cancel_recording()
        self.capturing_hotkey = True
        self.hotkeys.start_capture()
        self.window.settings.set_capturing(True)

    def cancel_hotkey_capture(self) -> None:
        self.capturing_hotkey = False
        self.hotkeys.cancel_capture()
        self.window.settings.set_capturing(False)

    def on_hotkey_captured(self, hotkey: str) -> None:
        self.capturing_hotkey = False
        self.window.settings.set_capturing(False)
        if not is_safe_hotkey(hotkey):
            self.window.settings.show_capture_message(
                f"«{hotkey}» se activaría al escribir normal. Usa al menos Ctrl, Alt, Shift o Win (o una tecla F)."
            )
            return
        try:
            self.hotkeys.set_hotkey(hotkey)
        except ValueError as exc:
            self.window.settings.show_capture_message(str(exc))
            self.hotkeys.set_hotkey(self.settings.hotkey)
            return
        self.settings.hotkey = hotkey
        self.settings.save()
        self.window.settings.set_hotkey(hotkey)
        self.window.home.set_hotkey(hotkey, self.settings.mode)
        self.window.settings.show_capture_message("Atajo guardado ✓")
        self._update_tray_tooltip()

    # --- grabación -----------------------------------------------------------
    def toggle_recording(self) -> None:
        if self.recorder.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self) -> None:
        if self.recorder.recording or self.capturing_hotkey:
            return
        if self.model_state == "error":
            self._notify("Whisper no está disponible: revisa Ajustes", error=True)
            return
        try:
            self.recorder.start(self.settings.input_device)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo abrir el micrófono")
            self._notify("No se pudo abrir el micrófono", error=True)
            return
        if self.settings.sounds:
            sounds.play("start")
        if self.settings.show_overlay:
            self.overlay.show_recording()
        self._set_ui_state()

    def stop_recording(self) -> None:
        if not self.recorder.recording:
            return
        audio, seconds = self.recorder.stop()
        if self.settings.sounds:
            sounds.play("stop")
        if seconds < MIN_SECONDS:
            self._notify("Muy corto: habla un poco más")
            self._set_ui_state()
            return
        self.jobs += 1
        if self.settings.show_overlay:
            self.overlay.show_processing("Transcribiendo…" if self.model_state == "ready" else "Cargando Whisper…")
        if self.model_state == "ready":
            self.request_transcribe.emit(audio, self.settings.language, self.settings.initial_prompt)
        else:
            self.pending.append(audio)
        self._set_ui_state()

    def cancel_recording(self) -> None:
        if not self.recorder.recording:
            return
        self.recorder.stop()
        self._notify("Cancelado")
        self._set_ui_state()

    # --- resultados ------------------------------------------------------------
    def on_model_status(self, state: str, detail: str) -> None:
        self.model_state = state
        self.window.set_model_status(state, detail)
        if state == "ready":
            for audio in self.pending:
                self.request_transcribe.emit(audio, self.settings.language, self.settings.initial_prompt)
            self.pending.clear()
        elif state == "error" and self.pending:
            self.jobs -= len(self.pending)
            self.pending.clear()
            self._notify("No se pudo cargar Whisper", error=True)
        self._set_ui_state()

    def on_transcribed(self, text: str, audio_seconds: float, language: str, elapsed: float) -> None:
        self.jobs = max(0, self.jobs - 1)
        if not text:
            self._notify("No se detectó voz", error=True)
            self._set_ui_state()
            return
        entry = self.history.add(text, audio_seconds, language)
        own_window_focused = QApplication.activeWindow() is not None
        if self.settings.auto_paste and not own_window_focused:
            self.paster.paste(text, self.settings.restore_clipboard)
            result = "Pegado"
        else:
            self.paster.copy(text)
            result = "Copiado"
        words = len(text.split())
        if self.settings.show_overlay and not self.recorder.recording:
            self.overlay.show_result(f"✓ {result} · {words} palabra{'s' if words != 1 else ''}")
        self.window.home.set_last(entry.text)
        self.window.history.refresh()
        self.refresh_stats(elapsed)
        self._set_ui_state(f"{result} en {elapsed:.1f} s")
        log.info("Transcrito %.1fs de audio en %.2fs (%s)", audio_seconds, elapsed, language)

    def on_failed(self, message: str) -> None:
        self.jobs = max(0, self.jobs - 1)
        self._notify(f"Error: {message[:60]}", error=True)
        self._set_ui_state()

    def _notify(self, text: str, error: bool = False) -> None:
        if error and self.settings.sounds:
            sounds.play("error")
        if self.settings.show_overlay and not self.recorder.recording:
            self.overlay.show_result(text, error=error)
        self.window.home.status.setText(text)

    # --- ajustes e historial -------------------------------------------------
    def update_setting(self, key: str, value) -> None:
        if getattr(self.settings, key) == value:
            return
        setattr(self.settings, key, value)
        self.settings.save()
        if key in ("model", "device"):
            self.model_state = "loading"
            self.window.set_model_status("loading", f"Cargando {self.settings.model}…")
            self._set_ui_state()
            self.request_load.emit(self.settings.model, self.settings.device)
        elif key == "sound_volume":
            sounds.generate(value)
            sounds.play("start")
        elif key == "mode":
            self.window.home.set_hotkey(self.settings.hotkey, value)
        elif key == "launch_at_startup":
            set_launch_at_startup(value)

    def test_sound(self) -> None:
        sounds.play("start")

    def delete_entry(self, entry_id: int) -> None:
        self.history.delete(entry_id)
        self.window.history.refresh()
        self.refresh_stats()

    def clear_history(self) -> None:
        self.history.clear()
        self.window.history.refresh()
        self.refresh_stats()


def set_launch_at_startup(enabled: bool) -> None:
    import winreg

    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            command = f'"{pythonw}" "{ROOT / "NeonWhisper.pyw"}" --minimized'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def _setup_logging() -> None:
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    sys.excepthook = lambda *exc: log.critical("Error no controlado", exc_info=exc)


def _already_running() -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SINGLE_INSTANCE_KEY)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        return True
    return False


def main() -> None:
    _setup_logging()
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Luisart.NeonWhisper")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    if _already_running():
        return
    app.setStyleSheet(T.STYLESHEET)
    app.setWindowIcon(make_app_icon())

    ctl = Controller(app, force_minimized="--minimized" in sys.argv)
    server = QLocalServer()
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server.listen(SINGLE_INSTANCE_KEY)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), ctl.show_window()))
    log.info("NeonWhisper iniciado")
    sys.exit(app.exec())
