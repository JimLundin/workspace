"""Immediate native work projection while the Teams effect worker is occupied."""

from dataclasses import dataclass, field, replace

from assistant.communications import (
    MAX_HANDLED,
    Acknowledgement,
    Command,
    Feed,
    Handle,
    HandleNotice,
    NotificationFilters,
    Reopen,
    Update,
    WindowsNotice,
    handle,
    notice_update,
    notices_observed,
    reopen,
    update_fingerprint,
    updates_observed,
)
from assistant.system_notices import Notice, NoticeKey, Observed


@dataclass(frozen=True, slots=True)
class NativeFeed:
    feed: Feed = field(default_factory=Feed)
    reopened: tuple[tuple[str, str], ...] = ()
    muted: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class Changed:
    state: NativeFeed
    dismiss: tuple[NoticeKey, ...] = ()


def observed(state: NativeFeed, observation: Observed) -> NativeFeed:
    return replace(state, feed=notices_observed(state.feed, observation))


def project(state: NativeFeed, feed: Feed) -> Feed:
    result = updates_observed(feed, state.feed.updates)
    result = handle(result, state.feed.handled)
    for key in state.reopened:
        result = reopen(result, key)
    return replace(result, muted_apps=state.muted if state.muted is not None else result.muted_apps,
                   notice_detail=state.feed.notice_detail or result.notice_detail)


def captured(feed: Feed, marks: tuple[Acknowledgement, ...]) -> tuple[Update, ...]:
    return tuple(update for update in feed.updates if isinstance(update.source, WindowsNotice)
                 and Acknowledgement(update.key, update_fingerprint(update)) in marks)


def forward(feed: Feed, command: Command) -> tuple[Command, ...]:
    """Queue captured notices, so later collection cannot erase a handling target."""
    if not isinstance(command, Handle):
        return (command,)
    native = captured(feed, command.marks)
    keys = {update.key for update in native}
    remaining = tuple(mark for mark in command.marks if mark.key not in keys)
    commands: list[Command] = [Handle(remaining)] if remaining else []
    for update in native:
        if isinstance(update.source, WindowsNotice):
            commands.append(HandleNotice(Notice(update.source.key, update.source.app_id, update.app_name, update.title, update.text)))
    return tuple(commands)


def acted(state: NativeFeed, feed: Feed, command: Command) -> Changed:
    match command:
        case Handle(marks):
            native = captured(feed, marks)
        case HandleNotice(notice):
            native = (notice_update(notice),)
        case Reopen(key) if any(update.key == key and isinstance(update.source, WindowsNotice) for update in feed.updates):
            return Changed(replace(state, feed=reopen(state.feed, key),
                                   reopened=(*state.reopened, key)[-MAX_HANDLED:]))
        case NotificationFilters(apps):
            return Changed(replace(state, muted=apps))
        case _:
            return Changed(state)
    keys = {update.key for update in native}
    updated = updates_observed(state.feed, native)
    updated = handle(updated, tuple(Acknowledgement(update.key, update_fingerprint(update)) for update in native))
    return Changed(replace(state, feed=updated, reopened=tuple(key for key in state.reopened if key not in keys)),
                   tuple(update.source.key for update in native if isinstance(update.source, WindowsNotice)))
