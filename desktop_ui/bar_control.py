"""The bar's round controls: Qt owns pointer, press and focus; each control paints its own feedback."""

from typing import override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.components.appearance import Lettering
from desktop_ui.components.text import color
from desktop_ui.qt_runtime import prepare

prepare()


class KeyboardFocus(QtWidgets.QAbstractButton):
    """A button that rings itself only for keyboard focus, as `:focus-visible` does, and can paint the bar's round control feedback."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.ringed = False  # Qt owns focus; the widget remembers only how focus arrived.

    @override
    def focusInEvent(self, event: QtGui.QFocusEvent) -> None:
        super().focusInEvent(event)
        self.ringed = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        self.update()

    @override
    def focusOutEvent(self, event: QtGui.QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.ringed = False
        self.update()

    def paint_feedback(self, painter: QtGui.QPainter, lettering: Lettering, *, selected: bool) -> None:
        """Press, hover or selection fill and the keyboard ring, round at the button's height: a circle, or a pill when wider."""
        bounds = QtCore.QRectF(self.rect())
        corner = bounds.height() / 2
        painter.save()
        if self.isDown() or self.underMouse() or selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color(lettering.press if self.isDown() or selected else lettering.hover))
            painter.drawRoundedRect(bounds, corner, corner)
        if self.hasFocus() and self.ringed:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QtGui.QPen(color(lettering.ink), 1.5))
            painter.drawRoundedRect(bounds.adjusted(1, 1, -1, -1), corner - 1, corner - 1)
        painter.restore()
