"""Across every transition between capsule arrangements, capsules never touch and rest one gap apart."""

from dataclasses import dataclass
from itertools import pairwise

from hypothesis import strategies

from assistant.island_layout import Content, Metrics, frame
from assistant.island_model import Action, CapsuleView, Key, Zone
from assistant.island_motion import IslandMotion, Shown, advance, placed, retarget, settled
from tests.properties.generation import cases, property_test

ZONES = {Key.LAYER: Zone.LEAD, Key.AGENT: Zone.LEAD, Key.ISLAND: Zone.ISLAND, Key.RECORDING: Zone.TRAIL, Key.INBOX: Zone.TRAIL}


@dataclass(frozen=True, slots=True)
class Journey:
    arrangements: tuple[tuple[Shown, ...], ...]
    steps: tuple[float, ...]


def arrangement(draw: strategies.DrawFn) -> tuple[Shown, ...]:
    optional = (Key.LAYER, Key.AGENT, Key.RECORDING, Key.INBOX)
    included = draw(strategies.lists(strategies.booleans(), min_size=len(optional), max_size=len(optional)))
    keys = (Key.ISLAND, *(key for key, chosen in zip(optional, included, strict=True) if chosen))
    return tuple(
        Shown(CapsuleView(key, ZONES[key], (), key.name, Action.OPEN_MENU), Content(draw(strategies.integers(34, 260)), ()))
        for key in Key
        if key in keys
    )


def journeys(draw: strategies.DrawFn) -> Journey:
    arrangements = tuple(arrangement(draw) for _ in range(draw(strategies.integers(2, 5))))
    steps = tuple(draw(strategies.lists(strategies.floats(0.001, 0.25, width=64), min_size=1, max_size=20)))
    return Journey(arrangements, steps)


@property_test(cases(journeys))
def test_capsules_never_overlap_in_flight_and_rest_exactly_one_gap_apart(journey: Journey) -> None:
    motion = IslandMotion()
    for target in journey.arrangements:
        motion = retarget(motion, target, animate=True)
        for step in journey.steps:
            motion = advance(motion, step)
            boxes = tuple(framed.box for framed in frame(placed(motion), Metrics(4000)))
            assert all(left.x + left.width <= right.x + 1e-9 for left, right in pairwise(boxes)), "Capsules overlapped in flight."
    while not settled(motion):
        motion = advance(motion, 0.05)
    boxes = tuple(framed.box for framed in frame(placed(motion), Metrics(4000)))
    assert [box.width for box in boxes] == [shown.content.width for shown in journey.arrangements[-1]]
    assert all(abs(right.x - (left.x + left.width) - 6) < 1e-9 for left, right in pairwise(boxes))
