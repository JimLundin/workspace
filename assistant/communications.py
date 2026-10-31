"""Immutable communication observations, local acknowledgement and reply evidence."""

import hashlib
from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum, auto
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
    kind: Literal["chat", "meeting"] = "chat"


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


class UpdateKind(Enum):
    REACTION = auto()
    INVITATION = auto()
    MENTION = auto()
    UPDATE = auto()


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
    kind: UpdateKind = UpdateKind.UPDATE
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
class NotificationFilter:
    """Windows apps the person keeps out of pending work; hiding never handles their notices."""

    hidden: frozenset[str] = frozenset()

    def hides(self, update: Update) -> bool:
        match update.source:
            case WindowsNotice(_, app_id):
                return app_id in self.hidden
            case TeamsActivity():
                return False

    def toggled(self, app_id: str) -> NotificationFilter:
        return NotificationFilter(self.hidden ^ {app_id})


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
    notification_filter: NotificationFilter = field(default_factory=NotificationFilter)

    def conversation(self, identity: str) -> Conversation | None:
        return next((chat for chat in self.conversations if chat.identity == identity), None)

    def unseen(self, message: Message) -> bool:
        return not message.own and not any(
            mark.key == message.key and mark.fingerprint == fingerprint(message.text) for mark in (*self.acknowledged, *self.handled)
        )

    def pending_update(self, update: Update) -> bool:
        key, revision = update.key, update_fingerprint(update)
        return not any(mark.key == key and mark.fingerprint == revision for mark in self.handled)

    def needs_attention(self, update: Update) -> bool:
        """The one pending-work test for updates: unhandled and not hidden by the notification filter."""
        return self.pending_update(update) and not self.notification_filter.hides(update)

    @property
    def unseen_chats(self) -> int:
        return len({message.conversation for message in self.messages if self.unseen(message)})


def message_order(message: Message) -> tuple[float, str]:
    return message.created_at, message.identity


def observed(feed: Feed, messages: tuple[Message, ...], at: float) -> Feed:
    """Stable source keys update an existing entry; reactions do not re-alert it."""
    merged = {message.key: message for message in feed.messages}
    for message in messages:
        previous = merged.get(message.key)
        merged[message.key] = replace(message, observed_at=previous.observed_at, own=message.own or previous.own) if previous is not None else message
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
    merged = {item.key: item for item in feed.updates}
    for item in updates:
        previous = merged.get(item.key)
        merged[item.key] = replace(item, created_at=previous.created_at) if previous is not None else item
    return replace(feed, updates=tuple(sorted(merged.values(), key=update_order)[-MAX_MESSAGES:]))


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
    chats: dict[str, list[Message]] = {}
    for message in sorted(feed.messages, key=message_order):
        if message.conversation in feed.followed and feed.unseen(message):
            chats.setdefault(message.conversation, []).append(message)
    return tuple(ChatTicket(identity, tuple(messages)) for identity, messages in chats.items())


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
