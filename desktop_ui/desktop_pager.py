"""The bar's desktop pager: a pure view of the observer's desktops.

The pager shows each desktop as its applications' icons, overlapping left to
right as they sit on screen, with the current one marked; an empty desktop shows
its number. A click goes straight to that desktop. Desktops are reached directly,
never cycled. Its names list the applications placed on each desktop. While either keyboard holds
its Apps key, each desktop carries its letter, read from the chord table.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, assert_never

from desktop_ui.shell_items import PinnedApp, WebApps
from desktop_ui.window_layout import App, Program
from protocol import Tool

JUMPS: Final = (Tool.DESKTOP_1, Tool.DESKTOP_2, Tool.DESKTOP_3, Tool.DESKTOP_4, Tool.DESKTOP_5)


@dataclass(frozen=True, slots=True)
class PagerSpec:
    """What the pager reads: each web app's name and symbol, and the chord letter reaching each desktop."""

    web_apps: WebApps
    letters: tuple[str | None, ...]
    """The chord letter for each desktop in order; desktops past the last have none."""
    desktop: str
    """A desktop's name, before its number..."""
    current: str
    """...the current one's mark..."""
    empty: str
    """...and what an empty desktop holds."""


"""Workspace's own pager; the bar passes it in, tests pass their own."""


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
    apps: tuple[App, ...] = field(default=(), kw_only=True)
    """Its applications left to right, as the face draws them."""


@dataclass(frozen=True, slots=True)
class PagerView:
    desktops: tuple[PagerDesktop, ...]
    hints: Hints
    symbols: frozendict[PinnedApp, str]
    """Each web app's symbol, which its icon shows."""


def label(app: App, web_apps: WebApps) -> str:
    match app:
        case PinnedApp():
            return web_apps[app].label
        case Program(exe=exe):
            return exe.removesuffix(".exe")
        case _:
            assert_never(app)


def pager(placed: Sequence[Sequence[App]], current: int, spec: PagerSpec, *, chord: bool) -> PagerView:
    """The pager for these desktops, each with the applications placed on it.

    The hints show while an Apps key is held, so the letter alone completes the request.
    """

    def desktop(index: int, apps: Sequence[App]) -> PagerDesktop:
        listed = ", ".join(label(app, spec.web_apps) for app in apps) or spec.empty
        here = f" ({spec.current})" if index == current else ""
        return PagerDesktop(str(index + 1), f"{spec.desktop} {index + 1}{here} · {listed}", current=index == current, apps=tuple(apps))

    desktops = tuple(desktop(index, apps) for index, apps in enumerate(placed))
    symbols = frozendict((app, web.glyph) for app, web in spec.web_apps.items())
    if not chord:
        return PagerView(desktops, NO_HINTS, symbols)
    letters = spec.letters
    jumps = tuple(letters[index] if index < len(letters) else None for index in range(len(desktops)))
    return PagerView(desktops, Hints(jumps), symbols)
