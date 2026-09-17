"""Detecta cuándo entras y sales de una reunión, sin instalar nada extra.

Dos señales, ambas nativas de Windows:

1. **El micrófono en uso.** Windows anota en el registro qué app está usando el micrófono
   (`CapabilityAccessManager\\ConsentStore\\microphone`): mientras lo usa, su `LastUsedTimeStop`
   vale 0. Es la misma información que muestra el icono del micrófono en la barra de tareas.
2. **Quién lo está usando.** Si el ejecutable es una app de reuniones (Teams, Zoom, Meet…) o
   un navegador con una pestaña de videollamada, es una reunión; si es otra cosa (o NeonWhisper
   dictando), no.

Para no arrancar y parar con cada microcorte, hay que ver la señal varias veces seguidas:
dos lecturas para empezar y cinco para terminar (~15 s de silencio).
"""
import ctypes
import logging
import re
import sys
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

POLL_MS = 3000
STARTS_AFTER = 2   # lecturas seguidas con reunión para empezar a grabar
ENDS_AFTER = 5     # lecturas seguidas sin reunión para darla por terminada

# Ejecutables que solo se abren para reunirse.
MEETING_APPS = {
    "ms-teams.exe": "Microsoft Teams",
    "teams.exe": "Microsoft Teams",
    "zoom.exe": "Zoom",
    "cpthost.exe": "Zoom",
    "webex.exe": "Webex",
    "webexmta.exe": "Webex",
    "slack.exe": "Slack",
    "discord.exe": "Discord",
    "gotomeeting.exe": "GoToMeeting",
    "bluejeans.exe": "BlueJeans",
    "skype.exe": "Skype",
    "whatsapp.exe": "WhatsApp",
}
# Navegadores: cuentan solo si además hay una ventana de videollamada abierta.
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "arc.exe"}
WINDOW_HINTS = (
    (re.compile(r"\bMeet\b|Google Meet", re.I), "Google Meet"),
    (re.compile(r"Zoom (Meeting|Reuni[óo]n)|Zoom Workplace", re.I), "Zoom"),
    (re.compile(r"Microsoft Teams|Teams \|", re.I), "Microsoft Teams"),
    (re.compile(r"Webex", re.I), "Webex"),
    (re.compile(r"Whereby|Jitsi|GoTo Meeting|BlueJeans|Around", re.I), "Videollamada"),
)


@dataclass(frozen=True)
class Meeting:
    app: str        # nombre bonito: "Zoom", "Google Meet"…
    process: str    # ejecutable que tiene el micrófono
    title: str      # título de la ventana, si lo hay


# --- Micrófono en uso ---------------------------------------------------------
_CONSENT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def apps_using_microphone() -> set[str]:
    """Ejecutables (en minúsculas, sin ruta) que están usando el micrófono ahora mismo."""
    if sys.platform != "win32":
        return set()
    import winreg

    using: set[str] = set()
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for branch in ("NonPackaged", ""):
            try:
                with winreg.OpenKey(root, _CONSENT + ("\\" + branch if branch else "")) as key:
                    count = winreg.QueryInfoKey(key)[0]
                    for i in range(count):
                        name = winreg.EnumKey(key, i)
                        if name == "NonPackaged":
                            continue
                        try:
                            with winreg.OpenKey(key, name) as sub:
                                stop = winreg.QueryValueEx(sub, "LastUsedTimeStop")[0]
                        except OSError:
                            continue
                        if stop == 0:  # 0 = lo sigue usando
                            using.add(name.replace("#", "\\").split("\\")[-1].lower())
            except OSError:
                continue
    return using


# --- Ventanas abiertas --------------------------------------------------------
def window_titles() -> list[str]:
    """Títulos de las ventanas visibles (para reconocer videollamadas en el navegador)."""
    if sys.platform != "win32":
        return []
    user32 = ctypes.windll.user32
    titles: list[str] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def collect(hwnd, _param):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                titles.append(buf.value)
        return True

    try:
        user32.EnumWindows(collect, None)
    except Exception:  # noqa: BLE001
        log.exception("No se pudieron leer las ventanas")
    return titles


def detect(extra_apps: set[str], ignore: set[str]) -> Meeting | None:
    """Mira el micrófono y las ventanas y dice si estás en una reunión."""
    using = apps_using_microphone() - ignore
    if not using:
        return None
    known = {**MEETING_APPS, **{a: a.removesuffix(".exe").title() for a in extra_apps}}
    for process in using:
        if process in known:
            title = next((t for t in window_titles() if known[process].split()[0].lower() in t.lower()), "")
            return Meeting(known[process], process, title)
    for process in using:
        if process in BROWSERS:
            for title in window_titles():
                for pattern, app in WINDOW_HINTS:
                    if pattern.search(title):
                        return Meeting(app, process, title)
    return None


class MeetingDetector(QObject):
    """Vigila en segundo plano y avisa cuando empieza y cuando termina una reunión."""

    started = Signal(object)  # Meeting
    ended = Signal()

    def __init__(self, settings, ignore: set[str] | None = None):
        super().__init__()
        self.settings = settings
        self.ignore = ignore or set()
        self.current: Meeting | None = None
        self._hits = 0
        self._misses = 0
        self._timer = QTimer(self, interval=POLL_MS, timeout=self.poll)

    def set_enabled(self, enabled: bool) -> None:
        if enabled and not self._timer.isActive():
            self._hits = self._misses = 0
            self._timer.start()
        elif not enabled and self._timer.isActive():
            self._timer.stop()

    def extra_apps(self) -> set[str]:
        raw = (self.settings.meeting_apps or "").replace(";", ",")
        return {a.strip().lower() for a in raw.split(",") if a.strip().endswith(".exe")}

    def poll(self) -> None:
        try:
            found = detect(self.extra_apps(), self.ignore)
        except Exception:  # noqa: BLE001 - nunca tumbar la app por el detector
            log.exception("Error detectando reuniones")
            return
        if found:
            self._misses = 0
            self._hits += 1
            if self.current is None and self._hits >= STARTS_AFTER:
                self.current = found
                log.info("Reunión detectada: %s (%s)", found.app, found.process)
                self.started.emit(found)
        else:
            self._hits = 0
            self._misses += 1
            if self.current is not None and self._misses >= ENDS_AFTER:
                log.info("Reunión terminada: %s", self.current.app)
                self.current = None
                self.ended.emit()

    def forget(self) -> None:
        """Olvida la reunión en curso (p. ej. si la paras a mano y no quieres que vuelva a empezar)."""
        self.current = None
        self._hits = 0
        self._misses = 0
