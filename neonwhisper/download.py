"""Descarga el modelo de Whisper por adelantado: python -m neonwhisper.download [modelo]."""
import sys

from faster_whisper.utils import download_model

from neonwhisper.config import Settings
from neonwhisper.paths import model_dir, model_downloaded


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else Settings.load().model
    if model_downloaded(model):
        print(f"El modelo '{model}' ya está descargado en {model_dir(model)}", flush=True)
        return
    print(f"Descargando Whisper '{model}' en {model_dir(model)} (puede tardar unos minutos)...", flush=True)
    download_model(model, output_dir=str(model_dir(model)))
    print("Listo.", flush=True)


if __name__ == "__main__":
    main()
