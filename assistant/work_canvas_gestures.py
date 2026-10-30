"""Immutable pointer decisions; Qt and persistence belong to the canvas owner."""

from dataclasses import dataclass, replace
from enum import Enum
from typing import assert_never

from assistant.work_canvas_layout import Box
from assistant.work_canvas_model import Placement


@dataclass(frozen=True, slots=True)
class ScenePoint:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class BubbleTarget:
    id: str
    bounds: Box
    parent_id: str | None
    members: frozenset[str]


@dataclass(frozen=True, slots=True)
class GestureScene:
    bubbles: tuple[BubbleTarget, ...]
    scope_id: str | None


@dataclass(frozen=True, slots=True)
class BubbleDrag:
    id: str
    origin: ScenePoint
    positions: tuple[Placement, ...]
    parent_id: str | None
    members: frozenset[str]


class Idle(Enum):
    READY = "ready"


@dataclass(frozen=True, slots=True)
class PendingDrag:
    drag: BubbleDrag


@dataclass(frozen=True, slots=True)
class MovingBubble:
    drag: BubbleDrag
    point: ScenePoint


@dataclass(frozen=True, slots=True)
class DrawingRelation:
    source_id: str
    point: ScenePoint


type Gesture = Idle | PendingDrag | MovingBubble | DrawingRelation


@dataclass(frozen=True, slots=True)
class PressBubble:
    drag: BubbleDrag


@dataclass(frozen=True, slots=True)
class PressConnector:
    id: str
    point: ScenePoint


@dataclass(frozen=True, slots=True)
class PointerMoved:
    point: ScenePoint
    tolerance: float


@dataclass(frozen=True, slots=True)
class PointerReleased:
    point: ScenePoint


class CancelGesture(Enum):
    CANCEL = "cancel"


type GestureInput = PressBubble | PressConnector | PointerMoved | PointerReleased | CancelGesture


class NoChange(Enum):
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ClickBubble:
    id: str


@dataclass(frozen=True, slots=True)
class MovePreview:
    positions: tuple[Placement, ...]
    target_id: str | None


@dataclass(frozen=True, slots=True)
class RelationPreview:
    source_id: str
    point: ScenePoint
    target_id: str | None


@dataclass(frozen=True, slots=True)
class PlaceBubbles:
    id: str
    positions: tuple[Placement, ...]


@dataclass(frozen=True, slots=True)
class NestBubble:
    id: str
    parent_id: str | None
    positions: tuple[Placement, ...]
    members: frozenset[str]


@dataclass(frozen=True, slots=True)
class ConnectBubbles:
    start: str
    end: str


type GestureEffect = NoChange | ClickBubble | MovePreview | RelationPreview | PlaceBubbles | NestBubble | ConnectBubbles


@dataclass(frozen=True, slots=True)
class GestureResult:
    state: Gesture
    effect: GestureEffect = NoChange.NONE


def contains(bounds: Box, point: ScenePoint) -> bool:
    return bounds.x <= point.x <= bounds.x + bounds.width and bounds.y <= point.y <= bounds.y + bounds.height


def hit(scene: GestureScene, point: ScenePoint, excluded: frozenset[str] = frozenset()) -> BubbleTarget | None:
    def area(bubble: BubbleTarget) -> float:
        return bubble.bounds.width * bubble.bounds.height

    return min(
        (bubble for bubble in scene.bubbles if bubble.id not in excluded and contains(bubble.bounds, point)),
        key=area,
        default=None,
    )


def translated(drag: BubbleDrag, point: ScenePoint) -> tuple[Placement, ...]:
    dx, dy = point.x - drag.origin.x, point.y - drag.origin.y
    # Clamp the complete block, preserving the relative positions of children.
    if drag.positions:
        dx = max(-100000 - min(item.x for item in drag.positions), min(dx, 100000 - max(item.x for item in drag.positions)))
        dy = max(-100000 - min(item.y for item in drag.positions), min(dy, 100000 - max(item.y for item in drag.positions)))
    return tuple(replace(position, x=position.x + dx, y=position.y + dy) for position in drag.positions)


def transition(state: Gesture, event: GestureInput, scene: GestureScene) -> GestureResult:
    match event:
        case CancelGesture.CANCEL:
            match state:
                case MovingBubble(drag=drag):
                    return GestureResult(Idle.READY, MovePreview(drag.positions, None))
                case _:
                    return GestureResult(Idle.READY)
        case PressConnector(id=identity, point=point):
            return GestureResult(DrawingRelation(identity, point), RelationPreview(identity, point, None))
        case PressBubble(drag=drag):
            match state:
                case DrawingRelation():
                    return GestureResult(state)
                case _:
                    return GestureResult(PendingDrag(drag))
        case PointerMoved(point=point, tolerance=tolerance):
            return move(state, PointerMoved(point, tolerance), scene)
        case PointerReleased(point=point):
            return release(state, point, scene)
        case _ as unreachable:
            assert_never(unreachable)


def move(state: Gesture, travel: PointerMoved, scene: GestureScene) -> GestureResult:
    point, tolerance = travel.point, travel.tolerance
    match state:
        case PendingDrag(drag=drag) if abs(point.x - drag.origin.x) + abs(point.y - drag.origin.y) < tolerance:
            return GestureResult(state)
        case PendingDrag(drag=drag) | MovingBubble(drag=drag):
            target = hit(scene, point, drag.members)
            return GestureResult(MovingBubble(drag, point), MovePreview(translated(drag, point), target.id if target else None))
        case DrawingRelation(source_id=source):
            target = hit(scene, point, frozenset((source,)))
            return GestureResult(DrawingRelation(source, point), RelationPreview(source, point, target.id if target else None))
        case Idle():
            return GestureResult(state)
        case _ as unreachable:
            assert_never(unreachable)


def release(state: Gesture, point: ScenePoint, scene: GestureScene) -> GestureResult:
    match state:
        case PendingDrag(drag=drag):
            return GestureResult(Idle.READY, ClickBubble(drag.id))
        case MovingBubble(drag=drag):
            target = hit(scene, point, drag.members)
            parent = target.id if target else drag.parent_id if drag.id == scene.scope_id else scene.scope_id
            positions = translated(drag, point)
            effect = PlaceBubbles(drag.id, positions) if parent == drag.parent_id else NestBubble(drag.id, parent, positions, drag.members)
            return GestureResult(Idle.READY, effect)
        case DrawingRelation(source_id=source):
            target = hit(scene, point, frozenset((source,)))
            return GestureResult(Idle.READY, ConnectBubbles(source, target.id)) if target else GestureResult(Idle.READY)
        case Idle():
            return GestureResult(state)
        case _ as unreachable:
            assert_never(unreachable)
