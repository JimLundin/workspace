"""Display layout decisions, including hotplug geometry and protected windows."""

from dataclasses import replace
from unittest import TestCase
from uuid import UUID

from assistant.monitor_layout import Display, MoveTile, OrientWorkspace, Tile, displays, plan


def display(index: int, width: int, height: int, count: int) -> Display:
    return Display(
        str(UUID(int=index + 1)),
        index * width,
        0,
        width,
        height,
        1.0,
        str(index + 1),
        str(UUID(int=index + 100)),
        "horizontal",
        tuple(Tile(str(UUID(int=index * 100 + offset + 1000)), focused=offset == 0) for offset in range(count)),
    )


def test_new_displays_receive_tiles_and_focused_window_stays_put() -> None:
    primary, added = display(0, 1920, 1080, 4), display(1, 1920, 1080, 0)
    moves = tuple(operation for operation in plan((primary, added)) if isinstance(operation, MoveTile))
    assert len(moves) == 2 and all(move.workspace == added.workspace for move in moves)
    assert primary.tiles[0].identity not in {move.identity for move in moves}


def test_logical_area_and_portrait_orientation_guide_placement() -> None:
    laptop = replace(display(0, 1920, 1200, 6), scale=1.5)
    large = display(1, 2560, 1440, 0)
    portrait = display(2, 1440, 2560, 0)
    operations = plan((laptop, large, portrait))
    moves = [operation for operation in operations if isinstance(operation, MoveTile)]
    assert len(moves) == 5  # One on laptop, three on large, two on portrait.
    assert OrientWorkspace(portrait.workspace_id, "vertical") in operations
    assert len([move for move in moves if move.workspace == large.workspace]) == 3
    assert len([move for move in moves if move.workspace == portrait.workspace]) == 2


def test_balanced_layout_is_stable_and_empty_screens_do_not_create_windows() -> None:
    layout = (display(0, 1920, 1080, 2), display(1, 1920, 1080, 2))
    assert plan(layout) == ()
    assert plan(()) == ()
    assert plan((display(0, 1920, 1080, 0),)) == ()


def test_parser_excludes_hidden_floating_minimized_and_dragged_windows() -> None:
    row: dict[str, object] = {"id": str(UUID(int=1)), "x": -1440, "y": -100, "width": 1440, "height": 2560, "scaleFactor": 1.0}
    nodes: list[dict[str, object]] = []
    observations: tuple[tuple[int, str, str, object], ...] = (
        (0, "tiling", "shown", None),
        (1, "floating", "shown", None),
        (2, "tiling", "hidden", None),
        (3, "minimized", "shown", None),
        (4, "tiling", "shown", {}),
    )
    for index, state, shown, drag in observations:
        nodes.append(
            {
                "id": str(UUID(int=10 + index)),
                "type": "window",
                "state": {"type": state},
                "displayState": shown,
                "activeDrag": drag,
                "hasFocus": False,
            }
        )
    row["children"] = [{"id": str(UUID(int=100)), "name": "1", "isDisplayed": True, "tilingDirection": "vertical", "children": nodes}]
    result = displays({"monitors": [row]})
    assert len(result) == 1 and result[0].tiles == (Tile(str(UUID(int=10)), focused=False),)
    assert result[0].x == -1440 and plan(result) == ()
    row["scaleFactor"] = float("nan")
    with TestCase().assertRaises(OSError):
        displays({"monitors": [row]})
