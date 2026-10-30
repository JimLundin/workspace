"""One source-badge paint contract for floating notifications and canvas bubbles."""

lazy from PySide6 import QtCore, QtGui

import assistant.feed_icons
from assistant.feed_origin import Origin
from assistant.ui_components.bubble_style import Palette


def paint_origins(painter: QtGui.QPainter, origins: tuple[Origin, ...], colors: Palette) -> None:
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    for index, origin in reversed(tuple(enumerate(origins[:3]))):
        x = index * 18
        painter.setPen(QtGui.QPen(QtGui.QColor(colors.edge), 1))
        painter.setBrush(QtGui.QColor(colors.surface))
        painter.drawEllipse(QtCore.QRectF(x + 0.5, 0.5, 27, 27))
        assistant.feed_icons.icon(origin.app).paint(painter, QtCore.QRect(x + 5, 5, 18, 18))
    painter.restore()
