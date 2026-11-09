"""The bar's controls: Qt owns pointer, press and focus; each control paints its own feedback in the bar's reading face."""

from typing import override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.components.appearance import Lettering
from desktop_ui.components.text import color, inter
from desktop_ui.qt_runtime import prepare

prepare()


def font(*, strong: bool) -> QtGui.QFont:
    """The bar's reading face: 12 px Inter with tabular digits, so readings keep their width as digits change."""
    return inter(12, QtGui.QFont.Weight.DemiBold if strong else QtGui.QFont.Weight.Medium, tabular=True)


def paint_feedback(  # noqa: PLR0913 - one shape, its corner and the three states it shows, plus the ring's inset
    painter: QtGui.QPainter,
    lettering: Lettering,
    bounds: QtCore.QRectF,
    corner: float,
    *,
    pressed: bool,
    hovered: bool,
    ringed: bool = False,
    inset: float = 1.0,
) -> None:
    """A press or hover fill over `bounds` and the keyboard ring `inset` inside it, rounded at `corner`."""
    painter.save()
    if pressed or hovered:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color(lettering.press if pressed else lettering.hover))
        painter.drawRoundedRect(bounds, corner, corner)
    if ringed:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QtGui.QPen(color(lettering.ink), 1.5))
        painter.drawRoundedRect(bounds.adjusted(inset, inset, -inset, -inset), corner - inset, corner - inset)
    painter.restore()


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

    @property
    def focus_ringed(self) -> bool:
        return self.hasFocus() and self.ringed

    def paint_round(self, painter: QtGui.QPainter, lettering: Lettering, *, selected: bool) -> None:
        """Press, hover or selection fill and the keyboard ring, round at the button's height: a circle, or a pill when wider."""
        bounds = QtCore.QRectF(self.rect())
        paint_feedback(
            painter, lettering, bounds, bounds.height() / 2, pressed=self.isDown() or selected, hovered=self.underMouse(), ringed=self.focus_ringed
        )
