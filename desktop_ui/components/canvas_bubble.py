"""Shared native pointer adaptation and controls for every canvas bubble."""

from typing import Protocol, override

lazy from PySide6 import QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.components.appearance import GLASS_ACCENT, Shade, Tokens
from desktop_ui.components.canvas_controls import CanvasControl, ControlAction
from desktop_ui.components.canvas_look import CONTROL, Surface, paint_selection, paint_surface, surface_fill
from desktop_ui.components.text import color
from desktop_ui.work_canvas_gestures import PointerMoved, PointerReleased, PressConnector, ScenePoint


class CanvasPointer(Protocol):
    def press_bubble(self, identity: str, point: ScenePoint) -> None: ...
    def pointer(self, event: PointerMoved | PointerReleased | PressConnector) -> None: ...


class CanvasEvents(Protocol):
    def select(self, identity: str) -> None: ...
    def inspect(self, identity: str) -> None: ...

    @property
    def interaction(self) -> CanvasPointer: ...

    @property
    def theme(self) -> Tokens: ...

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
        self.theme: Tokens = events.theme
        self.drop_target: bool = False
        self.surface: Surface = Surface.CARD
        self.setFlags(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.options: CanvasControl = CanvasControl(self, ControlAction("Bubble options", lambda: events.context_menu(identity), "more"), self.theme)
        # The relationship port: an accent ring, as relationships are drawn in the accent.
        self.connector: QtWidgets.QGraphicsEllipseItem = QtWidgets.QGraphicsEllipseItem(self)
        self.connector.setRect(-5, -5, 10, 10)
        self.connector.setPen(QtGui.QPen(color(Shade(GLASS_ACCENT, 0.75)), 1.5))
        self.connector.setBrush(QtGui.QColor(self.theme.solid))
        self.connector.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.connector.setCursor(Qt.CursorShape.CrossCursor)
        self.connector.setToolTip("Drag to another bubble to create a relationship")

    def resize_controls(self) -> None:
        width = self.rect().width()
        self.options.setPos(width - 12 - CONTROL, 8)
        self.connector.setPos(width - 12 - CONTROL / 2, 46)

    def highlight_drop(self, *, active: bool) -> None:
        if self.drop_target != active:
            self.drop_target = active
            self.update()

    def paint_bubble(self, painter: QtGui.QPainter) -> None:
        paint_surface(painter, self.rect(), self.theme, self.surface)
        if self.drop_target or self.isSelected():
            paint_selection(painter, self.rect(), self.surface, drop=self.drop_target)

    def surface_color(self) -> QtGui.QColor:
        """The ring that separates stacked badges takes the surface beneath it."""
        return QtGui.QColor(self.theme.window) if self.surface is Surface.GROUP else surface_fill(self.theme, self.surface)

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
