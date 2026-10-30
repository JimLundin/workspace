"""Lightweight scene controls; only an opened editor embeds native widgets.

Qt owns hover, press and focus state. Action definitions remain immutable, and
the same activation path handles pointer, keyboard and caller-driven actions.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.ui_components.bubble_style import Ink
from assistant.ui_components.text import font
from assistant.vector_icons import icon


@dataclass(frozen=True, slots=True)
class ControlAction:
    title: str
    activate: Callable[[], None]
    symbol: str | None = None


class CanvasControl(QtWidgets.QGraphicsRectItem):
    def __init__(self, parent: QtWidgets.QGraphicsItem, action: ControlAction) -> None:
        super().__init__(parent)
        self.action: ControlAction = action
        self.hovered: bool = False
        self.pressed: bool = False
        self.setRect(0, 0, 32, 32)
        self.setToolTip(action.title)
        self.setAcceptHoverEvents(True)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_caption(self, title: str) -> None:
        self.action = replace(self.action, title=title)
        self.setToolTip(title)
        self.update()

    def set_width(self, width: float) -> None:
        self.setRect(0, 0, width, 32)

    def click(self) -> None:
        self.action.activate()

    @override
    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem, widget: QtWidgets.QWidget | None = None) -> None:
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtGui.QColor("#ba9de3") if self.hasFocus() else Qt.PenStyle.NoPen)
        color = "#4a3d5c" if self.pressed else "#3a3148" if self.hovered else "transparent"
        painter.setBrush(QtGui.QColor(color))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)
        if self.action.symbol is not None:
            icon(self.action.symbol, Ink().foreground).paint(painter, QtCore.QRect(8, 8, 16, 16))
        else:
            painter.setPen(QtGui.QColor(Ink().foreground))
            painter.setFont(font(9))
            painter.drawText(self.rect().adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.action.title)
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
