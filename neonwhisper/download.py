"""Descarga el modelo de Whisper desde la terminal: python -m neonwhisper.download [modelo]."""
import sys
import threading
import time

from neonwhisper.config import Settings
from neonwhisper.downloader import DownloadManager
from neonwhisper.fmt import fmt_bytes, fmt_eta, fmt_speed
from neonwhisper.paths import model_dir, model_downloaded


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else Settings.load().model
    if model_downloaded(model):
        print(f"El modelo '{model}' ya está descargado en {model_dir(model)}", flush=True)
        return
    print(f"Descargando Whisper '{model}' en {model_dir(model)} ...", flush=True)
    done = threading.Event()
    last = [0.0]

    def on_change(name: str) -> None:
        info = manager.info(name)
        if info.state in ("installed", "error", "missing"):
            done.set()
            return
        if time.monotonic() - last[0] < 1 and info.state == "downloading":
            return
        last[0] = time.monotonic()
        line = f"  {info.fraction * 100:5.1f}%  {fmt_bytes(info.done)} / {fmt_bytes(info.total)}"
        if info.state == "downloading":
            line += f"  {fmt_speed(info.speed)}  {fmt_eta(info.eta)}"
        print(f"\r{line:<72}", end="", flush=True)

    manager = DownloadManager(on_change=on_change)
    manager.start(model)
    done.wait()
    print()
    info = manager.info(model)
    if info.state != "installed":
        print(f"No se pudo descargar: {info.error}", flush=True)
        sys.exit(1)
    print("Listo.", flush=True)


if __name__ == "__main__":
    main()
