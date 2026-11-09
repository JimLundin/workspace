"""The toolbar's applications: pinned web apps, then running applications grouped by
executable, each with stable window ordering and cycling."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

from contracts.members import every_member
from winapi.icon_pixels import Pixels
from winapi.shapes import Rect, Window


class PinnedApp(Enum):
    OUTLOOK = "outlook"
    TEAMS = "teams"


@dataclass(frozen=True, slots=True)
class WebApp:
    label: str
    url: str
    app_id: str
    """Edge's AppUserModelID for its `--app` window; other profiles append `.<profile>`."""
    glyph: str


WEB_APPS: Final = every_member(
    PinnedApp,
    {
        PinnedApp.OUTLOOK: WebApp("Outlook", "https://outlook.cloud.microsoft/mail/", "MSEdge.outlook.cloud.microsoft_/mail/", "mail"),
        PinnedApp.TEAMS: WebApp("Teams", "https://teams.cloud.microsoft/", "MSEdge.teams.cloud.microsoft_/", "chat"),
    },
)
LAUNCH_GRACE = 15.0
"""Seconds a launch may take to show its window before another click launches again."""

type Launches = frozendict[PinnedApp, float]


@dataclass(frozen=True, slots=True)
class Application:
    identity: str
    windows: tuple[Window, ...]
    image: Pixels | None = None


@dataclass(frozen=True, slots=True)
class Pinned:
    app: PinnedApp
    windows: tuple[Window, ...]


type Item = Pinned | Application


@dataclass(frozen=True, slots=True)
class Shelf:
    pinned: tuple[Pinned, ...]
    running: tuple[Application, ...]


EMPTY_SHELF = Shelf(tuple(Pinned(app, ()) for app in PinnedApp), ())


@dataclass(frozen=True, slots=True, order=True)
class Seat:
    """Where a window sits when first seen: its desktop, then its top-left corner."""

    desktop: int
    left: int
    top: int


type Seats = Mapping[int, Seat]
"""Newly seen windows' seats, by handle; a minimized window or one on no known desktop has none."""


def retained(current: Sequence[Window], before: Sequence[Window], seats: Seats) -> tuple[Window, ...]:
    """Windows seen before keep their places; new ones follow in the order they sit, those with no seat last.

    Placement fills an app's places in this order, so windows already placed by an
    earlier run, or restored where they were by their program, keep their places.
    """
    by_handle = frozendict((window.handle, window) for window in current)
    kept = tuple(window.handle for window in before if window.handle in by_handle)
    new = tuple(window for window in current if window.handle not in kept)
    seated = sorted((window for window in new if window.handle in seats), key=lambda window: seats[window.handle])
    return (*(by_handle[handle] for handle in kept), *seated, *(window for window in new if window.handle not in seats))


def applications(observed: Sequence[Window], previous: tuple[Application, ...], seats: Seats) -> tuple[Application, ...]:
    identities = tuple(dict.fromkeys((window.exe or str(window.handle) for window in observed), 0))
    order = tuple(app.identity for app in previous if app.identity in identities)
    order = (*order, *(identity for identity in identities if identity not in order))

    def grouped(identity: str) -> Application:
        current = tuple(window for window in observed if (window.exe or str(window.handle)) == identity)
        before = next((app for app in previous if app.identity == identity), None)
        if before is None:
            return Application(identity, retained(current, (), seats))
        return Application(identity, retained(current, before.windows, seats), before.image)

    return tuple(grouped(identity) for identity in order)


def pinned_app(app_id: str | None) -> PinnedApp | None:
    if app_id is None:
        return None
    return next((app for app, web in WEB_APPS.items() if app_id == web.app_id or app_id.startswith(web.app_id + ".")), None)


def shelf(observed: Sequence[Window], app_ids: Mapping[int, str | None], previous: Shelf, seats: Seats) -> Shelf:
    """Pinned web-app windows fill their slots; every other window joins its running application."""
    owners = tuple(pinned_app(app_ids.get(window.handle)) for window in observed)

    def slot(app: PinnedApp) -> Pinned:
        current = tuple(window for window, owner in zip(observed, owners, strict=True) if owner is app)
        before = next((pinned.windows for pinned in previous.pinned if pinned.app is app), ())
        return Pinned(app, retained(current, before, seats))

    others = tuple(window for window, owner in zip(observed, owners, strict=True) if owner is None)
    return Shelf(tuple(slot(app) for app in PinnedApp), applications(others, previous.running, seats))


def launch(pending: Launches, app: PinnedApp, now: float) -> Launches | None:
    """The pending launches after launching `app` now; None while an earlier launch may still open its window."""
    if pending.get(app, now) > now:
        return None
    return pending | {app: now + LAUNCH_GRACE}


def outstanding(pending: Launches, current: Shelf) -> Launches:
    """A launch whose window has appeared is no longer pending, so reopening after closing it launches again."""
    return frozendict((app, due) for app, due in pending.items() if all(slot.app is not app or not slot.windows for slot in current.pinned))


def caption_clip(outer: Rect, caption: Rect, region: Rect | None) -> Rect | None:
    """The window region hiding a slot window's caption, which Edge paints inside its client
    area; None when the current region already does. Regions don't follow resizing."""
    wanted = Rect(0, caption.bottom, outer.width, outer.height)
    return None if wanted == region else wanted


def next_window(handles: Sequence[int], foreground: int) -> int:
    """The window after the one in front, or the first: repeated presses visit them all."""
    return handles[(handles.index(foreground) + 1) % len(handles)] if foreground in handles else handles[0]
