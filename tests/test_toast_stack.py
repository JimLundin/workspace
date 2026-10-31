"""Toast stack sizing, capacity and placement from measured card sizes."""

from assistant.toast_stack import (
    Active,
    Column,
    Fit,
    Measured,
    Placement,
    Retiring,
    Space,
    Stacking,
    Viewport,
    allocate,
    fit,
    frames,
    space,
)
from winapi.shapes import Rect

TALL = Viewport(Rect(0, 0, 400, 800), 1.0, 20)
SHORT = Viewport(Rect(0, 0, 400, 300), 1.0, 20)
READING = Measured(200, 60, 140, 0)


def test_space_allocation_reserves_previews_and_prioritizes_pending_input() -> None:
    spaces = (Space(80, 250, 0), Space(80, 300, 2), Space(80, 250, 0), Space(40, 40, 3))
    assert allocate(spaces, 650) == (80, 300, 230, 40)
    assert allocate(spaces, 1000) == (250, 300, 250, 40)
    assert allocate(spaces, 200) == (0, 80, 80, 40)
    assert allocate(spaces, 120) == (0, 80, 0, 40)
    for available in range(1001):
        heights = allocate(spaces, available)
        assert sum(heights) <= available
        assert all(height == 0 or space.minimum <= height <= space.preferred for height, space in zip(heights, spaces, strict=True))


def test_pending_input_prefers_more_height_and_previews_keep_two_lines() -> None:
    # Defect: the rank caps swap or ignore scale, or a preview loses its two lines.
    assert space(Measured(700, 60, 600, 2), TALL) == Space(116, 480, 2)
    assert space(Measured(700, 60, 600, 3), TALL) == Space(116, 360, 3)
    assert space(Measured(700, 60, 600, 0), Viewport(TALL.area, 2.0, 20)) == Space(116, 700, 0)
    assert space(Measured(90, 60, 30, 0), TALL) == Space(90, 90, 0)


def test_retiring_cards_hold_their_space_until_an_arrival_needs_it() -> None:
    # Defect: a leaving card pushes the next page's arrival out of the viewport,
    # or retiring windows exceed the bounded native pool.
    assert fit(Column((READING, READING), (100,), 5), TALL) == Fit((200, 200), 1, 5)
    assert fit(Column((READING, READING), (100,), 5), SHORT) == Fit((116, 142), 0, 5)
    small = Measured(50, 50, 0, 0)
    assert fit(Column((small,) * 4, (50, 40, 30), 5), TALL) == Fit((50,) * 4, 1, 5)


def test_capacity_drops_to_the_cards_that_fit_but_keeps_one() -> None:
    # Defect: an overfull stack keeps its capacity and never re-projects, or reduces to zero cards.
    assert fit(Column((READING,) * 3, (), 5), SHORT) == Fit((0, 116, 132), 0, 2)
    tall = Measured(400, 300, 100, 0)
    assert fit(Column((tall,), (), 3), SHORT) == Fit((0,), 0, 1)
    assert fit(Column((tall,), (), 1), SHORT) == Fit((0,), 0, 1)


def test_feed_width_fits_narrow_work_areas() -> None:
    # Defect: a card wider than the work area spills past the margin.
    assert Viewport(Rect(0, 0, 250, 600), 1.0, 20).width == 218
    assert Viewport(Rect(0, 0, 1000, 600), 1.5, 30).width == 540


def test_feed_stacks_upward_and_retiring_cards_hold_their_place() -> None:
    slots = (Active(100, 0), Retiring(50), Active(80, 0))
    assert frames(slots, TALL, Stacking.FEED) == (Placement(684, 1.0), Placement(534, 1.0))


def test_trail_closes_retiring_space_fades_by_rank_and_pushes_older_phases_up() -> None:
    # Defect: a short arrival leaves a tall older phase stationary, or older phases stay opaque.
    assert frames((Active(100, 0), Retiring(50), Active(80, 650)), TALL, Stacking.TRAIL) == (Placement(684, 1.0), Placement(594, 0.42))
    assert frames((Active(100, 0), Active(80, 560)), TALL, Stacking.TRAIL) == (Placement(684, 1.0), Placement(560, 0.42))
    assert frames((Active(100, 0), Active(80, 600)), TALL, Stacking.PUSH) == (Placement(684, 1.0), Placement(584, 0.42))
    trail = frames((Active(10, 1000),) * 6, TALL, Stacking.TRAIL)
    assert trail == tuple(Placement(y, alpha) for y, alpha in zip((774, 754, 734, 714, 694, 674), (1.0, 0.42, 0.14, 0.04, 0.02, 0.02), strict=True))
