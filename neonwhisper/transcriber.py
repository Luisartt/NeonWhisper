"""Whisper local (faster-whisper / CTranslate2). Vive en su propio QThread."""
import logging
import os
import re
import subprocess
import time

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from neonwhisper.paths import model_dir, model_downloaded, setup_cuda_dlls

setup_cuda_dlls()

log = logging.getLogger(__name__)

# Frases que Whisper "alucina" con silencio o ruido.
_HALLUCINATIONS = re.compile(
    r"amara\.org|subt[ií]tulos (realizados )?por|thanks? for watching|suscr[ií]bete",
    re.IGNORECASE,
)


def gpu_name() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return out.stdout.strip().splitlines()[0].replace("NVIDIA GeForce ", "")
    except Exception:  # noqa: BLE001
        return "NVIDIA"


class Transcriber(QObject):
    status_changed = Signal(str, str)  # estado (downloading|loading|ready|error), detalle
    finished = Signal(str, float, str, float)  # texto, segundos de audio, idioma, segundos de proceso
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self._model = None

    @Slot(str, str)
    def load(self, model_name: str, device: str) -> None:
        import ctranslate2
        from faster_whisper import WhisperModel
        from faster_whisper.utils import download_model

        self._model = None
        try:
            path = str(model_dir(model_name))
            if not model_downloaded(model_name):
                self.status_changed.emit("downloading", f"Descargando {model_name}…")
                download_model(model_name, output_dir=path)

            self.status_changed.emit("loading", f"Cargando {model_name}…")
            has_cuda = ctranslate2.get_cuda_device_count() > 0
            if device == "cuda" and not has_cuda:
                raise RuntimeError("No se encontró una GPU NVIDIA con CUDA")

            model, label = None, ""
            if device in ("auto", "cuda") and has_cuda:
                try:
                    model = WhisperModel(path, device="cuda", compute_type="float16")
                    self._warmup(model)
                    label = f"GPU · {gpu_name()}"
                except Exception:
                    if device == "cuda":
                        raise
                    log.exception("Falló CUDA, usando CPU")
                    model = None
            if model is None:
                model = WhisperModel(
                    path, device="cpu", compute_type="int8", cpu_threads=max(4, (os.cpu_count() or 8) - 2)
                )
                self._warmup(model)
                label = "CPU"

            self._model = model
            log.info("Modelo %s listo en %s", model_name, label)
            self.status_changed.emit("ready", f"{model_name} · {label}")
        except Exception as exc:  # noqa: BLE001
            log.exception("No se pudo cargar el modelo")
            self.status_changed.emit("error", str(exc))

    @staticmethod
    def _warmup(model) -> None:
        noise = (np.random.default_rng(0).standard_normal(32000) * 0.01).astype(np.float32)
        segments, _ = model.transcribe(noise, language="es", beam_size=5, vad_filter=False)
        list(segments)

    @Slot(object, str, str)
    def transcribe(self, audio: np.ndarray, language: str, prompt: str) -> None:
        if self._model is None:
            self.failed.emit("El modelo todavía no está listo")
            return
        start = time.perf_counter()
        try:
            segments, info = self._model.transcribe(
                audio,
                language=None if language == "auto" else language,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                initial_prompt=prompt.strip() or None,
                condition_on_previous_text=False,
                without_timestamps=True,
            )
            parts = [s.text.strip() for s in segments]
            text = " ".join(p for p in parts if p and not _HALLUCINATIONS.search(p)).strip()
            self.finished.emit(text, len(audio) / 16000, info.language, time.perf_counter() - start)
        except Exception as exc:  # noqa: BLE001
            log.exception("Error transcribiendo")
            self.failed.emit(str(exc))
