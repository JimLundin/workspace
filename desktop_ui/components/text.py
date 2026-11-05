"""Qt colours and fonts from the kit's shades and type."""

lazy from PySide6.QtGui import QColor, QFont

from desktop_ui.components import typeface
from desktop_ui.components.appearance import Shade
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
