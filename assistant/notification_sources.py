"""Windows notices, their handling marks and the notification filter, owned beside the bar that observes them."""

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Annotated

from pydantic import Field, StringConstraints, TypeAdapter

from assistant.communications import (
    MAX_HANDLED,
    MAX_MESSAGES,
    Acknowledgement,
    Feed,
    NotificationFilter,
    Update,
    WindowsNotice,
    update_fingerprint,
    update_order,
)
from assistant.communications_state import StoredAcknowledgement
from assistant.state_store import SavedState
from winapi.system_notices import Notice, NoticeKey, Observed

MAX_HIDDEN_APPS = 256

type AppId = Annotated[str, StringConstraints(min_length=1, max_length=512)]


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


@dataclass(frozen=True, slots=True)
class HandleNotice:
    notice: Notice


@dataclass(frozen=True, slots=True)
class ReopenNotice:
    key: tuple[str, str]


@dataclass(frozen=True, slots=True)
class OpenApp:
    app_id: str


@dataclass(frozen=True, slots=True)
class ToggleApp:
    app_id: str


type Command = HandleNotice | ReopenNotice | OpenApp | ToggleApp


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


def handled(state: Notices, notice: Notice) -> Notices:
    """Handle only the captured revision; a notice Windows revised after it rendered stays pending."""
    captured = notice_update(notice)
    current = next((update for update in state.updates if update.key == captured.key), None)
    if current is None:
        state = merged(state, (captured,))
    elif update_fingerprint(current) != update_fingerprint(captured):
        return state
    retained = tuple(mark for mark in state.handled if mark.key != captured.key)
    return replace(state, handled=(*retained, Acknowledgement(captured.key, update_fingerprint(captured)))[-MAX_HANDLED:])


def reopened(state: Notices, key: tuple[str, str]) -> Notices:
    return replace(state, handled=tuple(mark for mark in state.handled if mark.key != key))


def filtered(state: Notices, app_id: str) -> Notices:
    if not app_id or len(app_id) > 512 or (app_id not in state.filter.hidden and len(state.filter.hidden) >= MAX_HIDDEN_APPS):
        return state
    return replace(state, filter=state.filter.toggled(app_id))


def joined(feed: Feed, notices: Notices) -> Feed:
    """The pending feed every consumer reads: Teams work plus Windows notices under one filter."""
    return replace(
        feed,
        updates=tuple(sorted((*feed.updates, *notices.updates), key=update_order)),
        handled=(*feed.handled, *notices.handled),
        notification_filter=notices.filter,
    )


class NotificationSources:
    """Qt's thread owns notices, so handling never waits behind a Teams navigation."""

    __slots__ = ("dismiss", "state", "store")

    def __init__(self, store: SavedState[NotificationState], dismiss: Callable[[NoticeKey], None]) -> None:
        self.store, self.dismiss = store, dismiss
        self.state = Notices()

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

    def commit(self, state: Notices) -> bool:
        """Publish a choice only after it is saved, so a restart cannot re-alert handled work."""
        if state.handled != self.state.handled or state.filter != self.state.filter:
            try:
                self.store.write(
                    NotificationState(
                        tuple(sorted(state.filter.hidden)),
                        tuple(StoredAcknowledgement(mark.key[0], mark.key[1], mark.fingerprint) for mark in state.handled),
                    )
                )
            except OSError:
                return False
        self.state = state
        return True

    def command(self, command: Command) -> bool:
        match command:
            case HandleNotice(notice):
                after = handled(self.state, notice)
                captured = notice_update(notice)
                if Acknowledgement(captured.key, update_fingerprint(captured)) not in after.handled or not self.commit(after):
                    return False
                self.dismiss(notice.key)
                return True
            case ReopenNotice(key):
                return self.commit(reopened(self.state, key))
            case ToggleApp(app_id):
                return self.commit(filtered(self.state, app_id))
            case OpenApp(app_id):
                os.startfile("shell:AppsFolder\\" + app_id)
                return True
