"""Ajustes persistentes en %APPDATA%\\NeonWhisper\\settings.json."""
import json
from dataclasses import asdict, dataclass, fields

from neonwhisper.paths import SETTINGS_FILE

MODELS = {
    "large-v3-turbo": "Large v3 Turbo · el mejor balance (recomendado)",
    "large-v3": "Large v3 · máxima precisión, más lento",
    "medium": "Medium · ligero",
    "small": "Small · muy ligero, para CPU",
}

MODEL_SIZES = {"large-v3-turbo": "~1.6 GB", "large-v3": "~3 GB", "medium": "~1.5 GB", "small": "~500 MB"}

LANGUAGES = {
    "es": "Español",
    "en": "English",
    "auto": "Detectar automáticamente",
}


@dataclass
class Settings:
    hotkey: str = "ctrl+alt+space"
    mode: str = "toggle"  # "toggle" = presiona para iniciar/detener · "hold" = mantén presionado
    model: str = "large-v3-turbo"  # modelo en uso (siempre uno instalado)
    pending_model: str = ""  # modelo que se usará automáticamente cuando termine de descargarse
    device: str = "auto"  # auto | cuda | cpu
    language: str = "es"
    input_device: int | None = None  # (antiguo) índice; los índices cambian al reiniciar
    input_device_name: str = ""  # "" = micrófono predeterminado de Windows
    auto_paste: bool = True
    restore_clipboard: bool = True
    sounds: bool = True
    sound_volume: float = 0.5
    initial_prompt: str = ""
    start_minimized: bool = False
    launch_at_startup: bool = False
    show_overlay: bool = True

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
