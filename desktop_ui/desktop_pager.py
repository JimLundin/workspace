"""The bar's desktop pager and its swipe: pure views of the observer's desktops.

The pager shows one number per desktop with the current one marked, between
previous and next ends. Its names list the applications placed on each desktop.
While the Apps layer is held or locked, each target also carries the physical
keycap that reaches it, read from the layout. While the firmware keyboard holds
Ctrl+Alt+Shift, each target carries its chord instead, read from the chord table.

A horizontal scroll over the bar is a swipe: one gesture, however many wheel
events it produces, steps one desktop.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Final, assert_never

from desktop_ui.keymap import shortcut
from desktop_ui.shell_items import WEB_APPS, PinnedApp
from desktop_ui.window_layout import App, Program
from miryoku.firmware import CHORDS
from miryoku.layout import Layer
from protocol import Tool

JUMPS: Final = (Tool.DESKTOP_1, Tool.DESKTOP_2, Tool.DESKTOP_3, Tool.DESKTOP_4)


@dataclass(frozen=True, slots=True)
class Hints:
    """The keys reaching each pager target; empty unless a keyboard is ready to reach them."""

    previous: str | None
    next: str | None
    desktops: tuple[str | None, ...]


NO_HINTS = Hints(None, None, ())


@dataclass(frozen=True, slots=True)
class PagerDesktop:
    label: str
    name: str
    """Its accessible name and tooltip: the desktop and the applications placed there."""
    current: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class PagerView:
    desktops: tuple[PagerDesktop, ...]
    hints: Hints


def label(app: App) -> str:
    match app:
        case PinnedApp():
            return WEB_APPS[app].label
        case Program(exe=exe):
            return exe.removesuffix(".exe")
        case _:
            assert_never(app)


class Reach(Enum):
    """Which keys reach the pager's targets right now."""

    APPS_LAYER = auto()
    """The laptop's Apps layer is held or locked: its physical keycaps."""
    CHORD = auto()
    """The firmware keyboard holds Ctrl+Alt+Shift: each target's chord."""


def reach(layer: str | None, *, chord: bool) -> Reach | None:
    """The keys reaching the pager now. The bar's layer reading names the layer first, then whether it's locked."""
    if chord:
        return Reach.CHORD
    return Reach.APPS_LAYER if layer is not None and layer.split(" · ")[0] == Layer.APPS.name else None


def keycap(tool: Tool, keys: Reach) -> str | None:
    match keys:
        case Reach.APPS_LAYER:
            found = shortcut(tool)
            return found.tap if found is not None else None
        case Reach.CHORD:
            # The hint shows while Ctrl+Alt+Shift are held, so the letter alone completes the chord.
            return CHORDS.get(tool)
        case _:
            assert_never(keys)


def pager(placed: Sequence[Sequence[App]], current: int, keys: Reach | None) -> PagerView:
    """The pager for these desktops, each with the applications placed on it."""

    def desktop(index: int, apps: Sequence[App]) -> PagerDesktop:
        listed = ", ".join(label(app) for app in apps) or "No placed apps"
        here = " (current)" if index == current else ""
        return PagerDesktop(str(index + 1), f"Desktop {index + 1}{here} · {listed}", current=index == current)

    desktops = tuple(desktop(index, apps) for index, apps in enumerate(placed))
    if keys is None:
        return PagerView(desktops, NO_HINTS)
    jumps = tuple(keycap(JUMPS[index], keys) if index < len(JUMPS) else None for index in range(len(desktops)))
    return PagerView(desktops, Hints(keycap(Tool.DESKTOP_PREVIOUS, keys), keycap(Tool.DESKTOP_NEXT, keys), jumps))


@dataclass(frozen=True, slots=True)
class Swipe:
    """One gesture's wheel events so far: when the last arrived, how far they travelled and whether it has stepped."""

    last: float
    travel: int
    stepped: bool


SWIPE_GAP: Final = 0.35
"""Seconds without wheel events that end a gesture."""
SWIPE_TRAVEL: Final = 60
"""Wheel travel, in eighths of a degree, a gesture needs before it steps: half a notch."""


def swipe(gesture: Swipe | None, delta: int, now: float) -> tuple[Swipe, int]:
    """The gesture after one horizontal wheel event, and the desktop step it takes now: -1, 1 or 0.

    Scrolling right (a negative delta, as fingers swiping left) goes to the next desktop.
    """
    ongoing = gesture is not None and now - gesture.last <= SWIPE_GAP
    travel = (gesture.travel if gesture is not None and ongoing else 0) + delta
    stepped = gesture is not None and ongoing and gesture.stepped
    if stepped or abs(travel) < SWIPE_TRAVEL:
        return Swipe(now, travel, stepped), 0
    return Swipe(now, travel, True), -1 if travel > 0 else 1
