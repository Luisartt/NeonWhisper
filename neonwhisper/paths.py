"""Rutas de datos del usuario y configuración de DLLs de CUDA.

La app puede estar instalada en Archivos de programa, donde no se puede escribir. Por eso nada
se guarda junto al programa: los ajustes y el historial viven en %APPDATA%\\NeonWhisper y los
modelos en %LOCALAPPDATA%\\NeonWhisper\\models.

Excepción: si junto a la app ya existe una carpeta `models` (instalaciones portables y las
anteriores a la v1.3), se sigue usando esa, para no volver a descargar varios GB.
"""
import os
import sys
from pathlib import Path

from neonwhisper import APP_NAME

APP_DIR = Path(__file__).resolve().parent.parent  # carpeta donde está instalado el programa
ROOT = APP_DIR  # nombre anterior, se conserva por compatibilidad
ASSETS = APP_DIR / "assets"
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
LOCAL_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
SOUNDS_DIR = DATA_DIR / "sounds"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_DB = DATA_DIR / "history.db"
LOG_FILE = DATA_DIR / "neonwhisper.log"

MEETINGS_DIR = LOCAL_DIR / "meetings"  # audio de las reuniones mientras se graban

PORTABLE = (APP_DIR / "models").is_dir()
MODELS_DIR = (APP_DIR / "models") if PORTABLE else (LOCAL_DIR / "models")

for _d in (DATA_DIR, SOUNDS_DIR, MODELS_DIR, MEETINGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def model_dir(name: str) -> Path:
    return MODELS_DIR / name


def model_downloaded(name: str) -> bool:
    return (model_dir(name) / "model.bin").is_file()


def setup_cuda_dlls() -> None:
    """Hace visibles las DLL de cuBLAS/cuDNN instaladas vía pip (paquetes nvidia-*)."""
    if sys.platform != "win32":
        return
    try:
        import nvidia  # namespace package
    except ImportError:
        return
    for base in list(getattr(nvidia, "__path__", [])):
        for sub in ("cublas", "cudnn", "cuda_nvrtc", "cuda_runtime"):
            bin_dir = Path(base) / sub / "bin"
            if bin_dir.is_dir():
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
                try:
                    os.add_dll_directory(str(bin_dir))
                except OSError:
                    pass
