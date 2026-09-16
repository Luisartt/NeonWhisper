"""Pega el texto donde está el cursor (portapapeles + Ctrl+V) y restaura el portapapeles."""
import time

import keyboard
from PySide6.QtCore import QMimeData, QObject, QTimer
from PySide6.QtGui import QGuiApplication

from neonwhisper.hotkeys import modifiers_down


def _clone_mime(src: QMimeData | None) -> QMimeData | None:
    if src is None or not src.formats():
        return None
    dst = QMimeData()
    for fmt in src.formats():
        dst.setData(fmt, src.data(fmt))
    return dst


class Paster(QObject):
    def __init__(self):
        super().__init__()
        self._generation = 0

    def copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    def paste(self, text: str, restore_clipboard: bool) -> None:
        self._generation += 1
        gen = self._generation
        clipboard = QGuiApplication.clipboard()
        saved = _clone_mime(clipboard.mimeData()) if restore_clipboard else None
        clipboard.setText(text)
        deadline = time.monotonic() + 2.0

        def send() -> None:
            # Espera a que sueltes Ctrl/Alt/Shift/Win para no mandar Ctrl+Alt+V por accidente.
            if modifiers_down() and time.monotonic() < deadline:
                QTimer.singleShot(20, send)
                return
            keyboard.send("ctrl+v")
            if saved is not None:
                QTimer.singleShot(800, lambda: self._restore(gen, saved))

        QTimer.singleShot(30, send)

    def _restore(self, gen: int, saved: QMimeData) -> None:
        if gen == self._generation:
            QGuiApplication.clipboard().setMimeData(saved)
