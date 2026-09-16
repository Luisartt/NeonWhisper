"""Sonidos sintetizados (sin archivos externos) reproducidos con winsound."""
import wave
import winsound

import numpy as np

from neonwhisper.paths import SOUNDS_DIR

RATE = 44100


def _tone(freqs: list[float], note_len: float, volume: float, decay: float = 9.0) -> np.ndarray:
    parts = []
    for f in freqs:
        t = np.linspace(0, note_len, int(RATE * note_len), endpoint=False)
        env = np.exp(-decay * t) * np.minimum(1.0, t / 0.004)
        wave_ = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(4 * np.pi * f * t) + 0.08 * np.sin(6 * np.pi * f * t)
        parts.append(wave_ * env)
    sig = np.concatenate(parts)
    sig = sig / (np.max(np.abs(sig)) or 1.0)
    return (sig * volume * 0.8 * 32767).astype(np.int16)


def _write(name: str, samples: np.ndarray) -> None:
    with wave.open(str(SOUNDS_DIR / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())


def generate(volume: float) -> None:
    v = max(0.0, min(1.0, volume))
    _write("start", _tone([880.0, 1318.5], 0.075, v, decay=14))
    _write("stop", _tone([1318.5, 880.0], 0.075, v, decay=14))
    _write("done", _tone([1760.0], 0.09, v * 0.6, decay=30))
    _write("error", _tone([330.0, 262.0], 0.11, v, decay=10))


def play(name: str) -> None:
    path = SOUNDS_DIR / f"{name}.wav"
    if path.exists():
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
