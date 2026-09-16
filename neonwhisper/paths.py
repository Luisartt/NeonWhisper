"""Rutas de datos del usuario y configuración de DLLs de CUDA."""
import os
import sys
from pathlib import Path

from neonwhisper import APP_NAME

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
MODELS_DIR = ROOT / "models"  # junto a la app: portable y sin symlinks de Hugging Face
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
SOUNDS_DIR = DATA_DIR / "sounds"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_DB = DATA_DIR / "history.db"
LOG_FILE = DATA_DIR / "neonwhisper.log"

for _d in (DATA_DIR, MODELS_DIR, SOUNDS_DIR):
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
