"""Shared immediate feedback inside the native button's actual hit rectangle."""

lazy from PySide6.QtCore import QRectF, Qt
lazy from PySide6.QtGui import QColor, QPainter, QPen
lazy from PySide6.QtWidgets import QAbstractButton

from assistant.qt_runtime import prepare
from assistant.ui_components.appearance import GLASS_ACCENT

prepare()


def paint_feedback(button: QAbstractButton, painter: QPainter, ink: str) -> None:
    # Qt owns pointer, press, focus and enabled state. Paint from those current
    # observations without adding UI state or changing the button's geometry.
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    bounds = QRectF(button.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
    # Controls are capsules; the kit's hover and press fills are 8% and 14% of the ink.
    radius = min(bounds.width(), bounds.height()) / 2
    if button.isEnabled() and (button.underMouse() or button.isDown()):
        fill = QColor(ink)
        fill.setAlpha(36 if button.isDown() else 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(bounds, radius, radius)
    if button.isEnabled() and button.hasFocus():
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(GLASS_ACCENT), 2))
        ring = bounds.adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(ring, radius - 1, radius - 1)
    painter.restore()
