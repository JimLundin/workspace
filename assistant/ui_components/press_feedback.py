"""A filled circular control inside a card, with immediate feedback in its hit rectangle."""

lazy from PySide6.QtCore import QRectF, Qt
lazy from PySide6.QtGui import QPainter, QPen
lazy from PySide6.QtWidgets import QAbstractButton

from assistant.qt_runtime import prepare
from assistant.ui_components.bubble import Controls
from assistant.ui_components.text import color

prepare()


def paint_feedback(button: QAbstractButton, painter: QPainter, controls: Controls) -> None:
    # Qt owns pointer, press, focus and enabled state. Paint from those current
    # observations without adding UI state or changing the button's geometry.
    painter.save()
    bounds = QRectF(button.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
    side = min(bounds.width(), bounds.height())
    circle = QRectF(bounds.center().x() - side / 2, bounds.center().y() - side / 2, side, side)
    active = button.isEnabled() and (button.underMouse() or button.isDown())
    fill = controls.press if active and button.isDown() else controls.hover if active else controls.fill
    painter.setPen(QPen(color(controls.edge), 1))
    painter.setBrush(color(fill))
    painter.drawEllipse(circle)
    if button.isEnabled() and button.hasFocus():
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(color(controls.focus), 2))
        painter.drawEllipse(circle.adjusted(1, 1, -1, -1))
    painter.restore()
