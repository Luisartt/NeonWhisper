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

MODEL_SIZES = {
    "large-v3-turbo": "~1.6 GB", "large-v3": "~3 GB", "medium": "~1.5 GB", "small": "~500 MB",
    "llama-3.2-3b": "~3.2 GB", "llama-3.2-1b": "~1.3 GB",
}

# Modelos de texto para resumir reuniones (CTranslate2, el mismo motor que Whisper).
SUMMARY_MODELS = {
    "llama-3.2-3b": "Llama 3.2 3B · resúmenes más finos (recomendado)",
    "llama-3.2-1b": "Llama 3.2 1B · más rápido y ligero",
}

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
    ui_theme: str = "neon"  # tema de la interfaz: neon | glass | mono (ver ui/theme.py)
    theme_syncs_overlay: bool = True  # al cambiar de tema, la barra flotante usa el diseño del mismo nombre
    show_overlay: bool = True
    overlay_style: str = "neon"  # neon | glass | mono (ver ui/overlay_styles.py)
    overlay_scale: float = 1.0
    overlay_bg_opacity: float = 0.96  # fondo de la barra (0 = solo ondas y borde)
    overlay_opacity: float = 1.0  # toda la barra
    # --- Reuniones ---
    meetings_enabled: bool = False  # grabar reuniones automáticamente (se activa en Ajustes)
    meeting_auto_start: bool = True  # al detectar la reunión, grabar sin preguntar
    meeting_record_mic: bool = True  # grabar tu voz (puedes silenciarla en caliente)
    meeting_capture_system: bool = True  # además del micrófono, lo que suena en tu PC
    meeting_speaker: str = ""  # salida que se captura ("" = la predeterminada de Windows)
    meeting_popup: bool = True  # aviso flotante arriba a la izquierda al detectar una reunión
    meeting_keep_audio: bool = False  # conservar el .wav después de transcribir
    meeting_min_seconds: int = 60  # reuniones más cortas que esto se descartan
    meeting_summary_model: str = "llama-3.2-3b"  # ver SUMMARY_MODELS ("" = solo transcripción)
    meeting_apps: str = ""  # apps extra que cuentan como reunión, separadas por comas

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
