"""Shared native pointer adaptation and controls for every canvas bubble."""

from typing import Protocol, override

lazy from PySide6 import QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.ui_components.canvas_controls import CanvasControl, ControlAction
from assistant.work_canvas_gestures import PointerMoved, PointerReleased, PressConnector, ScenePoint


class CanvasPointer(Protocol):
    def press_bubble(self, identity: str, point: ScenePoint) -> None: ...
    def pointer(self, event: PointerMoved | PointerReleased | PressConnector) -> None: ...


class CanvasEvents(Protocol):
    def select(self, identity: str) -> None: ...
    def inspect(self, identity: str) -> None: ...

    @property
    def interaction(self) -> CanvasPointer: ...

    def reflow(self) -> None: ...
    def open_context(self, identity: str) -> None: ...
    def context_menu(self, identity: str) -> None: ...
    def toggle_bubble(self, identity: str) -> None: ...


class CanvasBubble(QtWidgets.QGraphicsRectItem):
    """One pointer/menu owner for both containers and evidence bubbles."""

    def __init__(self, identity: str, events: CanvasEvents) -> None:
        super().__init__()
        self.identity: str = identity
        self.events: CanvasEvents = events
        self.drop_target: bool = False
        self.setFlags(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.options: CanvasControl = CanvasControl(self, ControlAction("Bubble options", lambda: events.context_menu(identity), "more"))
        self.connector: QtWidgets.QGraphicsEllipseItem = QtWidgets.QGraphicsEllipseItem(self)
        self.connector.setRect(-6, -6, 12, 12)
        self.connector.setPen(QtGui.QPen(QtGui.QColor("#ba9de3"), 1.5))
        self.connector.setBrush(QtGui.QColor("#262337"))
        self.connector.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.connector.setCursor(Qt.CursorShape.CrossCursor)
        self.connector.setToolTip("Drag to another bubble to create a relationship")

    def resize_controls(self) -> None:
        self.options.setPos(self.rect().width() - 48, 16)
        self.connector.setPos(self.rect().width() - 18, 64)

    def highlight_drop(self, *, active: bool) -> None:
        if self.drop_target != active:
            self.drop_target = active
            self.update()

    def paint_selection(self, painter: QtGui.QPainter) -> None:
        if self.drop_target or self.isSelected():
            painter.save()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QtGui.QPen(QtGui.QColor("#c4a5e8"), 2 if self.drop_target else 1.5))
            painter.drawRoundedRect(self.rect().adjusted(8.5, 8.5, -1, -1), 26, 26)
            painter.restore()

    @override
    def contextMenuEvent(self, event: QtWidgets.QGraphicsSceneContextMenuEvent) -> None:
        self.events.context_menu(self.identity)
        event.accept()

    @override
    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        point = event.scenePos()
        observation = ScenePoint(point.x(), point.y())
        self.events.select(self.identity)
        if self.connector.contains(self.connector.mapFromParent(event.pos())):
            self.events.interaction.pointer(PressConnector(self.identity, observation))
        else:
            self.events.interaction.press_bubble(self.identity, observation)
        event.accept()

    @override
    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        point = event.scenePos()
        self.events.interaction.pointer(PointerMoved(ScenePoint(point.x(), point.y()), 0))
        event.accept()

    @override
    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        point = event.scenePos()
        self.events.interaction.pointer(PointerReleased(ScenePoint(point.x(), point.y())))
        event.accept()

    @override
    def mouseDoubleClickEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        self.events.open_context(self.identity)
        event.accept()
