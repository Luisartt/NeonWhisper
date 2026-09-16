"""Lanzador sin consola: doble clic (o el acceso directo) abre NeonWhisper."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from neonwhisper.app import main  # noqa: E402

main()
