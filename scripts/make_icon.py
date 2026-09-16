"""Genera assets/icon.ico y assets/icon.png a partir del logo dibujado en código."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402

from neonwhisper.ui.widgets import paint_logo  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    paint_logo(p, QRectF(0, 0, size, size))
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def main() -> None:
    QGuiApplication(sys.argv)
    ASSETS.mkdir(exist_ok=True)
    render(512).save(str(ASSETS / "icon.png"))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [png_bytes(render(s)) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, data in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    (ASSETS / "icon.ico").write_bytes(header + entries + b"".join(images))
    print("Íconos generados en", ASSETS)


if __name__ == "__main__":
    main()
