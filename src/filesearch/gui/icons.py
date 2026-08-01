"""Lucide icons, inlined and recoloured at runtime.

The SVG sources are embedded as strings rather than shipped as files so the
frozen PyInstaller build has no data paths to resolve. Lucide draws with
`currentColor`, which Qt's SVG renderer does not resolve, so the colour is
substituted before rasterising and the result cached per colour and size.

Icons are from Lucide, ISC licensed. See THIRD-PARTY-NOTICES.txt.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_HEADER = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" '
    'stroke-linecap="round" stroke-linejoin="round">'
)

# Path bodies only; the wrapper above supplies the shared attributes.
_BODIES: dict[str, str] = {
    # Navigation.
    "search": '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
    "folder-tree": (
        '<path d="M20 10a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1h-2.5a1 1 0 0 1-.8-.4l-.9-1.2A1 1 0 0 0 15 3h-2a1 1 0 0 0-1 1v5a1 1 0 0 0 1 1Z"/>'
        '<path d="M20 21a1 1 0 0 0 1-1v-3a1 1 0 0 0-1-1h-2.9a1 1 0 0 1-.88-.55l-.42-.85a1 1 0 0 0-.92-.6H13a1 1 0 0 0-1 1v5a1 1 0 0 0 1 1Z"/>'
        '<path d="M3 5a2 2 0 0 0 2 2h3"/><path d="M3 3v13a2 2 0 0 0 2 2h3"/>'
    ),
    "plug": (
        '<path d="M12 22v-5"/><path d="M15 8V2"/>'
        '<path d="M17 8a1 1 0 0 1 1 1v4a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1z"/>'
        '<path d="M9 8V2"/>'
    ),
    # Two sliders rather than the classic gear: the gear's twelve lobes blur
    # into a fuzzy circle at 16px, these four shapes stay crisp.
    "settings-2": (
        '<path d="M14 17H5"/><path d="M19 7h-9"/>'
        '<circle cx="17" cy="17" r="3"/><circle cx="7" cy="7" r="3"/>'
    ),
    # Actions.
    "external-link": (
        '<path d="M15 3h6v6"/><path d="M10 14 21 3"/>'
        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
    ),
    "folder-open": (
        '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>'
    ),
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "minus": '<path d="M5 12h14"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "trash-2": (
        '<path d="M10 11v6"/><path d="M14 11v6"/>'
        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
        '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
    ),
    "play": '<path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"/>',
    "square": '<rect width="18" height="18" x="3" y="3" rx="2"/>',
    "rotate-cw": (
        '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/>'
        '<path d="M21 3v5h-5"/>'
    ),
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "triangle-alert": (
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
        '<path d="M12 9v4"/><path d="M12 17h.01"/>'
    ),
    "copy": (
        '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>'
        '<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>'
    ),
    "database": (
        '<ellipse cx="12" cy="5" rx="9" ry="3"/>'
        '<path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/>'
        '<path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/>'
    ),
    "eye": (
        '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/>'
        '<circle cx="12" cy="12" r="3"/>'
    ),
    "eye-off": (
        '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49"/>'
        '<path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/>'
        '<path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/>'
        '<path d="m2 2 20 20"/>'
    ),
    "sun": (
        '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/>'
        '<path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/>'
        '<path d="M2 12h2"/><path d="M20 12h2"/>'
        '<path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>'
    ),
    "moon": (
        '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/>'
    ),
    "file-text": (
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/>'
        '<path d="M16 13H8"/><path d="M16 17H8"/>'
    ),
    "inbox": (
        '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/>'
        '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>'
    ),
}

# The brand mark: a solid hexagon with the inner circle knocked out.
# Derived from Lucide "bolt", filled rather than stroked.
BRAND_MARK = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{color}">'
    '<path fill-rule="evenodd" clip-rule="evenodd" '
    'd="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 '
    '1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z M12 8a4 4 0 1 0 0 8 4 4 0 1 0 0-8z"/>'
    "</svg>"
)

_cache: dict[tuple, QPixmap] = {}


def clear_cache() -> None:
    """Drop rendered pixmaps. Called when the theme changes."""
    _cache.clear()


def _render(svg: str, size: int, ratio: float) -> QPixmap:
    px = max(1, int(round(size * ratio)))
    image = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, px, px))
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def pixmap(name: str, color: str, size: int = 16, width: float = 2, ratio: float = 1.0) -> QPixmap:
    key = (name, color, size, width, ratio)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    body = _BODIES.get(name)
    if body is None:
        raise KeyError(f"unknown icon: {name}")
    svg = (_HEADER.format(w=width) + body + "</svg>").replace("currentColor", color)
    result = _render(svg, size, ratio)
    _cache[key] = result
    return result


def icon(name: str, color: str, size: int = 16, width: float = 2, ratio: float = 1.0) -> QIcon:
    return QIcon(pixmap(name, color, size, width, ratio))


def brand_pixmap(color: str, size: int = 20, ratio: float = 1.0) -> QPixmap:
    key = ("__brand__", color, size, 0, ratio)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    result = _render(BRAND_MARK.format(color=color), size, ratio)
    _cache[key] = result
    return result
