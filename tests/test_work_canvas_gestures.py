"""Canvas gesture decisions through immutable scene observations."""

from dataclasses import replace

from assistant.work_canvas_gestures import (
    BubbleDrag,
    BubbleTarget,
    CancelGesture,
    ClickBubble,
    ConnectBubbles,
    GestureScene,
    Idle,
    MovePreview,
    NestBubble,
    PlaceBubbles,
    PointerMoved,
    PointerReleased,
    PressBubble,
    PressConnector,
    RelationPreview,
    ScenePoint,
    transition,
)
from assistant.work_canvas_layout import Box
from assistant.work_canvas_model import Placement


def scene() -> GestureScene:
    return GestureScene(
        (
            BubbleTarget("group:drag", Box(0, 0, 360, 400), None, frozenset(("group:drag", "note:child"))),
            BubbleTarget("note:child", Box(24, 172, 300, 160), "group:drag", frozenset(("note:child",))),
            BubbleTarget("group:target", Box(500, 0, 360, 400), None, frozenset(("group:target",))),
        ),
        None,
    )


def drag() -> BubbleDrag:
    return BubbleDrag(
        "group:drag",
        ScenePoint(100, 20),
        (Placement("group:drag", 0, 0), Placement("note:child", 24, 172)),
        None,
        frozenset(("group:drag", "note:child")),
    )


def test_container_gesture_moves_the_subtree_and_cancellation_restores_it() -> None:
    # Defect: pointer movement translates only the frame, selects an invisible
    # descendant as a drop owner, or cancellation leaves a partial move behind.
    current = transition(Idle.READY, PressBubble(drag()), scene())
    click = transition(current.state, PointerReleased(ScenePoint(100, 20)), scene())
    assert click.effect == ClickBubble("group:drag")
    below_threshold = transition(current.state, PointerMoved(ScenePoint(102, 21), 10), scene())
    assert below_threshold.state == current.state
    # The exact native threshold begins a drag; one extra pixel must not be
    # required or a user's small intended drag can open an editor instead.
    boundary = transition(current.state, PointerMoved(ScenePoint(110, 20), 10), scene())
    assert boundary.effect == MovePreview((Placement("group:drag", 10, 0), Placement("note:child", 34, 172)), None)
    moving = transition(current.state, PointerMoved(ScenePoint(120, 200), 10), scene())
    assert moving.effect == MovePreview((Placement("group:drag", 20, 180), Placement("note:child", 44, 352)), None)
    released = transition(moving.state, PointerReleased(ScenePoint(120, 200)), scene())
    assert released.effect == PlaceBubbles("group:drag", (Placement("group:drag", 20, 180), Placement("note:child", 44, 352)))
    cancelled = transition(moving.state, CancelGesture.CANCEL, scene())
    assert cancelled.state is Idle.READY and cancelled.effect == MovePreview(drag().positions, None)


def test_drop_creates_containment_while_connector_creates_a_relationship() -> None:
    # Defect: connector drops reparent evidence or ordinary drops merely draw
    # lines; a nested bubble dropped in empty overview must become a root.
    current = transition(Idle.READY, PressBubble(drag()), scene())
    moving = transition(current.state, PointerMoved(ScenePoint(600, 100), 10), scene())
    nested = transition(moving.state, PointerReleased(ScenePoint(600, 100)), scene())
    assert nested.effect == NestBubble("group:drag", "group:target", (Placement("group:drag", 500, 80), Placement("note:child", 524, 252)))
    drawing = transition(Idle.READY, PressConnector("group:drag", ScenePoint(340, 64)), scene())
    preview = transition(drawing.state, PointerMoved(ScenePoint(600, 100), 10), scene())
    assert preview.effect == RelationPreview("group:drag", ScenePoint(600, 100), "group:target")
    connected = transition(drawing.state, PointerReleased(ScenePoint(600, 100)), scene())
    assert connected.effect == ConnectBubbles("group:drag", "group:target")
    leaf = BubbleDrag("note:child", ScenePoint(50, 200), (Placement("note:child", 24, 172),), "group:drag", frozenset(("note:child",)))
    current = transition(Idle.READY, PressBubble(leaf), scene())
    moving = transition(current.state, PointerMoved(ScenePoint(1000, 1000), 10), scene())
    rooted = transition(moving.state, PointerReleased(ScenePoint(1000, 1000)), scene())
    assert rooted.effect == NestBubble("note:child", None, (Placement("note:child", 974, 972),))


def test_dragging_the_focused_root_preserves_its_parent_on_empty_space() -> None:
    # Defect: moving a focused canvas root reparents it into itself or detaches
    # it from its original work when the cursor leaves all visible bubbles.
    focused = replace(scene(), scope_id="group:drag")
    start = transition(Idle.READY, PressBubble(replace(drag(), parent_id="group:outer")), focused)
    moving = transition(start.state, PointerMoved(ScenePoint(1000, 1000), 10), focused)
    result = transition(moving.state, PointerReleased(ScenePoint(1000, 1000)), focused)
    assert result.effect == PlaceBubbles("group:drag", (Placement("group:drag", 900, 980), Placement("note:child", 924, 1152)))
