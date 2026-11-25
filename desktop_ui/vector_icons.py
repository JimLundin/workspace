from dataclasses import dataclass
from functools import lru_cache
from typing import Final

lazy from PySide6 import QtCore, QtGui, QtSvg
lazy from PySide6.QtCore import Qt

from desktop_ui.components.appearance import Shade
from desktop_ui.fluent_icons import FILLED, REGULAR
from desktop_ui.qt_runtime import prepare

prepare()

_STOP = '<rect x="4.25" y="4.25" width="7.5" height="7.5" rx="1.8"/>'
_CPU = (
    '<path fill-rule="evenodd" d="M4.5 4h7a.5.5 0 0 1 .5.5v7a.5.5 0 0 1-.5.5h-7a.5.5 0 0 1-.5-.5v-7a.5.5 0 0 1 .5-.5zM5 5v6h6V5z"/>'
    '<rect x="6.5" y="6.5" width="3" height="3" rx=".5"/>'
    '<path d="M6 2h1v2H6zM9 2h1v2H9zM6 12h1v2H6zM9 12h1v2H9zM2 6h2v1H2zM2 9h2v1H2zM12 6h2v1h-2zM12 9h2v1h-2z"/>'
)
_MEMORY = (
    '<path fill-rule="evenodd" d="M2 4h12a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H2a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zm0 1v5h12V5z"/>'
    '<path d="M3.5 6h2v3h-2zM7 6h2v3H7zM10.5 6h2v3h-2zM3 11h1v2H3zM5 11h1v2H5zM7 11h1v2H7zM9 11h1v2H9zM11 11h1v2h-1z"/>'
)

_EARLIER = '<path d="M10.35 3.15l.7.7L6.9 8l4.15 4.15-.7.7L5.5 8z"/>'
_LATER = '<path d="M5.65 3.15l-.7.7L9.1 8l-4.15 4.15.7.7L10.5 8z"/>'

_QUESTION = '<path d="M11 10a2 2 0 0 1 4 0c0 1-1.5 1.2-1.5 2h-1c0-1.4 1.5-1.5 1.5-2a1 1 0 0 0-2 0z"/><circle cx="13" cy="14" r=".6"/>'
_ABSENT = '<path d="M11 11h4v1h-4z"/>'


@dataclass(frozen=True, slots=True)
class Badged:
    base: str
    badge: str


OWN: Final = frozendict(
    {
        "stop": _STOP,
        "stop.fill": _STOP,
        "cpu": _CPU,
        "memory": _MEMORY,
        "earlier": _EARLIER,
        "later": _LATER,
    }
)
"""Symbols drawn here rather than taken from Fluent."""
BADGED: Final = frozendict(
    {
        "speaker-unknown": Badged("speaker-on", _QUESTION),
        "wifi-unknown": Badged("wifi", _QUESTION),
        "wifi-absent": Badged("wifi", _ABSENT),
    }
)
BADGE_SCALE: Final = 0.7
FALLBACK: Final = "doc"
"""What an unknown name draws."""


def symbol(name: str) -> str:
    if (own := OWN.get(name)) is not None:
        return own
    if (badged := BADGED.get(name)) is not None:
        return (
            f'<g transform="scale({BADGE_SCALE})">'
            + REGULAR[badged.base]
            + "</g>"
            + badged.badge
        )
    base, filled = name.removesuffix(".fill"), name.endswith(".fill")
    return (
        (FILLED.get(base) if filled else None)
        or REGULAR.get(base)
        or REGULAR[FALLBACK]
    )


@lru_cache(maxsize=128)
def icon(name: str, color: str, size: int = 16) -> QtGui.QIcon:
    source = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="{color}">{symbol(name)}</svg>'
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(source.encode()))
    pixmap = QtGui.QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QtGui.QIcon(pixmap)


def paint_icon(
    painter: QtGui.QPainter,
    name: str,
    ink: Shade,
    bounds: QtCore.QRect | QtCore.QRectF,
) -> None:
    area = QtCore.QRectF(bounds)
    symbol = icon(name, ink.color).pixmap(
        QtCore.QSize(round(area.width()), round(area.height())),
        painter.device().devicePixelRatioF(),
    )
    painter.save()
    painter.setOpacity(ink.opacity)
    painter.drawPixmap(area, symbol, QtCore.QRectF(symbol.rect()))
    painter.restore()
