"""Windows notices, their handling marks and the notification filter, owned beside the bar that observes them."""

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Annotated

from pydantic import Field, StringConstraints, TypeAdapter

from assistant.communications import (
    MAX_HANDLED,
    MAX_MESSAGES,
    Acknowledgement,
    TeamsActivity,
    Update,
    WindowsNotice,
    update_order,
)
from assistant.communications_state import StoredAcknowledgement
from assistant.state_store import SavedState
from winapi.system_notices import Notice, Observed

MAX_HIDDEN_APPS = 256

type AppId = Annotated[str, StringConstraints(min_length=1, max_length=512)]


@dataclass(frozen=True, slots=True)
class NotificationFilter:
    """Windows apps the person keeps out of pending work; hiding never handles their notices."""

    hidden: frozenset[str] = frozenset()

    def hides(self, update: Update) -> bool:
        match update.source:
            case WindowsNotice(_, app_id):
                return app_id in self.hidden
            case TeamsActivity():
                return False


@dataclass(frozen=True, slots=True)
class NotificationState:
    hidden_apps: Annotated[tuple[AppId, ...], Field(max_length=MAX_HIDDEN_APPS)] = ()
    handled: Annotated[tuple[StoredAcknowledgement, ...], Field(max_length=MAX_HANDLED)] = ()


NOTIFICATION_STATE = TypeAdapter(NotificationState)


@dataclass(frozen=True, slots=True)
class Notices:
    updates: tuple[Update, ...] = ()
    handled: tuple[Acknowledgement, ...] = ()
    filter: NotificationFilter = field(default_factory=NotificationFilter)


def notice_update(notice: Notice) -> Update:
    return Update(
        WindowsNotice(notice.key, notice.app_id), notice.title, notice.body, notice.app_name, (notice.key.created / 10_000_000) - 11_644_473_600
    )


def merged(state: Notices, updates: Iterable[Update]) -> Notices:
    known = {update.key: update for update in state.updates}
    known.update({update.key: update for update in updates})
    return replace(state, updates=tuple(sorted(known.values(), key=update_order)[-MAX_MESSAGES:]))


def observed(state: Notices, observation: Observed) -> Notices:
    # Windows retains delivery and dismissal ownership. An unavailable read never removes history.
    return merged(state, (notice_update(notice) for notice in observation.notices))


class NotificationSources:
    """Qt's thread owns the latest immutable notices and their loaded attention choices."""

    __slots__ = ("state", "store")

    def __init__(self, store: SavedState[NotificationState]) -> None:
        self.store: SavedState[NotificationState] = store
        self.state: Notices = Notices()

    def load(self) -> None:
        try:
            saved = self.store.read()
        except OSError, ValueError:
            # Unreadable choices start empty: notices re-alert rather than stopping startup.
            return
        self.state = Notices(
            handled=tuple(Acknowledgement((mark.source, mark.identity), mark.fingerprint) for mark in saved.handled),
            filter=NotificationFilter(frozenset(saved.hidden_apps)),
        )

    def observe(self, observation: Observed) -> bool:
        before, self.state = self.state, observed(self.state, observation)
        return self.state != before
