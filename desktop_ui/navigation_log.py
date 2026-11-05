"""The navigation log: every change of the focused window, so the declared layouts
can be changed to need less of it. One JSON object per line in
`%LOCALAPPDATA%/workspace/navigation.jsonl`. It records which application and
desktop the user came from and went to, what caused it and how long the previous
window had been in front; applications by executable file name or pinned web app,
never window titles or content.

A Workspace navigation is recorded when the dispatcher decides it. A foreground
change Workspace didn't cause is classified from the input observed just before
it. The decisions are pure: the application observer passes observations and
timestamps in, and appends the entries it gets back.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Final, Literal, assert_never

from pydantic import TypeAdapter

from desktop_ui.navigation import (
    AppKey,
    CycleApp,
    Effect,
    Focus,
    JumpDesktop,
    Launch,
    Navigated,
    Navigation,
    PagerClick,
    ShowWindow,
    Source,
    SpatialFocus,
    Switch,
    SwitcherPick,
    World,
    Zoom,
    ZoomIn,
    ZoomOut,
    identity,
    owner,
)
from desktop_ui.shell_items import PinnedApp
from desktop_ui.window_layout import App, Program, Setup
from usage import DIRECTORY
from winapi.win_events import CaptureStart, SwitchEnd, SwitchStart

NAVIGATION_LOG: Final = DIRECTORY / "navigation.jsonl"
ROTATE_BYTES: Final = 16 * 1024 * 1024
"""At this size the log becomes `navigation.1.jsonl`, replacing the one before."""

ECHO_S: Final = 2.0
"""How long a Workspace focus or desktop switch may take to bring its window to the front."""
LAUNCH_ECHO_S: Final = 15.0
"""How long a launched application may take to show its first window."""
ALT_TAB_S: Final = 0.5
"""A foreground change this soon after the Alt+Tab switcher closes is its choice."""
CLICK_S: Final = 0.5
"""A foreground change this soon after a mouse capture began is that click's."""
SWITCHER_STALE_S: Final = 60.0
"""A switcher open this long without closing missed its close event."""

type Kind = Literal[
    "app_key",
    "cycle_app",
    "show_window",
    "switcher_pick",
    "spatial_focus",
    "jump_desktop",
    "pager_click",
    "zoom",
    "external",
]
type Cause = Literal["key", "pager", "toolbar", "alt_tab", "mouse", "other"]
type SetupName = Literal["laptop_only", "home", "work"]


@dataclass(frozen=True, slots=True)
class Entry:
    """One line of the log; docs/window-placement.md describes every field."""

    time: datetime
    setup: SetupName | None
    kind: Kind
    cause: Cause
    from_app: str | None
    to_app: str | None
    from_desktop: int | None
    to_desktop: int | None
    other_desktop: bool = field(kw_only=True)
    launched: bool = field(kw_only=True)
    dwell_ms: int | None = field(kw_only=True)


ENTRY: Final = TypeAdapter[Entry](Entry)


@dataclass(frozen=True, slots=True)
class Focused:
    """The window in front, as the log last saw it."""

    window: int
    app: App | None
    desktop: int | None
    since: float | None
    """When it came to the front (`time.monotonic()`); None when it was in front before observation began."""


@dataclass(frozen=True, slots=True)
class Arrival:
    """Another program's window came to the front, resolved against the observer's world."""

    window: int
    app: App | None
    desktop: int | None
    held: bool = field(kw_only=True)
    """A mouse button was down when the event was delivered."""


@dataclass(frozen=True, slots=True)
class Expected:
    """A Workspace navigation's effect, until its window comes to the front or `until` passes."""

    effect: Focus | Switch | Launch
    until: float


@dataclass(frozen=True, slots=True)
class SwitcherOpen:
    origin: Focused | None
    opened: float


@dataclass(frozen=True, slots=True)
class SwitcherClosed:
    """Alt+Tab ended; its choice is the next foreground change, or the last one while it was open."""

    origin: Focused | None
    opened: float
    closed: float


type Switcher = SwitcherOpen | SwitcherClosed | None


@dataclass(frozen=True, slots=True)
class Tracker:
    focused: Focused | None
    expected: Expected | None
    switcher: Switcher
    captured: float | None
    """When a window last captured the mouse."""


START: Final = Tracker(None, None, None, None)


@dataclass(frozen=True, slots=True)
class Moment:
    """When something happened: the monotonic clock for durations, local time for the entry."""

    at: float
    time: datetime
    setup: Setup | None


def setup_name(setup: Setup | None) -> SetupName | None:
    match setup:
        case Setup.LAPTOP_ONLY:
            return "laptop_only"
        case Setup.HOME:
            return "home"
        case Setup.WORK:
            return "work"
        case None:
            return None
        case _:
            assert_never(setup)


def app_name(app: App | None) -> str | None:
    match app:
        case Program(exe=exe):
            return exe
        case PinnedApp():
            return app.value
        case None:
            return None
        case _:
            assert_never(app)


def kind(navigation: Navigation) -> Kind:
    """Spelled out rather than derived from class names, so renaming a variant can't change the log."""
    match navigation:
        case AppKey():
            return "app_key"
        case CycleApp():
            return "cycle_app"
        case ShowWindow():
            return "show_window"
        case SwitcherPick():
            return "switcher_pick"
        case SpatialFocus():
            return "spatial_focus"
        case JumpDesktop():
            return "jump_desktop"
        case PagerClick():
            return "pager_click"
        case Zoom():
            return "zoom"
        case _:
            assert_never(navigation)


def cause(source: Source) -> Cause:
    match source:
        case Source.KEY:
            return "key"
        case Source.PAGER:
            return "pager"
        case Source.TOOLBAR:
            return "toolbar"
        case _:
            assert_never(source)


def dwell_ms(focused: Focused | None, at: float) -> int | None:
    return round((at - focused.since) * 1000) if focused is not None and focused.since is not None else None


def external(origin: Focused | None, arrival: Arrival, moment: Moment, why: Cause) -> Entry:
    """Four independent facts of one change: where from, where to, when, and why; each caller decides them differently."""
    from_desktop = origin.desktop if origin is not None else None
    return Entry(
        moment.time,
        setup_name(moment.setup),
        "external",
        why,
        app_name(origin.app if origin is not None else None),
        app_name(arrival.app),
        from_desktop,
        arrival.desktop,
        other_desktop=from_desktop is not None and arrival.desktop is not None and from_desktop != arrival.desktop,
        launched=False,
        dwell_ms=dwell_ms(origin, moment.at),
    )


def seen(tracker: Tracker, world: World) -> Tracker:
    """The first observation tells which window was already in front."""
    if tracker.focused is not None:
        return tracker
    return replace(tracker, focused=Focused(world.foreground, owner(world, world.foreground), world.current, None))


def expected(chosen: Effect, focused: Focused | None, at: float) -> Expected | None:
    """Zooms, refusals and focusing the window already in front bring nothing forward."""
    match chosen:
        case Focus(window=window) if focused is not None and focused.window == window:
            return None
        case Focus() | Switch():
            return Expected(chosen, at + ECHO_S)
        case Launch():
            return Expected(chosen, at + LAUNCH_ECHO_S)
        case ZoomIn() | ZoomOut() | None:
            return None
        case _:
            assert_never(chosen)


def echoes(effect: Focus | Switch | Launch, arrival: Arrival) -> bool:
    """Whether a foreground change is where a Workspace navigation was going."""
    match effect:
        case Focus(window=window):
            return arrival.window == window
        case Switch(desktop=desktop, then=then):
            return arrival.window == then if then is not None else arrival.desktop == desktop
        case Launch(app=app):
            return arrival.app == identity(app)
        case _:
            assert_never(effect)


def noticed(tracker: Tracker, event: CaptureStart | SwitchStart | SwitchEnd) -> Tracker:
    match event:
        case CaptureStart(at=at):
            return replace(tracker, captured=at)
        case SwitchStart(at=at):
            return replace(tracker, switcher=SwitcherOpen(tracker.focused, at))
        case SwitchEnd(at=at):
            match tracker.switcher:
                case SwitcherOpen(origin=origin, opened=opened):
                    return replace(tracker, switcher=SwitcherClosed(origin, opened, at))
                case SwitcherClosed() | None:
                    return tracker
                case _:
                    assert_never(tracker.switcher)
        case _:
            assert_never(event)


def switched(origin: Focused | None, focused: Focused | None, moment: Moment) -> tuple[Entry, ...]:
    """A finished Alt+Tab whose choice came to the front before the switcher closed; nothing when it was cancelled."""
    if focused is None or (origin is not None and origin.window == focused.window):
        return ()
    return (external(origin, Arrival(focused.window, focused.app, focused.desktop, held=False), moment, "alt_tab"),)


def settled(tracker: Tracker, moment: Moment) -> tuple[Tracker, tuple[Entry, ...]]:
    """Time passing: an expected navigation expires, and an Alt+Tab with no later change is recorded."""
    expired = tracker.expected is not None and moment.at > tracker.expected.until
    current = replace(tracker, expected=None) if expired else tracker
    match current.switcher:
        case SwitcherClosed(origin=origin, closed=closed) if moment.at > closed + ALT_TAB_S:
            return replace(current, switcher=None), switched(origin, current.focused, moment)
        case SwitcherOpen(origin=origin, opened=opened) if moment.at > opened + SWITCHER_STALE_S:
            return replace(current, switcher=None), switched(origin, current.focused, moment)
        case SwitcherOpen() | SwitcherClosed() | None:
            return current, ()
        case _:
            assert_never(current.switcher)


def navigated(tracker: Tracker, decided: tuple[Effect, Navigated], moment: Moment) -> tuple[Tracker, tuple[Entry, ...]]:
    """A Workspace navigation is logged as decided, even when it moved nothing; its foreground change is then expected."""
    current, earlier = settled(tracker, moment)
    chosen, record = decided
    entry = Entry(
        moment.time,
        setup_name(moment.setup),
        kind(record.navigation),
        cause(record.navigation.source),
        app_name(record.from_app),
        app_name(record.to_app),
        record.from_desktop,
        record.to_desktop,
        other_desktop=record.from_desktop != record.to_desktop,
        launched=record.launched,
        dwell_ms=dwell_ms(current.focused, moment.at),
    )
    return replace(current, expected=expected(chosen, current.focused, moment.at)), (*earlier, entry)


def arrived(tracker: Tracker, arrival: Arrival, moment: Moment) -> tuple[Tracker, tuple[Entry, ...]]:
    """A foreground change: a Workspace navigation's echo, a step inside one, or an external navigation.

    While the Alt+Tab switcher is open, the windows it brings forward aren't navigations
    yet; the first change after it closes is its choice. While a Workspace navigation is
    under way, a change neither clicked nor switched to is the shell passing focus along.
    """
    current, earlier = settled(tracker, moment)
    previous = current.focused
    if previous is not None and previous.window == arrival.window:
        return current, earlier
    moved = replace(current, focused=Focused(arrival.window, arrival.app, arrival.desktop, moment.at))
    match current.switcher:
        case SwitcherOpen():
            return moved, earlier
        case SwitcherClosed(origin=origin) if origin is not None and origin.window == arrival.window:
            return replace(current, focused=origin, switcher=None), earlier
        case SwitcherClosed(origin=origin):
            return replace(moved, switcher=None), (*earlier, external(origin, arrival, moment, "alt_tab"))
        case None:
            pass
        case _:
            assert_never(current.switcher)
    expecting = current.expected
    if expecting is not None and echoes(expecting.effect, arrival):
        return replace(moved, expected=None), earlier
    clicked = arrival.held or (current.captured is not None and 0 <= moment.at - current.captured <= CLICK_S)
    if expecting is not None and not clicked:
        return moved, earlier
    return moved, (*earlier, external(previous, arrival, moment, "mouse" if clicked else "other"))


def rotated(path: Path) -> Path:
    return path.with_name(f"{path.stem}.1{path.suffix}")


def append(entries: Iterable[Entry], path: Path) -> None:
    """Only the application observer's worker appends, so lines never interleave."""
    lines = b"".join(ENTRY.dump_json(entry) + b"\n" for entry in entries)
    if not lines:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size >= ROTATE_BYTES:
        path.replace(rotated(path))
    with path.open("ab") as log:
        log.write(lines)
