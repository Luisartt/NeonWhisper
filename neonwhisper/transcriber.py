"""Whisper local (faster-whisper / CTranslate2). Vive en su propio QThread."""
import logging
import os
import re
import subprocess
import threading
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
    # estado: downloading | loading | ready | error. "ready" significa que hay un modelo usable.
    status_changed = Signal(str, str)
    finished = Signal(str, float, str, float)  # texto, segundos de audio, idioma, segundos de proceso
    failed = Signal(str)
    _download_done = Signal(str, str)  # modelo, error ("" si salió bien)

    def __init__(self):
        super().__init__()
        self._model = None
        self._loaded: tuple[str, str] = ("", "")
        self._label = ""
        self._wanted: tuple[str, str] = ("", "")
        self._downloading: set[str] = set()
        self._download_done.connect(self._on_download_done)

    @property
    def has_model(self) -> bool:
        return self._model is not None

    # --- carga ------------------------------------------------------------------
    @Slot(str, str)
    def load(self, model_name: str, device: str) -> None:
        """Carga el modelo pedido. Si hay que descargarlo, lo hace en segundo plano
        y el modelo actual sigue funcionando mientras tanto."""
        self._wanted = (model_name, device)
        if model_downloaded(model_name):
            self._load_now(model_name, device)
            return
        self.status_changed.emit("downloading", f"Descargando {model_name}…")
        if model_name not in self._downloading:
            self._downloading.add(model_name)
            threading.Thread(target=self._download, args=(model_name,), daemon=True).start()

    def _download(self, model_name: str) -> None:  # hilo de descarga
        from faster_whisper.utils import download_model

        error = ""
        try:
            download_model(model_name, output_dir=str(model_dir(model_name)))
        except Exception as exc:  # noqa: BLE001
            log.exception("No se pudo descargar %s", model_name)
            error = str(exc) or exc.__class__.__name__
        self._downloading.discard(model_name)
        self._download_done.emit(model_name, error)

    @Slot(str, str)
    def _on_download_done(self, model_name: str, error: str) -> None:
        if self._wanted[0] != model_name:
            return  # el usuario ya eligió otro modelo
        if error:
            self._report_failure(model_name, f"no se pudo descargar: {error}")
        else:
            self._load_now(*self._wanted)

    def _load_now(self, model_name: str, device: str) -> None:
        if self._model is not None and self._loaded == (model_name, device):
            self.status_changed.emit("ready", f"{model_name} · {self._label}")
            return
        self.status_changed.emit("loading", f"{model_name} · instalado ✓")
        try:
            model, label = self._create(str(model_dir(model_name)), device)
        except Exception as exc:  # noqa: BLE001
            log.exception("No se pudo cargar %s", model_name)
            self._report_failure(model_name, str(exc))
            return
        self._model, self._loaded, self._label = model, (model_name, device), label
        log.info("Modelo %s listo en %s", model_name, label)
        self.status_changed.emit("ready", f"{model_name} · {label}")

    def _report_failure(self, model_name: str, reason: str) -> None:
        if self._model is not None:  # seguimos con el modelo que ya estaba cargado
            self.status_changed.emit("ready", f"{self._loaded[0]} · {self._label} ({model_name}: {reason[:80]})")
        else:
            self.status_changed.emit("error", reason)

    def _create(self, path: str, device: str):
        import ctranslate2
        from faster_whisper import WhisperModel

        has_cuda = ctranslate2.get_cuda_device_count() > 0
        if device == "cuda" and not has_cuda:
            raise RuntimeError("No se encontró una GPU NVIDIA con CUDA")
        if device in ("auto", "cuda") and has_cuda:
            try:
                model = WhisperModel(path, device="cuda", compute_type="float16")
                self._warmup(model)
                return model, f"GPU · {gpu_name()}"
            except Exception:
                if device == "cuda":
                    raise
                log.exception("Falló CUDA, usando CPU")
        model = WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=max(4, (os.cpu_count() or 8) - 2))
        self._warmup(model)
        return model, "CPU"

    @staticmethod
    def _warmup(model) -> None:
        noise = (np.random.default_rng(0).standard_normal(32000) * 0.01).astype(np.float32)
        segments, _ = model.transcribe(noise, language="es", beam_size=5, vad_filter=False)
        list(segments)

    # --- transcripción ----------------------------------------------------------
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
