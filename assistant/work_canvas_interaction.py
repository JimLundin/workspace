"""Qt owns pointer capture and previews; immutable decisions own the gestures.

Native items mutate only in this UI owner. No document/layout work occurs during
pointer movement. The panel applies the single immutable commit effect on release.
"""

from collections.abc import Iterator
from typing import Protocol

lazy from PySide6 import QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.ui_components.canvas_bubble import CanvasBubble
from assistant.work_canvas_gestures import (
    BubbleDrag,
    CancelGesture,
    DrawingRelation,
    Gesture,
    GestureEffect,
    GestureScene,
    Idle,
    MovePreview,
    PointerMoved,
    PointerReleased,
    PressBubble,
    PressConnector,
    RelationPreview,
    ScenePoint,
    transition,
)
from assistant.work_canvas_model import Placement


class InteractionHost(Protocol):
    @property
    def canvas(self) -> QtWidgets.QGraphicsView: ...
    @property
    def scene(self) -> QtWidgets.QGraphicsScene: ...
    def bubbles(self) -> Iterator[CanvasBubble]: ...
    def capture_gesture_scene(self) -> GestureScene: ...
    def gesture_placements(self) -> tuple[Placement, ...]: ...
    def gesture_status(self, text: str) -> None: ...
    def apply_gesture(self, effect: GestureEffect) -> None: ...
    def update_connection_geometry(self) -> None: ...


class CanvasInteraction:
    def __init__(self, owner: InteractionHost) -> None:
        self.owner: InteractionHost = owner
        self.gesture: Gesture = Idle.READY
        self.gesture_scene: GestureScene = GestureScene((), None)
        self.relation_preview: QtWidgets.QGraphicsPathItem | None = None

    def press_bubble(self, identity: str, point: ScenePoint) -> None:
        match self.gesture:
            case DrawingRelation():
                return
            case _:
                self.gesture_scene = self.owner.capture_gesture_scene()
        target = next(bubble for bubble in self.gesture_scene.bubbles if bubble.id == identity)
        state = self.owner.gesture_placements()
        positions = tuple(position for position in state if position.id in target.members)
        drag = BubbleDrag(identity, point, positions, target.parent_id, target.members)
        self.gesture = transition(self.gesture, PressBubble(drag), self.gesture_scene).state

    def pointer(self, event: PointerMoved | PointerReleased | PressConnector) -> None:
        match event:
            case PressConnector():
                self.gesture_scene = self.owner.capture_gesture_scene()
            case PointerMoved(point=point):
                event = PointerMoved(point, QtWidgets.QApplication.startDragDistance() / self.owner.canvas.transform().m11())
            case _:
                pass
        result = transition(self.gesture, event, self.gesture_scene)
        self.gesture = result.state
        match result.effect:
            case MovePreview(positions=positions, target_id=target):
                indexed = frozendict((position.id, position) for position in positions)
                for bubble in self.owner.bubbles():
                    position = indexed.get(bubble.identity)
                    if position is not None:
                        bubble.setPos(position.x, position.y)
                    bubble.highlight_drop(active=bubble.identity == target)
                self.owner.update_connection_geometry()
            case RelationPreview(source_id=identity, point=point, target_id=target):
                self.preview_relation(identity, point)
                for bubble in self.owner.bubbles():
                    bubble.highlight_drop(active=bubble.identity == target)
            case _ as effect:
                self.owner.apply_gesture(effect)
        match result.state:
            case Idle():
                self.clear_gesture_preview()
            case _:
                pass

    def clear_gesture_preview(self) -> None:
        if self.relation_preview is not None:
            self.owner.scene.removeItem(self.relation_preview)
            self.relation_preview = None
        for bubble in self.owner.bubbles():
            bubble.highlight_drop(active=False)

    def preview_relation(self, identity: str, point: ScenePoint) -> None:
        source = next(bubble for bubble in self.owner.bubbles() if bubble.identity == identity)
        first = source.mapToScene(source.connector.pos())
        if self.relation_preview is None:
            self.relation_preview = QtWidgets.QGraphicsPathItem()
            pen = QtGui.QPen(QtGui.QColor("#c4a5e8"), 2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self.relation_preview.setPen(pen)
            self.relation_preview.setZValue(30)
            self.relation_preview.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.owner.scene.addItem(self.relation_preview)
        path = QtGui.QPainterPath(first)
        path.lineTo(point.x, point.y)
        self.relation_preview.setPath(path)

    def start_relation(self, identity: str) -> None:
        self.clear_gesture_preview()
        source = next(bubble for bubble in self.owner.bubbles() if bubble.identity == identity)
        point = source.mapToScene(source.connector.pos())
        self.pointer(PressConnector(identity, ScenePoint(point.x(), point.y())))
        self.owner.gesture_status("Click another bubble to connect; Escape cancels.")

    def cancel(self) -> bool:
        match self.gesture:
            case Idle():
                return False
            case _:
                result = transition(self.gesture, CancelGesture.CANCEL, self.gesture_scene)
                self.gesture = result.state
                match result.effect:
                    case MovePreview(positions=positions):
                        indexed = frozendict((position.id, position) for position in positions)
                        for bubble in self.owner.bubbles():
                            position = indexed.get(bubble.identity)
                            if position is not None:
                                bubble.setPos(position.x, position.y)
                        self.owner.update_connection_geometry()
                    case _:
                        pass
                self.clear_gesture_preview()
                self.owner.gesture_status("")
                return True
