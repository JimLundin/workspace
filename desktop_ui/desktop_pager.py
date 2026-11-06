"""The bar's desktop pager: a pure view of the observer's desktops.

The pager shows one number per desktop with the current one marked; a click goes
straight to that desktop. Desktops are reached directly, never cycled. Its names
list the applications placed on each desktop. While either keyboard holds
its Apps key, each desktop carries its letter, read from the chord table.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, assert_never

from desktop_ui.shell_items import WEB_APPS, PinnedApp
from desktop_ui.window_layout import App, Program, WorkspaceView
from miryoku.firmware import CHORDS
from protocol import Tool

JUMPS: Final = (Tool.DESKTOP_1, Tool.DESKTOP_2, Tool.DESKTOP_3, Tool.DESKTOP_4, Tool.DESKTOP_5)


@dataclass(frozen=True, slots=True)
class Hints:
    """The chord letter reaching each desktop; empty unless a keyboard holds its Apps key."""

    desktops: tuple[str | None, ...]


NO_HINTS = Hints(())


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
        case WorkspaceView.CANVAS:
            return "Canvas"
        case _:
            assert_never(app)


def pager(placed: Sequence[Sequence[App]], current: int, *, chord: bool) -> PagerView:
    """The pager for these desktops, each with the applications placed on it.

    The hints show while an Apps key is held, so the letter alone completes the request.
    """

    def desktop(index: int, apps: Sequence[App]) -> PagerDesktop:
        listed = ", ".join(label(app) for app in apps) or "No placed apps"
        here = " (current)" if index == current else ""
        return PagerDesktop(str(index + 1), f"Desktop {index + 1}{here} · {listed}", current=index == current)

    desktops = tuple(desktop(index, apps) for index, apps in enumerate(placed))
    if not chord:
        return PagerView(desktops, NO_HINTS)
    jumps = tuple(CHORDS.get(JUMPS[index]) if index < len(JUMPS) else None for index in range(len(desktops)))
    return PagerView(desktops, Hints(jumps))
