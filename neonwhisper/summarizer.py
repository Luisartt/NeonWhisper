"""Resumen de reuniones con un modelo de texto local (CTranslate2, el mismo motor que Whisper).

No hace falta nada nuevo instalado: los modelos son conversiones de Llama 3.2 Instruct al
formato de CTranslate2, se descargan con el mismo gestor que los de Whisper y corren en la
GPU si hay. El modelo se carga al resumir y se suelta al terminar, para no ocupar VRAM
mientras dictas.

Las transcripciones largas se resumen en dos pasos: primero por tramos y luego se juntan
esos resúmenes en uno solo (lo de siempre cuando el texto no cabe en el contexto).
"""
import logging
import re
import time

from PySide6.QtCore import QObject, Signal, Slot

from neonwhisper.paths import model_dir, model_downloaded

log = logging.getLogger(__name__)

CHUNK_TOKENS = 2400      # transcripción por tramo en el primer paso
MAX_NEW_TOKENS = 700
SYSTEM = "Eres un asistente que resume reuniones en español. Sé concreto y no inventes nada que no esté en el texto."

PART_TASK = (
    "Resume en viñetas cortas SOLO lo que aparece arriba: de qué se habló, qué se decidió y qué tareas "
    "salieron. Nada de introducciones ni comentarios tuyos."
)

FINAL_PROMPT = """--- {source} ---
{text}
--- FIN ---

{task}"""

# El resumen se escribe sección por sección: un modelo pequeño sigue mucho mejor una instrucción
# concreta a la vez que cuatro juntas. (título, instrucción, cómo empieza la respuesta)
SECTIONS = (
    ("## Resumen",
     "Escribe de tres a cinco frases seguidas con lo esencial de esta reunión. Solo el texto, "
     "sin viñetas, sin títulos y sin frases de introducción.", "", 260),
    ("## Temas tratados",
     "Enumera los temas que se trataron: máximo seis viñetas, una línea cada una, sin numerar y sin "
     "copiar frases literales. Solo las viñetas.", "- ", 200),
    ("## Decisiones",
     "Enumera lo que se decidió: máximo seis viñetas, una línea cada una, sin numerar. Solo las viñetas. "
     "Si no se decidió nada, responde exactamente: No se registraron decisiones.", "- ", 200),
    ("## Tareas",
     "Enumera las tareas que salieron: máximo seis viñetas, una línea cada una, sin numerar, con quién "
     "la hace y para cuándo si se dice. No copies el diálogo. Solo las viñetas. Si no salió ninguna, "
     "responde exactamente: No se registraron tareas.", "- ", 200),
)

def clean_section(text: str) -> str:
    """Limpia lo que suelen colar los modelos pequeños: preámbulos, numeración y viñetas kilométricas."""
    text = re.sub(r"^\s*(aqu[ií] (tienes|est[áa])|el resumen|resumen)[^\n:]*:\s*", "", text, flags=re.I)
    lines, seen = [], set()
    for line in text.strip().splitlines():
        # "- 3. tema" -> "- tema" (el espacio tras el punto evita romper "1.3" o "8.000")
        line = re.sub(r"^\s*[-*•]?\s*\d{1,2}[.)]\s+", "- ", line.rstrip())
        line = re.sub(r"^\s*[-*•]\s+", "- ", line)  # viñetas con espaciado desigual
        if line.startswith("-") and len(line) > 220:  # una viñeta que se convirtió en párrafo
            line = line[:217].rsplit(" ", 1)[0] + "…"
        key = line.strip().lower()
        if not key or key in seen:  # el modelo repitiendo la misma viñeta
            continue
        seen.add(key)
        lines.append(line)
    return "\n".join(lines).strip() or "—"


def chat_prompt(user: str, prefill: str = "") -> str:
    """Formato de conversación de Llama 3.x. `prefill` arranca la respuesta por nosotros."""
    return (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        f"{SYSTEM}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        f"{user}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        f"{prefill}"
    )


def split_text(text: str, tokens_per_chunk: int = CHUNK_TOKENS, chars_per_token: int = 4) -> list[str]:
    """Parte la transcripción en tramos por frases, sin cortar a mitad de una."""
    limit = tokens_per_chunk * chars_per_token
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    chunks, current = [], ""
    for sentence in sentences:
        while len(sentence) > limit:  # una "frase" enorme (audio sin puntuación)
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.append(sentence[:limit])
            sentence = sentence[limit:]
        if len(current) + len(sentence) + 1 > limit and current:
            chunks.append(current.strip())
            current = ""
        current += sentence + " "
    if current.strip():
        chunks.append(current.strip())
    return chunks


class Summarizer(QObject):
    """Vive en el mismo hilo que Whisper, así nunca pelean por la GPU."""

    progress = Signal(int, int, int)   # id de la reunión, parte, total
    finished = Signal(int, str)        # id de la reunión, resumen
    failed = Signal(int, str)          # id de la reunión, motivo

    def __init__(self):
        super().__init__()
        self._generator = None
        self._tokenizer = None
        self._loaded = ""

    # --- modelo -------------------------------------------------------------
    def _load(self, model: str, device: str):
        if self._loaded == model and self._generator is not None:
            return
        import ctranslate2
        from tokenizers import Tokenizer

        path = model_dir(model)
        self.unload()
        has_cuda = ctranslate2.get_cuda_device_count() > 0
        use_cuda = has_cuda and device in ("auto", "cuda")
        try:
            generator = ctranslate2.Generator(str(path), device="cuda" if use_cuda else "cpu", compute_type="auto")
        except Exception:  # noqa: BLE001 - normalmente, VRAM insuficiente
            if not use_cuda:
                raise
            log.exception("No se pudo cargar %s en la GPU, se usa el CPU", model)
            generator = ctranslate2.Generator(str(path), device="cpu", compute_type="auto")
        self._generator = generator
        self._tokenizer = Tokenizer.from_file(str(path / "tokenizer.json"))
        self._loaded = model
        log.info("Modelo de resumen %s listo (%s)", model, generator.device)

    def unload(self) -> None:
        self._generator = None
        self._tokenizer = None
        self._loaded = ""

    def _generate(self, user_prompt: str, max_tokens: int = MAX_NEW_TOKENS, prefill: str = "") -> str:
        """Genera la respuesta. `prefill` va escrito ya en boca del modelo, para que respete el formato."""
        tokens = self._tokenizer.encode(chat_prompt(user_prompt, prefill), add_special_tokens=False).tokens
        results = self._generator.generate_batch(
            [tokens],
            max_length=max_tokens,
            sampling_temperature=0.2,
            sampling_topk=20,
            repetition_penalty=1.15,   # los modelos pequeños se enganchan repitiendo la misma viñeta
            no_repeat_ngram_size=5,
            include_prompt_in_result=False,
            end_token=["<|eot_id|>", "<|end_of_text|>"],
        )
        return (prefill + self._tokenizer.decode(results[0].sequences_ids[0])).strip()

    # --- resumen -------------------------------------------------------------
    @Slot(int, str, str, str)
    def summarize(self, meeting_id: int, transcript: str, model: str, device: str) -> None:
        text = transcript.strip()
        if not text:
            self.failed.emit(meeting_id, "la transcripción está vacía")
            return
        if not model_downloaded(model):
            self.failed.emit(meeting_id, f"el modelo {model} no está descargado")
            return
        start = time.perf_counter()
        try:
            self._load(model, device)
            chunks = split_text(text)
            if len(chunks) == 1:
                source, content, steps = "TRANSCRIPCIÓN", chunks[0], len(SECTIONS)
            else:  # demasiado larga para el contexto: primero por tramos y luego el total
                parts = []
                steps = len(chunks) + len(SECTIONS)
                for i, chunk in enumerate(chunks, 1):
                    self.progress.emit(meeting_id, i, steps)
                    parts.append(self._generate(
                        FINAL_PROMPT.format(source=f"TRANSCRIPCIÓN (parte {i} de {len(chunks)})", text=chunk,
                                            task=PART_TASK),
                        max_tokens=400, prefill="- ",
                    ))
                source = "RESÚMENES POR PARTES"
                content = "\n\n".join(f"Parte {i}:\n{p}" for i, p in enumerate(parts, 1))
            done = steps - len(SECTIONS)
            written = []
            for title, task, prefill, budget in SECTIONS:
                done += 1
                self.progress.emit(meeting_id, done, steps)
                body = self._generate(
                    FINAL_PROMPT.format(source=source, text=content, task=task), max_tokens=budget, prefill=prefill
                )
                written.append(f"{title}\n{clean_section(body)}")
            summary = "\n\n".join(written)
            log.info("Reunión %s resumida en %.1fs", meeting_id, time.perf_counter() - start)
            self.finished.emit(meeting_id, summary.strip())
        except Exception as exc:  # noqa: BLE001
            log.exception("Error resumiendo la reunión %s", meeting_id)
            self.failed.emit(meeting_id, str(exc))
        finally:
            self.unload()  # libera la VRAM: dictar es lo que manda
