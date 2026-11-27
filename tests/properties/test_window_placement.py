from collections import Counter
from dataclasses import dataclass, replace
from itertools import combinations

from hypothesis import strategies

from desktop_ui.window_layout import (
    Group,
    Placement,
    Program,
    Screens,
    Target,
    place,
    screens,
)
from tests.properties.generation import cases, property_test
from tests.test_window_layout import SETUPS
from winapi.screen import Monitor
from winapi.shapes import Rect

DECLARED = tuple(
    dict.fromkeys(
        app for layout in SETUPS.layouts.values() for app in layout.places
    )
)
OTHERS = (Program("python.exe"), Program("notepad.exe"), Program("mspaint.exe"))
SIZES = (
    *(
        (tuple((size.width, size.height) for size in sizes))
        for sizes in SETUPS.externals.values()
    ),
    ((1920, 1080),),
)
"""Every setup the test's own setups recognize, and an unrecognized screen."""


@dataclass(frozen=True, slots=True)
class PlacementCase:
    where: Screens
    apps: tuple[Group, ...]


def monitor(draw: strategies.DrawFn, area: Rect, *, internal: bool) -> Monitor:
    taskbar = draw(strategies.sampled_from((0, 48, 72)))
    return Monitor(
        area,
        Rect(area.left, area.top, area.right, area.bottom - taskbar),
        primary=internal,
        internal=internal,
    )


def beside(draw: strategies.DrawFn, size: tuple[int, int], left: int) -> Rect:
    top = draw(strategies.integers(-size[1], 1200))
    return Rect(left, top, left + size[0], top + size[1])


def apps(draw: strategies.DrawFn, handles: range) -> tuple[Group, ...]:
    chosen = tuple(
        app for app in (*DECLARED, *OTHERS) if draw(strategies.booleans())
    )
    counts = tuple(draw(strategies.integers(1, 6)) for _ in chosen)
    starts = tuple(
        handles.start + sum(counts[:index]) for index in range(len(counts))
    )
    return tuple(
        Group(app, tuple(range(start, start + size)))
        for app, start, size in zip(chosen, starts, counts, strict=True)
    )


def placement_cases(draw: strategies.DrawFn) -> PlacementCase:
    size = draw(strategies.sampled_from(((1920, 1200), (2560, 1600))))
    laptop = monitor(draw, beside(draw, size, 0), internal=True)
    sizes = draw(strategies.sampled_from(SIZES))
    lefts = tuple(
        size[0] + sum(width for width, _ in sizes[:index])
        for index in range(len(sizes))
    )
    externals = tuple(
        monitor(draw, beside(draw, external, left), internal=False)
        for external, left in zip(sizes, lefts, strict=True)
    )
    where = screens((laptop, *externals), SETUPS)
    assert where is not None
    side_by_side = draw(strategies.sampled_from((None, 1, 2, 3)))
    layout = replace(where.layout, side_by_side=side_by_side)
    return PlacementCase(
        replace(where, layout=layout), apps(draw, range(1, 100))
    )


def stacked(a: Target, b: Target) -> bool:
    return bool(
        (above := a.layer)
        and (below := b.layer)
        and above.place == below.place
        and above.depth != below.depth
    )


def overlapping(placement: Placement) -> tuple[tuple[int, int], ...]:
    def meet(a: Rect, b: Rect) -> bool:
        return (
            a.left < b.right
            and b.left < a.right
            and a.top < b.bottom
            and b.top < a.bottom
        )

    return tuple(
        (first, second)
        for (first, a), (second, b) in combinations(placement.items(), 2)
        if a.desktop == b.desktop and not stacked(a, b) and meet(a.rect, b.rect)
    )


def too_wide(placement: Placement, side_by_side: int | None) -> bool:
    shown = Counter(
        (target.desktop, target.layer)
        for target in placement.values()
        if target.layer
    )
    return side_by_side is not None and any(
        count > side_by_side for count in shown.values()
    )


@property_test(cases(placement_cases))
def test_placed_windows_overlap_only_across_layers_and_each_gets_one_place(
    case: PlacementCase,
) -> None:
    placement = place(case.where, case.apps)
    assert not overlapping(placement)
    assert not too_wide(placement, case.where.layout.side_by_side)
    assert set(placement) == {
        handle for group in case.apps for handle in group.windows
    }
    assert all(
        target.desktop < case.where.layout.desktops
        for target in placement.values()
    )
