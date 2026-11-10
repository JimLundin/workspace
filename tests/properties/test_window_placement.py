"""No two windows placed on one desktop overlap, and none goes beyond the setup's desktops, in any setup."""

from dataclasses import dataclass
from itertools import combinations

from hypothesis import strategies

from desktop_ui.window_layout import Group, Placement, Program, Screens, place, screens
from tests.properties.generation import cases, property_test
from tests.test_window_layout import SETUPS
from winapi.screen import Monitor
from winapi.shapes import Rect

DECLARED = tuple(dict.fromkeys(app for layout in SETUPS.layouts.values() for app in layout.places))
OTHERS = (Program("python.exe"), Program("notepad.exe"), Program("mspaint.exe"))
SIZES = (*((tuple((size.width, size.height) for size in sizes)) for sizes in SETUPS.externals.values()), ((1920, 1080),))
"""Every setup the test's own setups recognize, and an unrecognized screen."""


@dataclass(frozen=True, slots=True)
class PlacementCase:
    where: Screens
    apps: tuple[Group, ...]


def monitor(draw: strategies.DrawFn, area: Rect, *, internal: bool) -> Monitor:
    taskbar = draw(strategies.sampled_from((0, 48, 72)))
    return Monitor(area, Rect(area.left, area.top, area.right, area.bottom - taskbar), primary=internal, internal=internal)


def beside(draw: strategies.DrawFn, size: tuple[int, int], left: int) -> Rect:
    top = draw(strategies.integers(-size[1], 1200))
    return Rect(left, top, left + size[0], top + size[1])


def apps(draw: strategies.DrawFn, handles: range) -> tuple[Group, ...]:
    chosen = tuple(app for app in (*DECLARED, *OTHERS) if draw(strategies.booleans()))
    counts = tuple(draw(strategies.integers(1, 6)) for _ in chosen)
    starts = tuple(handles.start + sum(counts[:index]) for index in range(len(counts)))
    return tuple(Group(app, tuple(range(start, start + size))) for app, start, size in zip(chosen, starts, counts, strict=True))


def placement_cases(draw: strategies.DrawFn) -> PlacementCase:
    # Screens never overlap: each external starts right of the ones before it.
    size = draw(strategies.sampled_from(((1920, 1200), (2560, 1600))))
    laptop = monitor(draw, beside(draw, size, 0), internal=True)
    sizes = draw(strategies.sampled_from(SIZES))
    lefts = tuple(size[0] + sum(width for width, _ in sizes[:index]) for index in range(len(sizes)))
    externals = tuple(monitor(draw, beside(draw, external, left), internal=False) for external, left in zip(sizes, lefts, strict=True))
    where = screens((laptop, *externals), SETUPS)
    assert where is not None
    return PlacementCase(where, apps(draw, range(1, 100)))


def overlapping(placement: Placement) -> tuple[tuple[int, int], ...]:
    def meet(a: Rect, b: Rect) -> bool:
        return a.left < b.right and b.left < a.right and a.top < b.bottom and b.top < a.bottom

    return tuple((first, second) for (first, a), (second, b) in combinations(placement.items(), 2) if a.desktop == b.desktop and meet(a.rect, b.rect))


@property_test(cases(placement_cases))
def test_placed_windows_never_overlap_and_each_gets_one_place(case: PlacementCase) -> None:
    # Defects: neighbouring regions or split columns round to overlapping edges,
    # undeclared apps overlap in the place for others, a window lands on a
    # desktop the setup doesn't keep, or a window is dropped.
    placement = place(case.where, case.apps)
    assert not overlapping(placement)
    assert set(placement) == {handle for group in case.apps for handle in group.windows}
    assert all(target.desktop < case.where.layout.desktops for target in placement.values())
