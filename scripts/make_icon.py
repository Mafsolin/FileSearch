"""Render assets/brand/filesearch.svg into a multi-size Windows .ico.

Run after changing the mark:

    .venv\\Scripts\\python.exe scripts\\make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "brand" / "filesearch.svg"
TARGET = ROOT / "assets" / "brand" / "filesearch.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)

# The mark occupies the full 24u viewBox. Windows renders icons edge to edge,
# so inset it slightly to keep the silhouette from touching the bitmap border.
PADDING_RATIO = 0.08


def render(renderer: QSvgRenderer, size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    inset = size * PADDING_RATIO
    renderer.render(painter, QRectF(inset, inset, size - inset * 2, size - inset * 2))
    painter.end()
    return image


def main() -> int:
    QGuiApplication(sys.argv)
    if not SOURCE.exists():
        print(f"missing source: {SOURCE}", file=sys.stderr)
        return 1

    renderer = QSvgRenderer(str(SOURCE))
    if not renderer.isValid():
        print(f"could not parse: {SOURCE}", file=sys.stderr)
        return 1

    images = [render(renderer, size) for size in SIZES]

    # QImageWriter emits a single frame per file, so build the ICO container by
    # hand from PNG-compressed frames. Every size here is <256, and 256 is
    # encoded as 0 per the ICO format.
    import struct
    from PySide6.QtCore import QBuffer, QByteArray

    frames = []
    for image in images:
        # Hold the QByteArray in a local: QBuffer does not take ownership, and a
        # temporary would be collected while the buffer still points at it.
        storage = QByteArray()
        buffer = QBuffer(storage)
        buffer.open(QBuffer.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        frames.append((image.width(), bytes(storage)))

    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries = b""
    payload = b""
    for width, data in frames:
        dimension = 0 if width >= 256 else width
        entries += struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset
        )
        payload += data
        offset += len(data)

    TARGET.write_bytes(header + entries + payload)
    print(f"wrote {TARGET} ({TARGET.stat().st_size} bytes, sizes: {list(SIZES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
