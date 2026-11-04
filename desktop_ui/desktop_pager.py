"""The bar's desktop pager and its swipe: pure views of the observer's desktops.

The pager shows one number per desktop with the current one marked, between
previous and next ends. Its names list the applications placed on each desktop.
While either keyboard holds Ctrl+Alt+Shift, each target carries its chord letter,
read from the chord table.

A horizontal scroll over the bar is a swipe: one gesture, however many wheel
events it produces, steps one desktop.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, assert_never

from desktop_ui.shell_items import WEB_APPS, PinnedApp
from desktop_ui.window_layout import App, Program
from miryoku.firmware import CHORDS
from protocol import Tool

JUMPS: Final = (Tool.DESKTOP_1, Tool.DESKTOP_2, Tool.DESKTOP_3, Tool.DESKTOP_4)


@dataclass(frozen=True, slots=True)
class Hints:
    """The chord letter reaching each pager target; empty unless a keyboard holds Ctrl+Alt+Shift."""

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


def pager(placed: Sequence[Sequence[App]], current: int, *, chord: bool) -> PagerView:
    """The pager for these desktops, each with the applications placed on it.

    The hints show while Ctrl+Alt+Shift are held, so the letter alone completes the chord.
    """

    def desktop(index: int, apps: Sequence[App]) -> PagerDesktop:
        listed = ", ".join(label(app) for app in apps) or "No placed apps"
        here = " (current)" if index == current else ""
        return PagerDesktop(str(index + 1), f"Desktop {index + 1}{here} · {listed}", current=index == current)

    desktops = tuple(desktop(index, apps) for index, apps in enumerate(placed))
    if not chord:
        return PagerView(desktops, NO_HINTS)
    jumps = tuple(CHORDS.get(JUMPS[index]) if index < len(JUMPS) else None for index in range(len(desktops)))
    return PagerView(desktops, Hints(CHORDS.get(Tool.DESKTOP_PREVIOUS), CHORDS.get(Tool.DESKTOP_NEXT), jumps))


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
