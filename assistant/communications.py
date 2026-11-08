"""Immutable communication observations, local acknowledgement and reply evidence."""

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum, StrEnum, auto
from itertools import groupby
from typing import Literal

from winapi.system_notices import NoticeKey

MAX_MESSAGES = 300
MAX_FOLLOWED = 8
MAX_HANDLED = 2000


class Status(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    PAUSED = auto()
    STALE = auto()


@dataclass(frozen=True, slots=True)
class Conversation:
    identity: str
    title: str

    @property
    def meeting(self) -> bool:
        """A meeting's chat, which Teams names by its meeting."""
        return "meeting_" in self.identity


@dataclass(frozen=True, slots=True)
class Message:
    conversation: str
    identity: str
    sender: str
    text: str
    created_at: float
    observed_at: float
    reactions: tuple[str, ...] = ()
    own: bool = field(default=False, kw_only=True)

    @property
    def key(self) -> tuple[str, str]:
        return self.conversation, self.identity


class Delivery(Enum):
    QUEUED = auto()
    SENDING = auto()
    OBSERVED = auto()
    UNKNOWN = auto()
    REVIEWED = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class Reply:
    identity: str
    conversation: str
    title: str
    text: str
    created_at: float
    delivery: Delivery = Delivery.QUEUED
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Acknowledgement:
    key: tuple[str, str]
    fingerprint: str


class Activity(StrEnum):
    """What a Teams activity reports."""

    REACTION = "reaction"
    INVITATION = "invitation"
    MENTION = "mention"
    UPDATE = "update"


@dataclass(frozen=True, slots=True)
class SourceDate:
    at: float


@dataclass(frozen=True, slots=True)
class SourceDateHint:
    label: str
    observed_on: date


class SourceDateStatus(Enum):
    UNKNOWN = "unknown"


type SourceTime = SourceDate | SourceDateHint | SourceDateStatus


@dataclass(frozen=True, slots=True)
class TeamsActivity:
    identity: str
    activity: Activity = Activity.UPDATE


@dataclass(frozen=True, slots=True)
class WindowsNotice:
    key: NoticeKey
    app_id: str


type UpdateSource = TeamsActivity | WindowsNotice


@dataclass(frozen=True, slots=True)
class Update:
    source: UpdateSource
    title: str
    text: str
    app_name: str
    created_at: float
    # Activity ordering keeps first observation separate from the provider's date.
    source_time: SourceTime = field(default=SourceDateStatus.UNKNOWN, kw_only=True)

    @property
    def key(self) -> tuple[str, str]:
        match self.source:
            case TeamsActivity(identity):
                return "activity", identity
            case WindowsNotice(key, _):
                return "windows", f"{key.identity}:{key.created}"


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def update_fingerprint(update: Update) -> str:
    return fingerprint(update.title + "\n" + update.text)


@dataclass(frozen=True, slots=True)
class UnavailableChat:
    conversation: str
    reason: Literal["missing", "loading"]


@dataclass(frozen=True, slots=True)
class Feed:
    status: Status = Status.DISCONNECTED
    detail: str = "Connect Teams to bring chat updates into this conversation."
    conversations: tuple[Conversation, ...] = ()
    followed: tuple[str, ...] = ()
    messages: tuple[Message, ...] = ()
    replies: tuple[Reply, ...] = ()
    acknowledged: tuple[Acknowledgement, ...] = ()
    unavailable: tuple[UnavailableChat, ...] = ()
    checked_at: float = 0
    updates: tuple[Update, ...] = ()
    handled: tuple[Acknowledgement, ...] = ()
    activity_detail: str = ""

    def conversation(self, identity: str) -> Conversation | None:
        return next((chat for chat in self.conversations if chat.identity == identity), None)

    def unseen(self, message: Message) -> bool:
        return not message.own and not any(
            mark.key == message.key and mark.fingerprint == fingerprint(message.text) for mark in (*self.acknowledged, *self.handled)
        )


def message_order(message: Message) -> tuple[float, str]:
    return message.created_at, message.identity


def grouped[K, V](items: Iterable[V], key: Callable[[V], K]) -> frozendict[K, tuple[V, ...]]:
    """Items by key, keys in first-appearance order and each group in its original order."""
    ordered = tuple(items)
    rank = {name: position for position, name in enumerate(dict.fromkeys(map(key, ordered)))}
    return frozendict((name, tuple(group)) for name, group in groupby(sorted(ordered, key=lambda item: rank[key(item)]), key=key))


def message_key(message: Message) -> tuple[str, str]:
    return message.key


def _merged_message(previous: Message | None, revisions: tuple[Message, ...]) -> Message:
    """The latest revision keeps the first observation time and stays own once any revision was."""
    first = previous if previous is not None else revisions[0]
    return replace(revisions[-1], observed_at=first.observed_at, own=first.own or any(message.own for message in revisions))


def observed(feed: Feed, messages: tuple[Message, ...], at: float) -> Feed:
    """Stable source keys update an existing entry; reactions do not re-alert it."""
    known = {message.key: message for message in feed.messages}
    arrived = {key: _merged_message(known.get(key), revisions) for key, revisions in grouped(messages, message_key).items()}
    merged = {**known, **arrived}
    retained = tuple(sorted(merged.values(), key=message_order)[-MAX_MESSAGES:])
    keys = {message.key for message in retained}
    return replace(feed, messages=retained, checked_at=at, acknowledged=tuple(mark for mark in feed.acknowledged if mark.key in keys))


def acknowledge(feed: Feed, key: tuple[str, str]) -> Feed:
    message = next((item for item in feed.messages if item.key == key), None)
    if message is None:
        return feed
    return replace(feed, acknowledged=(*(mark for mark in feed.acknowledged if mark.key != key), Acknowledgement(key, fingerprint(message.text))))


def handle(feed: Feed, marks: tuple[Acknowledgement, ...]) -> Feed:
    """Handle only captured revisions; arrivals during a click remain pending."""
    current = {message.key: fingerprint(message.text) for message in feed.messages}
    current.update({update.key: update_fingerprint(update) for update in feed.updates})
    accepted = {mark.key: mark for mark in marks if current.get(mark.key) == mark.fingerprint}
    retained = tuple(mark for mark in feed.handled if mark.key not in accepted)
    return replace(feed, handled=(*retained, *accepted.values())[-MAX_HANDLED:])


def reopen(feed: Feed, key: tuple[str, str]) -> Feed:
    return replace(
        feed,
        handled=tuple(mark for mark in feed.handled if mark.key != key),
        acknowledged=tuple(mark for mark in feed.acknowledged if mark.key != key),
    )


def updates_observed(feed: Feed, updates: tuple[Update, ...]) -> Feed:
    known = {item.key: item for item in feed.updates}
    arrived = {
        key: replace(revisions[-1], created_at=_first_update(known.get(key), revisions).created_at)
        for key, revisions in grouped(updates, update_key).items()
    }
    merged = {**known, **arrived}
    return replace(feed, updates=tuple(sorted(merged.values(), key=update_order)[-MAX_MESSAGES:]))


def _first_update(previous: Update | None, revisions: tuple[Update, ...]) -> Update:
    return previous if previous is not None else revisions[0]


def update_key(update: Update) -> tuple[str, str]:
    return update.key


def update_order(update: Update) -> float:
    return update.created_at


@dataclass(frozen=True, slots=True)
class ChatTicket:
    conversation: str
    messages: tuple[Message, ...]

    @property
    def latest(self) -> Message:
        return self.messages[-1]


def chat_tickets(feed: Feed) -> tuple[ChatTicket, ...]:
    pending = (message for message in sorted(feed.messages, key=message_order) if message.conversation in feed.followed and feed.unseen(message))
    return tuple(ChatTicket(identity, messages) for identity, messages in grouped(pending, message_conversation).items())


def message_conversation(message: Message) -> str:
    return message.conversation


def reply_changed(feed: Feed, reply: Reply) -> Feed:
    replies = tuple(item for item in feed.replies if item.identity != reply.identity)
    return replace(feed, replies=(*replies, reply)[-50:])


@dataclass(frozen=True, slots=True)
class Connect:
    pass


@dataclass(frozen=True, slots=True)
class Disconnect:
    pass


@dataclass(frozen=True, slots=True)
class Refresh:
    pass


@dataclass(frozen=True, slots=True)
class Follow:
    conversations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Seen:
    key: tuple[str, str]


@dataclass(frozen=True, slots=True)
class Send:
    conversation: str
    text: str
    identity: str
    handling: tuple[Acknowledgement, ...] = ()


@dataclass(frozen=True, slots=True)
class SaveDraft:
    conversation: str
    text: str


@dataclass(frozen=True, slots=True)
class OpenChat:
    conversation: str


@dataclass(frozen=True, slots=True)
class ResolveAttempt:
    identity: str


@dataclass(frozen=True, slots=True)
class Handle:
    marks: tuple[Acknowledgement, ...]


@dataclass(frozen=True, slots=True)
class Reopen:
    key: tuple[str, str]


@dataclass(frozen=True, slots=True)
class OpenUpdate:
    key: tuple[str, str]


type Command = Connect | Disconnect | Refresh | Follow | Seen | Send | SaveDraft | OpenChat | ResolveAttempt | Handle | Reopen | OpenUpdate
