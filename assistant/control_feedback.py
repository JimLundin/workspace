"""Shared immediate feedback inside the native button's actual hit rectangle."""

lazy from PySide6.QtCore import QRectF, Qt
lazy from PySide6.QtGui import QColor, QPainter, QPen
lazy from PySide6.QtWidgets import QAbstractButton

from assistant.qt_runtime import prepare

prepare()


def paint_feedback(button: QAbstractButton, painter: QPainter, ink: str) -> None:
    # Qt owns pointer, press, focus and enabled state. Paint from those current
    # observations without adding UI state or changing the button's geometry.
    painter.save()
    bounds = QRectF(button.rect()).adjusted(.5, .5, -.5, -.5)
    if button.isEnabled() and (button.underMouse() or button.isDown()):
        fill = QColor(ink)
        fill.setAlpha(54 if button.isDown() else 28)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(bounds, 10, 10)
    if button.isEnabled() and button.hasFocus():
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(ink), 1, Qt.PenStyle.DotLine))
        painter.drawRoundedRect(bounds.adjusted(2, 2, -2, -2), 8, 8)
    painter.restore()
