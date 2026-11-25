from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

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
    """Edge's AppUserModelID for its `--app` window on the profile the apps open in; another profile's differs."""
    glyph: str


type WebApps = frozendict[PinnedApp, WebApp]

LAUNCH_GRACE: Final = 15.0
"""Seconds a started app's new window has to appear before the launch is forgotten."""

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
    desktop: int
    left: int
    top: int


type Seats = Mapping[int, Seat]
"""Newly seen windows' seats, by handle; a minimized window or one on no known desktop has none."""


def retained(
    current: Sequence[Window], before: Sequence[Window], seats: Seats
) -> tuple[Window, ...]:
    by_handle = frozendict((window.handle, window) for window in current)
    kept = tuple(
        window.handle for window in before if window.handle in by_handle
    )
    new = tuple(window for window in current if window.handle not in kept)
    seated = sorted(
        (window for window in new if window.handle in seats),
        key=lambda window: seats[window.handle],
    )
    return (
        *(by_handle[handle] for handle in kept),
        *seated,
        *(window for window in new if window.handle not in seats),
    )


def applications(
    observed: Sequence[Window], previous: tuple[Application, ...], seats: Seats
) -> tuple[Application, ...]:
    identities = tuple(
        dict.fromkeys(
            (window.exe or str(window.handle) for window in observed), 0
        )
    )
    order = tuple(
        app.identity for app in previous if app.identity in identities
    )
    order = (
        *order,
        *(identity for identity in identities if identity not in order),
    )

    def grouped(identity: str) -> Application:
        current = tuple(
            window
            for window in observed
            if (window.exe or str(window.handle)) == identity
        )
        before = next(
            (app for app in previous if app.identity == identity), None
        )
        if before is None:
            return Application(identity, retained(current, (), seats))
        return Application(
            identity, retained(current, before.windows, seats), before.image
        )

    return tuple(grouped(identity) for identity in order)


def pinned_app(app_id: str | None, web_apps: WebApps) -> PinnedApp | None:
    if app_id is None:
        return None
    return next(
        (app for app, web in web_apps.items() if app_id == web.app_id), None
    )


def not_kept_away(
    observed: Iterable[Window],
    app_ids: Mapping[int, str | None],
    kept_away: frozenset[str],
) -> Iterator[Window]:
    return (
        window
        for window in observed
        if app_ids.get(window.handle) not in kept_away
    )


def shelf(
    observed: Sequence[Window],
    app_ids: Mapping[int, str | None],
    previous: Shelf,
    seats: Seats,
    web_apps: WebApps,
) -> Shelf:
    owners = tuple(
        pinned_app(app_ids.get(window.handle), web_apps) for window in observed
    )

    def slot(app: PinnedApp) -> Pinned:
        current = tuple(
            window
            for window, owner in zip(observed, owners, strict=True)
            if owner is app
        )
        before = next(
            (pinned.windows for pinned in previous.pinned if pinned.app is app),
            (),
        )
        return Pinned(app, retained(current, before, seats))

    others = tuple(
        window
        for window, owner in zip(observed, owners, strict=True)
        if owner is None
    )
    return Shelf(
        tuple(slot(app) for app in web_apps),
        applications(others, previous.running, seats),
    )


def launch(
    pending: Launches, app: PinnedApp, now: float, grace: float
) -> Launches | None:
    if pending.get(app, now) > now:
        return None
    return pending | {app: now + grace}


def outstanding(pending: Launches, current: Shelf) -> Launches:
    return frozendict(
        (app, due)
        for app, due in pending.items()
        if all(
            slot.app is not app or not slot.windows for slot in current.pinned
        )
    )


def caption_clip(
    outer: Rect, caption: Rect, region: Rect | None
) -> Rect | None:
    wanted = Rect(0, caption.bottom, outer.width, outer.height)
    return None if wanted == region else wanted


def next_window(handles: Sequence[int], foreground: int) -> int:
    return (
        handles[(handles.index(foreground) + 1) % len(handles)]
        if foreground in handles
        else handles[0]
    )
