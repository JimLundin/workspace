"""Shared vector icons, rendered at native Qt resolution.

Symbols are Fluent UI System Icons drawn for 16 px (see desktop_ui/fluent_icons.py).
A ".fill" suffix selects the filled variant for active states, as SF Symbols names them.
"""

from functools import lru_cache

lazy from PySide6 import QtCore, QtGui, QtSvg
lazy from PySide6.QtCore import Qt

from desktop_ui.fluent_icons import FILLED, REGULAR
from desktop_ui.qt_runtime import prepare

prepare()

# A small rounded square reads as Stop at toolbar size, as SF Symbols' stop.fill does.
_STOP = '<rect x="4.25" y="4.25" width="7.5" height="7.5" rx="1.8"/>'


def symbol(name: str) -> str:
    """The SVG body for a symbol name; unknown names fall back to the document symbol."""
    if name in ("stop", "stop.fill"):
        return _STOP
    if name == "chevron-left":
        return '<g transform="translate(16 0) scale(-1 1)">' + REGULAR["chevron"] + "</g>"
    # Unavailable is not muted or disconnected: a question badge retains the
    # device identity without asserting a state Windows could not observe.
    if name in ("speaker-unknown", "wifi-unknown", "wifi-absent"):
        base_icon = "speaker-on" if name == "speaker-unknown" else "wifi"
        badge = (
            '<path d="M11 11h4v1h-4z"/>'
            if name == "wifi-absent"
            else '<path d="M11 10a2 2 0 0 1 4 0c0 1-1.5 1.2-1.5 2h-1c0-1.4 1.5-1.5 1.5-2a1 1 0 0 0-2 0z"/><circle cx="13" cy="14" r=".6"/>'
        )
        return '<g transform="scale(.7)">' + REGULAR[base_icon] + "</g>" + badge
    base, filled = name.removesuffix(".fill"), name.endswith(".fill")
    return (FILLED.get(base) if filled else None) or REGULAR.get(base) or REGULAR["doc"]


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
