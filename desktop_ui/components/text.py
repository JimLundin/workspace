"""Qt colours, fonts and capsules from the kit's shades, type and looks."""

from functools import lru_cache
from typing import assert_never

lazy from PySide6.QtCore import QRectF
lazy from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen

from desktop_ui.components import typeface
from desktop_ui.components.appearance import GlassLook, Look, Shade, SolidLook
from desktop_ui.qt_runtime import prepare

prepare()


def color(shade: Shade) -> QColor:
    value = QColor(shade.color)
    value.setAlphaF(shade.opacity)
    return value


def face(pixels: float, weight: int = 400, family: str = typeface.FAMILY) -> QFont:
    """Inter at a pixel size and CSS weight; Qt's 96 logical DPI makes a point 4/3 pixels."""
    value = QFont(family)
    value.setPointSizeF(pixels * 0.75)
    value.setWeight(QFont.Weight(weight))
    return value


@lru_cache(maxsize=32)
def inter(pixels: int, weight: QFont.Weight, *, tabular: bool = False) -> QFont:
    """Inter at a whole pixel size, shared and never changed; tabular digits keep a reading's width as it changes."""
    value = QFont(typeface.FAMILY)
    value.setPixelSize(pixels)
    value.setWeight(weight)
    if tabular:
        value.setFeature(QFont.Tag("tnum"), 1)
    return value


def hit() -> QColor:
    """Invisible, but Windows' per-pixel hit-testing routes the pointer here."""
    return QColor(0, 0, 0, 1)


def outline(bounds: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(bounds, radius, radius)
    return path


def paint_capsule(painter: QPainter, path: QPainterPath, look: Look, opacity: float = 1.0) -> None:
    """A capsule's material. Composition draws glass behind the window, so Qt paints only the hit fill;
    solid takes its fill and a 1 px edge at `opacity`."""
    match look:
        case GlassLook():
            painter.fillPath(path, hit())
        case SolidLook(fill=fill, edge=edge):
            painter.setOpacity(opacity)
            painter.fillPath(path, color(fill))
            painter.setPen(QPen(color(edge), 1))
            painter.drawPath(path)
            painter.setOpacity(1)
        case _:
            assert_never(look)
