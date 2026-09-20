"""Buscar e instalar versiones nuevas desde el repositorio público, sin reinstalar a mano.

La comprobación solo baja un archivo de unos cientos de bytes (`neonwhisper/__init__.py` de
GitHub), así que se puede hacer al arrancar sin que se note. La instalación se la pasa a
`scripts/update.ps1`, que ya sabe bajar el .zip, comparar versiones y llamar al instalador.

El proceso de actualización cierra la app (el instalador necesita reemplazar sus archivos) y la
vuelve a abrir al terminar. Por eso `install()` se despide y deja corriendo un proceso aparte.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from neonwhisper import __version__
from neonwhisper.paths import APP_DIR

log = logging.getLogger(__name__)

REPO = "Luisartt/NeonWhisper"
BRANCH = "main"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/neonwhisper/__init__.py"
RELEASES_URL = f"https://github.com/{REPO}/releases"
TIMEOUT = 8  # segundos: si GitHub no contesta rápido, no vale la pena esperar

_VERSION_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')


def parse_version(text: str) -> tuple[int, ...]:
    """«1.7.0» -> (1, 7, 0). Lo que no sea número se ignora, para no reventar con «1.7.0-beta»."""
    parts = []
    for chunk in text.strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    """¿La versión del repositorio es posterior a la instalada?"""
    a, b = parse_version(remote), parse_version(local)
    size = max(len(a), len(b))
    return a + (0,) * (size - len(a)) > b + (0,) * (size - len(b))


def fetch_latest_version() -> str:
    """Versión publicada en el repositorio. Lanza si no se pudo consultar."""
    request = urllib.request.Request(
        VERSION_URL,
        # GitHub responde 403 a peticiones sin identificar; además evita que nos sirva caché vieja.
        headers={"User-Agent": f"NeonWhisper/{__version__}", "Cache-Control": "no-cache"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read(4096).decode("utf-8", "replace")
    match = _VERSION_RE.search(body)
    if not match:
        raise ValueError("La respuesta de GitHub no traía número de versión")
    return match.group(1)


def is_git_clone() -> bool:
    """Una carpeta de desarrollo no se actualiza así: se actualiza con git."""
    return (APP_DIR / ".git").exists()


def update_script() -> Path:
    return APP_DIR / "scripts" / "update.ps1"


def can_update() -> tuple[bool, str]:
    """(se puede actualizar desde la app, por qué no si no se puede)."""
    if sys.platform != "win32":
        return False, "La actualización automática solo está hecha para Windows."
    if is_git_clone():
        return False, ("Esta copia es un clon de git: actualízala con «git pull» para no perder "
                       "tu historial de git.")
    if not update_script().is_file():
        return False, "No encuentro scripts/update.ps1 junto al programa."
    return True, ""


class _CheckWorker(QThread):
    """Consulta GitHub fuera del hilo de la interfaz: si la red tarda, la app no se congela."""

    done = Signal(str)     # versión publicada
    failed = Signal(str)   # motivo en cristiano

    def run(self) -> None:
        try:
            self.done.emit(fetch_latest_version())
        except urllib.error.HTTPError as exc:
            self.failed.emit(f"GitHub respondió {exc.code}")
        except urllib.error.URLError as exc:
            self.failed.emit(f"No hay conexión con GitHub ({exc.reason})")
        except Exception as exc:  # noqa: BLE001 - cualquier fallo se cuenta igual al usuario
            self.failed.emit(str(exc))


class Updater(QObject):
    """Busca versiones nuevas y lanza la actualización."""

    #: (versión publicada, hay una más nueva que la instalada)
    checked = Signal(str, bool)
    check_failed = Signal(str)
    #: la actualización arrancó: la app está a punto de cerrarse
    launching = Signal()
    launch_failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker: _CheckWorker | None = None
        self.latest = ""

    @property
    def busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def check(self) -> None:
        """Pregunta a GitHub qué versión hay publicada. No bloquea."""
        if self.busy:
            return
        worker = _CheckWorker(self)
        worker.done.connect(self._on_version)
        worker.failed.connect(self._on_failed)
        # Sin esto el QThread se queda colgando tras terminar y el siguiente `check` no arranca.
        worker.finished.connect(self._clear_worker)
        self._worker = worker
        worker.start()

    def _clear_worker(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()

    def _on_version(self, version: str) -> None:
        self.latest = version
        nueva = is_newer(version)
        log.info("Versión publicada: v%s (instalada v%s)%s",
                 version, __version__, " - hay actualización" if nueva else "")
        self.checked.emit(version, nueva)

    def _on_failed(self, reason: str) -> None:
        log.info("No se pudo consultar si hay versión nueva: %s", reason)
        self.check_failed.emit(reason)

    def install(self) -> bool:
        """Lanza el actualizador en una ventana aparte y avisa de que la app va a cerrarse.

        Devuelve False (y emite `launch_failed`) si esta copia no se puede actualizar así.
        """
        ok, motivo = can_update()
        if not ok:
            self.launch_failed.emit(motivo)
            return False
        comando = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(update_script()), "-Root", str(APP_DIR), "-Branch", BRANCH,
        ]
        try:
            # En su propia consola y su propio grupo: el instalador tiene que sobrevivir al cierre
            # de la app, porque lo primero que hace es cerrarla para reemplazar sus archivos.
            subprocess.Popen(
                comando,
                cwd=str(APP_DIR),
                creationflags=(getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                               | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
                close_fds=True,
            )
        except OSError as exc:
            log.exception("No se pudo lanzar el actualizador")
            self.launch_failed.emit(str(exc))
            return False
        log.info("Actualizador lanzado desde %s", APP_DIR)
        self.launching.emit()
        return True
