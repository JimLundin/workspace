"""Lightweight scene controls; only an opened editor embeds native widgets.

Qt owns hover, press and focus state. Action definitions remain immutable, and
the same activation path handles pointer, keyboard and caller-driven actions.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.ui_components.appearance import GLASS_ACCENT, Tokens
from assistant.ui_components.canvas_look import CONTROL, Role, color, face, flat
from assistant.vector_icons import icon


@dataclass(frozen=True, slots=True)
class ControlAction:
    title: str
    activate: Callable[[], None]
    symbol: str | None = None


class CanvasControl(QtWidgets.QGraphicsRectItem):
    """A 28 px capsule: a plain symbol, or a filled caption that fits its text, as the kit's buttons."""

    def __init__(self, parent: QtWidgets.QGraphicsItem, action: ControlAction, theme: Tokens) -> None:
        super().__init__(parent)
        self.action: ControlAction = action
        self.theme: Tokens = theme
        self.hovered: bool = False
        self.pressed: bool = False
        self.available: float = CONTROL
        self.setRect(0, 0, CONTROL, CONTROL)
        self.setToolTip(action.title)
        self.setAcceptHoverEvents(True)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_caption(self, title: str) -> None:
        self.action = replace(self.action, title=title)
        self.setToolTip(title)
        self.set_width(self.available)
        self.update()

    def set_width(self, width: float) -> None:
        """A caption fits its text within `width`; a symbol stays a circle."""
        self.available = width
        caption = QtGui.QFontMetricsF(face(Role.CONTROL)).horizontalAdvance(self.action.title) + 24
        self.setRect(0, 0, CONTROL if self.action.symbol is not None else min(width, caption), CONTROL)

    def click(self) -> None:
        self.action.activate()

    @override
    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem, widget: QtWidgets.QWidget | None = None) -> None:
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        captioned = self.action.symbol is None
        # Inside a card a caption is filled, never glass; a symbol fills only under the pointer.
        fill = self.theme.press if self.pressed else self.theme.hover if self.hovered or captioned else None
        painter.setPen(QtGui.QPen(QtGui.QColor(GLASS_ACCENT), 2) if self.hasFocus() else Qt.PenStyle.NoPen)
        painter.setBrush(color(fill) if fill is not None else Qt.BrushStyle.NoBrush)
        bounds = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(bounds, bounds.height() / 2, bounds.height() / 2)
        if self.action.symbol is not None:
            icon(self.action.symbol, flat(self.theme.ink2, self.theme.solid)).paint(painter, QtCore.QRect(6, 6, 16, 16))
        else:
            painter.setPen(color(self.theme.ink))
            painter.setFont(face(Role.CONTROL))
            painter.drawText(self.rect().adjusted(12, 0, -12, 0), Qt.AlignmentFlag.AlignCenter, self.action.title)
        painter.restore()

    @override
    def hoverEnterEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    @override
    def hoverLeaveEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    @override
    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        self.pressed = True
        self.setFocus()
        self.update()
        event.accept()

    @override
    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        activate = self.pressed and self.rect().contains(event.pos())
        self.pressed = False
        self.update()
        event.accept()
        if activate:
            self.click()

    @override
    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.click()
            event.accept()
        else:
            super().keyPressEvent(event)
