"""Descarga de modelos de Whisper con progreso, pausa/continuar y conexiones en paralelo.

Hugging Face limita la velocidad por conexión, así que los archivos grandes se bajan
en varios segmentos a la vez. Cada segmento se guarda en `.parts/` y se reanuda con
peticiones Range, incluso después de cerrar la app. Al terminar se ensamblan y se
verifica el SHA-256.
"""
import hashlib
import json
import logging
import math
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from fnmatch import fnmatch

import httpx

from neonwhisper.paths import model_dir, model_downloaded

log = logging.getLogger(__name__)

REPOS = {  # los mismos repositorios que usa faster-whisper
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3": "Systran/faster-whisper-large-v3",
    "medium": "Systran/faster-whisper-medium",
    "small": "Systran/faster-whisper-small",
    # Modelos de texto para resumir reuniones (Llama 3.2 convertido a CTranslate2).
    "llama-3.2-3b": "jncraton/Llama-3.2-3B-Instruct-ct2-int8",
    "llama-3.2-1b": "jncraton/Llama-3.2-1B-Instruct-ct2-int8",
}
ALLOW_PATTERNS = ("config.json", "preprocessor_config.json", "generation_config.json",
                  "tokenizer.json", "vocabulary.*", "model.bin")
MANIFEST = ".download.json"
PARTS = ".parts"
SEGMENTS = 8
SEGMENT_MIN_SIZE = 64 * 1024 * 1024
CHUNK = 256 * 1024
ACTIVE_STATES = ("connecting", "downloading", "verifying")


@dataclass
class DownloadInfo:
    state: str = "missing"  # missing | installed | connecting | downloading | paused | verifying | error
    done: int = 0
    total: int = 0
    speed: float = 0.0  # bytes por segundo
    error: str = ""

    @property
    def fraction(self) -> float:
        return min(1.0, self.done / self.total) if self.total else 0.0

    @property
    def eta(self) -> float | None:
        return (self.total - self.done) / self.speed if self.speed > 1 and self.total else None


class _Job:
    def __init__(self, model: str):
        self.model = model
        self.pause = threading.Event()
        self.cancel = False
        self.finished = False
        self.thread: threading.Thread | None = None
        self.done = 0

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive() and not self.finished


# --- manifiesto en disco ----------------------------------------------------------
def _read_manifest(model: str) -> dict | None:
    try:
        return json.loads((model_dir(model) / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_manifest(model: str, manifest: dict) -> None:
    (model_dir(model) / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")


def _segments(size: int, count: int) -> list[tuple[int, int]]:
    step = math.ceil(size / count)
    return [(start, min(size, start + step) - 1) for start in range(0, size, step)]


def _part_paths(model: str, entry: dict) -> list:
    return [model_dir(model) / PARTS / f"{entry['name']}.{i}" for i in range(entry["segments"])]


def _bytes_on_disk(model: str, manifest: dict) -> int:
    total = 0
    for entry in manifest["files"]:
        final = model_dir(model) / entry["name"]
        if final.is_file() and final.stat().st_size == entry["size"]:
            total += entry["size"]
            continue
        total += sum(p.stat().st_size for p in _part_paths(model, entry) if p.is_file())
    return total


def _stale_hf_download(model: str) -> bool:
    """Descarga a medias hecha por la versión anterior (caché de huggingface_hub)."""
    cache = model_dir(model) / ".cache" / "huggingface" / "download"
    return not model_downloaded(model) and cache.is_dir() and any(cache.glob("*.lock"))


def _friendly(exc: Exception) -> str:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return "Sin conexión a internet"
    if isinstance(exc, httpx.TimeoutException):
        return "La conexión tardó demasiado"
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 112:
        return "No hay espacio suficiente en el disco"
    return (str(exc) or exc.__class__.__name__)[:140]


class DownloadManager:
    def __init__(
        self,
        on_change: Callable[[str], None] = lambda model: None,
        on_installed: Callable[[str], None] = lambda model: None,
    ):
        self.on_change = on_change
        self.on_installed = on_installed
        self._lock = threading.RLock()
        self._jobs: dict[str, _Job] = {}
        self._info: dict[str, DownloadInfo] = {}

    # --- consultas --------------------------------------------------------------
    def info(self, model: str) -> DownloadInfo:
        with self._lock:
            job = self._jobs.get(model)
            cached = self._info.get(model)
            if cached is not None and (cached.state in ("error", "connecting") or (job is not None and job.running)):
                return replace(cached)
        manifest = _read_manifest(model)
        if manifest is None:
            return DownloadInfo("installed" if model_downloaded(model) else "missing")
        return DownloadInfo("paused", _bytes_on_disk(model, manifest), sum(f["size"] for f in manifest["files"]))

    def interrupted(self) -> list[str]:
        """Modelos que se estaban descargando cuando se cerró la app (no los pausados a propósito)."""
        result = []
        for model in REPOS:
            manifest = _read_manifest(model)
            if (manifest is not None and not manifest.get("paused")) or _stale_hf_download(model):
                result.append(model)
        return result

    # --- acciones ---------------------------------------------------------------
    def start(self, model: str) -> None:
        """Empieza o continúa la descarga."""
        with self._lock:
            job = self._jobs.get(model)
            if job is not None and job.running:
                job.pause.clear()
                job.cancel = False
                return
            job = _Job(model)
            self._jobs[model] = job
            job.thread = threading.Thread(target=self._run, args=(job,), daemon=True, name=f"download-{model}")
        current = self.info(model)
        self._set(model, DownloadInfo("connecting", current.done, current.total))
        job.thread.start()

    def pause(self, model: str) -> None:
        with self._lock:
            job = self._jobs.get(model)
            if job is not None and job.running:
                job.pause.set()

    def cancel(self, model: str) -> None:
        """Detiene la descarga y borra lo descargado."""
        with self._lock:
            job = self._jobs.get(model)
            if job is not None and job.running:
                job.cancel = True
                job.pause.set()
                return
            self._info.pop(model, None)
        self._discard_partial(model)
        self._set(model, DownloadInfo("missing"))

    def delete(self, model: str) -> None:
        with self._lock:
            job = self._jobs.get(model)
            if job is not None and job.running:
                return
            self._info.pop(model, None)
        shutil.rmtree(model_dir(model), ignore_errors=True)
        self._set(model, DownloadInfo("missing"))

    def wait(self, model: str) -> None:
        job = self._jobs.get(model)
        if job is not None and job.thread is not None:
            job.thread.join()

    # --- trabajo en segundo plano ----------------------------------------------
    def _set(self, model: str, info: DownloadInfo) -> None:
        with self._lock:
            self._info[model] = info
        try:
            self.on_change(model)
        except Exception:  # noqa: BLE001
            log.exception("Error notificando el progreso")

    def _run(self, job: _Job) -> None:
        model = job.model
        try:
            while True:
                outcome = self._attempt(job)
                with self._lock:
                    if outcome == "paused" and not job.pause.is_set() and not job.cancel:
                        continue  # pidieron continuar mientras se pausaba
                    job.finished = True
                    break
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                job.finished = True
            if not job.cancel:
                log.exception("Falló la descarga de %s", model)
                manifest = _read_manifest(model)
                done = _bytes_on_disk(model, manifest) if manifest else 0
                total = sum(f["size"] for f in manifest["files"]) if manifest else 0
                self._set(model, DownloadInfo("error", done, total, 0.0, _friendly(exc)))
                return
            outcome = "paused"

        if job.cancel:
            self._discard_partial(model)
            with self._lock:
                self._info.pop(model, None)
            self._set(model, DownloadInfo("missing"))
        elif outcome == "paused":
            manifest = _read_manifest(model)
            if manifest is not None:
                manifest["paused"] = True
                _write_manifest(model, manifest)
            with self._lock:
                self._info.pop(model, None)
            self._set(model, self.info(model))
        else:
            with self._lock:
                self._info.pop(model, None)
            log.info("Modelo %s descargado", model)
            self._set(model, DownloadInfo("installed"))
            self.on_installed(model)

    def _fetch_manifest(self, model: str) -> dict:
        from huggingface_hub import HfApi

        repo = REPOS[model]
        info = HfApi().model_info(repo, files_metadata=True)
        files = [
            {
                "name": s.rfilename,
                "size": int(s.size or 0),
                "sha256": s.lfs.sha256 if s.lfs else None,
                "segments": SEGMENTS if (s.size or 0) >= SEGMENT_MIN_SIZE else 1,
            }
            for s in info.siblings
            if any(fnmatch(s.rfilename, p) for p in ALLOW_PATTERNS) and s.size
        ]
        files.sort(key=lambda f: f["name"] == "model.bin")  # model.bin al final: indica que todo terminó
        return {"repo": repo, "revision": info.sha, "files": files, "paused": False}

    def _attempt(self, job: _Job) -> str:
        model = job.model
        folder = model_dir(model)
        folder.mkdir(parents=True, exist_ok=True)
        manifest = _read_manifest(model)
        if manifest is None:
            manifest = self._fetch_manifest(model)
            shutil.rmtree(folder / ".cache", ignore_errors=True)  # restos de la versión anterior
        manifest["paused"] = False
        _write_manifest(model, manifest)

        total = sum(f["size"] for f in manifest["files"])
        job.done = _bytes_on_disk(model, manifest)
        base_url = f"https://huggingface.co/{manifest['repo']}/resolve/{manifest['revision']}/"
        (folder / PARTS).mkdir(exist_ok=True)

        with httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, read=60.0),
            headers={"User-Agent": "NeonWhisper"},
            limits=httpx.Limits(max_connections=SEGMENTS + 2),
        ) as client:
            for entry in manifest["files"]:
                final = folder / entry["name"]
                if final.is_file() and final.stat().st_size == entry["size"]:
                    continue
                parts = _part_paths(model, entry)
                errors: list[Exception] = []
                threads = [
                    threading.Thread(
                        target=self._fetch_segment,
                        args=(job, client, base_url + entry["name"], rng, path, errors),
                        daemon=True,
                    )
                    for rng, path in zip(_segments(entry["size"], entry["segments"]), parts)
                ]
                for t in threads:
                    t.start()
                last_time, last_done, speed = time.monotonic(), job.done, 0.0
                while any(t.is_alive() for t in threads):
                    time.sleep(0.4)
                    now = time.monotonic()
                    instant = (job.done - last_done) / max(1e-3, now - last_time)
                    speed = instant if speed == 0 else speed * 0.8 + instant * 0.2
                    last_time, last_done = now, job.done
                    if not job.pause.is_set():
                        self._set(model, DownloadInfo("downloading", job.done, total, speed))
                if errors:
                    raise errors[0]
                if job.pause.is_set():
                    return "paused"

                if entry["size"] >= SEGMENT_MIN_SIZE:
                    self._set(model, DownloadInfo("verifying", job.done, total))
                tmp = final.with_name(final.name + ".tmp")
                digest = hashlib.sha256()
                with open(tmp, "wb") as out:
                    for path in parts:
                        with open(path, "rb") as src:
                            while chunk := src.read(8 * 1024 * 1024):
                                out.write(chunk)
                                digest.update(chunk)
                if tmp.stat().st_size != entry["size"] or (entry["sha256"] and digest.hexdigest() != entry["sha256"]):
                    tmp.unlink(missing_ok=True)
                    for path in parts:
                        path.unlink(missing_ok=True)
                    raise RuntimeError(f"{entry['name']} llegó dañado; vuelve a intentarlo")
                tmp.replace(final)
                for path in parts:
                    path.unlink(missing_ok=True)

        shutil.rmtree(folder / PARTS, ignore_errors=True)
        (folder / MANIFEST).unlink(missing_ok=True)
        return "done"

    def _fetch_segment(self, job: _Job, client: httpx.Client, url: str, rng: tuple[int, int], path, errors: list) -> None:
        start, end = rng
        length = end - start + 1
        failures = 0
        while not job.pause.is_set():
            have = path.stat().st_size if path.is_file() else 0
            if have > length:
                path.unlink()
                with self._lock:
                    job.done -= have
                continue
            if have == length:
                return
            try:
                with client.stream("GET", url, headers={"Range": f"bytes={start + have}-{end}"}) as response:
                    if response.status_code != 206:
                        raise RuntimeError(f"El servidor respondió {response.status_code}")
                    with open(path, "ab") as out:
                        for chunk in response.iter_bytes(CHUNK):
                            out.write(chunk)
                            with self._lock:
                                job.done += len(chunk)
                            if job.pause.is_set():
                                return
                failures = 0
            except (httpx.HTTPError, OSError, RuntimeError) as exc:
                failures += 1
                if failures > 6:
                    errors.append(exc)
                    job.pause.set()  # detiene los demás segmentos; el error se reporta
                    return
                time.sleep(min(2**failures, 30))

    def _discard_partial(self, model: str) -> None:
        folder = model_dir(model)
        shutil.rmtree(folder / PARTS, ignore_errors=True)
        (folder / MANIFEST).unlink(missing_ok=True)
        for tmp in folder.glob("*.tmp"):
            tmp.unlink(missing_ok=True)
        if not model_downloaded(model):
            shutil.rmtree(folder, ignore_errors=True)
