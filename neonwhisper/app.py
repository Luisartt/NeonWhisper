"""Punto de entrada: conecta atajo → micrófono → Whisper → pegado → historial."""
import ctypes
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from neonwhisper import APP_NAME, sounds
from neonwhisper.audio import Recorder, resolve_input_device
from neonwhisper.config import MODELS, Settings
from neonwhisper.downloader import DownloadManager
from neonwhisper.fmt import fmt_eta
from neonwhisper.history import History
from neonwhisper.hotkeys import HotkeyManager, is_safe_hotkey
from neonwhisper.paster import Paster
from neonwhisper.paths import LOG_FILE, ROOT, model_downloaded
from neonwhisper.transcriber import Transcriber
from neonwhisper.ui import theme as T
from neonwhisper.ui.overlay import Overlay
from neonwhisper.ui.widgets import make_app_icon
from neonwhisper.ui.window import MainWindow

log = logging.getLogger(APP_NAME)
MIN_SECONDS = 0.35
OVERLAY_KEYS = ("overlay_style", "overlay_scale", "overlay_bg_opacity", "overlay_opacity")
SINGLE_INSTANCE_KEY = "NeonWhisper-single-instance"


class Controller(QObject):
    request_load = Signal(str, str)
    request_transcribe = Signal(object, str, str)
    download_changed = Signal(str)
    download_installed = Signal(str)

    def __init__(self, app: QApplication, force_minimized: bool = False):
        super().__init__()
        self.app = app
        self.quitting = False
        self.capturing_hotkey = False
        self.settings = Settings.load()
        self._apply_theme()
        sync_launch_at_startup(self.settings)
        self._reconcile_models()
        self.downloads = DownloadManager(on_change=self.download_changed.emit, on_installed=self.download_installed.emit)
        self.download_changed.connect(self.on_download_changed)
        self.download_installed.connect(self.on_download_installed)
        self.history = History()
        self.recorder = Recorder()
        self.paster = Paster()
        self.model_state = "loading"
        self.model_usable = False
        self._load_attempts = 0
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

        self.window = MainWindow(self)
        self.overlay = Overlay(lambda: self.recorder.level)
        self.overlay.cancel_requested.connect(self.cancel_recording)
        self._apply_overlay_look()
        self._save_timer = QTimer(self, singleShot=True, interval=400, timeout=self.settings.save)

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
        if model_downloaded(self.settings.model):
            self.window.set_model_status("loading", f"{self.settings.model} · instalado ✓")
        self.refresh_stats()
        self._set_ui_state()
        self.request_load.emit(self.settings.model, self.settings.device)
        self._resume_downloads()

        if not (self.settings.start_minimized or force_minimized):
            self.show_window()

    # --- tema de la interfaz ---------------------------------------------------
    def _apply_theme(self) -> None:
        """Aplica el tema guardado a toda la app: hoja de estilos, íconos y la ventana si ya existe."""
        T.set_theme(self.settings.ui_theme)
        self.app.setStyleSheet(T.build_stylesheet())
        self.icon_idle = make_app_icon(False)
        self.icon_active = make_app_icon(True)
        self.app.setWindowIcon(self.icon_idle)
        recording = getattr(self, "recorder", None) and self.recorder.recording
        if getattr(self, "tray", None):
            self.tray.setIcon(self.icon_active if recording else self.icon_idle)
        if getattr(self, "window", None):
            self.window.restyle()

    def _sync_overlay_style(self) -> None:
        """Deja la barra flotante con el diseño del mismo nombre que el tema."""
        if self.settings.overlay_style == self.settings.ui_theme:
            return
        self.settings.overlay_style = self.settings.ui_theme
        self._apply_overlay_look()
        self.preview_overlay()

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
        if self._save_timer.isActive():
            self._save_timer.stop()
            self.settings.save()
        self.window.settings.stop_mic_test()
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
            home.set_state("processing", "Transcribiendo…" if self.model_usable else "Iniciando Whisper…")
        elif not self.model_usable and self.model_state == "error":
            home.set_state("disabled", "No se pudo cargar Whisper")
        elif not self.model_usable:
            home.set_state("idle", "Iniciando Whisper…")
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
        if self.model_state == "error" and not self.model_usable:
            self._notify("Whisper no está disponible: revisa Ajustes", error=True)
            return
        self.window.settings.stop_mic_test()
        try:
            self.recorder.start(resolve_input_device(self.settings.input_device_name, self.settings.input_device))
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
            self.overlay.show_processing("Transcribiendo…" if self.model_usable else "Iniciando Whisper…")
        if self.model_usable:
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
            self.model_usable = True
            self._load_attempts = 0
            for audio in self.pending:
                self.request_transcribe.emit(audio, self.settings.language, self.settings.initial_prompt)
            self.pending.clear()
            self.window.settings.refresh_models()
        elif state == "error" and not self.model_usable:
            if self._load_attempts < 3:  # p. ej. al encender la PC el driver de la GPU aún no está listo
                self._load_attempts += 1
                self.window.set_model_status("loading", f"Reintentando ({self._load_attempts}/3)…")
                QTimer.singleShot(8000, lambda: self.request_load.emit(self.settings.model, self.settings.device))
            elif self.pending:
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
        if key in OVERLAY_KEYS:  # los deslizadores cambian muchas veces por segundo
            self._save_timer.start()
            self._apply_overlay_look()
            self.preview_overlay()
            return
        self.settings.save()
        if key in ("model", "device"):
            self.request_load.emit(self.settings.model, self.settings.device)
        elif key == "sound_volume":
            sounds.generate(value)
            sounds.play("start")
        elif key == "mode":
            self.window.home.set_hotkey(self.settings.hotkey, value)
        elif key == "launch_at_startup":
            set_launch_at_startup(value)
        elif key in ("ui_theme", "theme_syncs_overlay"):
            if key == "ui_theme":
                self._apply_theme()
            if self.settings.theme_syncs_overlay:
                self._sync_overlay_style()
            self.settings.save()
            self.window.settings.set_theme_selection(self.settings.ui_theme)

    # --- barra flotante --------------------------------------------------------
    def _apply_overlay_look(self) -> None:
        s = self.settings
        self.overlay.apply_appearance(s.overlay_style, s.overlay_scale, s.overlay_bg_opacity, s.overlay_opacity)

    def preview_overlay(self) -> None:
        if not (self.recorder.recording or self.jobs):
            self.overlay.show_preview(3000)

    def reset_overlay_look(self) -> None:
        defaults = Settings()
        for key in OVERLAY_KEYS:
            setattr(self.settings, key, getattr(defaults, key))
        if self.settings.theme_syncs_overlay:
            self.settings.overlay_style = self.settings.ui_theme
        self.settings.save()
        self._apply_overlay_look()
        self.preview_overlay()

    # --- modelos y descargas ---------------------------------------------------
    def _reconcile_models(self) -> None:
        """El modelo en uso siempre debe estar instalado; si no, se usa otro mientras se descarga."""
        s = self.settings
        if not model_downloaded(s.model):
            fallback = next((m for m in MODELS if model_downloaded(m)), None)
            if fallback:
                s.pending_model = s.pending_model or s.model
                s.model = fallback
            else:
                s.pending_model = s.model
        if s.pending_model and model_downloaded(s.pending_model):
            s.model, s.pending_model = s.pending_model, ""
        s.save()

    def _resume_downloads(self) -> None:
        for model in self.downloads.interrupted():
            self.downloads.start(model)
        pending = self.settings.pending_model
        if pending and self.downloads.info(pending).state == "missing":
            self.downloads.start(pending)
        self._update_download_summary()

    def start_download(self, model: str) -> None:
        self.downloads.start(model)

    def pause_download(self, model: str) -> None:
        self.downloads.pause(model)

    def resume_download(self, model: str) -> None:
        self.downloads.start(model)

    def cancel_download(self, model: str) -> None:
        if self.settings.pending_model == model:
            self.update_setting("pending_model", "")
        self.downloads.cancel(model)

    def delete_model(self, model: str) -> None:
        if model != self.settings.model:
            self.downloads.delete(model)

    def use_model(self, model: str) -> None:
        if model_downloaded(model):
            self.update_setting("model", model)
            self.window.settings.refresh_models()

    def on_download_changed(self, model: str) -> None:
        self.window.settings.refresh_models(model)
        self._update_download_summary()

    def on_download_installed(self, model: str) -> None:
        name = MODELS.get(model, model).split(" · ")[0]
        self.tray.showMessage("Modelo descargado", f"{name} ya está instalado.", self.icon_idle, 3000)
        if model == self.settings.pending_model or not self.model_usable:
            self.update_setting("pending_model", "")
            self.use_model(model)
        self.window.settings.refresh_models()
        self._update_download_summary()

    def _update_download_summary(self) -> None:
        order = {"downloading": 0, "verifying": 1, "connecting": 2, "error": 3, "paused": 4}
        active = sorted(
            ((m, info) for m in MODELS if (info := self.downloads.info(m)).state in order),
            key=lambda item: order[item[1].state],
        )
        if not active:
            self.window.set_download_summary(None)
            return
        model, info = active[0]
        pct = f"{info.fraction * 100:.0f}%"
        text, mode = {
            "downloading": (f"Descargando {model} · {pct} · {fmt_eta(info.eta)}", "active"),
            "verifying": (f"Verificando {model}…", "indeterminate"),
            "connecting": (f"Conectando para {model}…", "indeterminate"),
            "error": (f"Error al descargar {model}", "error"),
            "paused": (f"{model} en pausa · {pct}", "paused"),
        }[info.state]
        if len(active) > 1:
            text += f"  (+{len(active) - 1})"
        self.window.set_download_summary(text, info.fraction, mode)

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


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _startup_command() -> str:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{ROOT / "NeonWhisper.pyw"}" --minimized'


def get_launch_at_startup() -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, APP_NAME)[0]
    except OSError:
        return None


def set_launch_at_startup(enabled: bool) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def sync_launch_at_startup(settings: Settings) -> None:
    """El registro manda: refleja su estado en Ajustes y corrige la ruta si la carpeta se movió."""
    current = get_launch_at_startup()
    settings.launch_at_startup = current is not None
    if current is not None and current != _startup_command():
        try:
            set_launch_at_startup(True)
        except OSError:
            log.exception("No se pudo actualizar el inicio con Windows")


def _setup_logging() -> None:
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    sys.excepthook = lambda *exc: log.critical("Error no controlado", exc_info=exc)


def _already_running(show: bool) -> bool:
    """Si ya hay una instancia abierta, le pide mostrarse (salvo arranque minimizado) y devuelve True."""
    sock = QLocalSocket()
    sock.connectToServer(SINGLE_INSTANCE_KEY)
    if not sock.waitForConnected(300):
        return False
    if show:
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def main() -> None:
    _setup_logging()
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Luisart.NeonWhisper")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    minimized = "--minimized" in sys.argv
    if _already_running(show=not minimized):
        return

    ctl = Controller(app, force_minimized=minimized)
    server = QLocalServer()
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server.listen(SINGLE_INSTANCE_KEY)
    connections = []

    def on_connection() -> None:
        conn = server.nextPendingConnection()
        connections.append(conn)

        def on_data() -> None:
            if b"show" in bytes(conn.readAll()):
                ctl.show_window()

        conn.readyRead.connect(on_data)
        conn.disconnected.connect(lambda: (connections.remove(conn), conn.deleteLater()))

    server.newConnection.connect(on_connection)
    log.info("NeonWhisper iniciado")
    sys.exit(app.exec())
