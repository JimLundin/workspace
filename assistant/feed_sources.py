"""Feed sources: each variant owns its key, origin, pending rule and triage evidence.

The pending feed retains each observer's latest report and derives one listing.
Routine arrivals stay quiet: triage assesses pending work, never a floating card.
"""

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from itertools import chain
from typing import Final, assert_never

from pydantic import TypeAdapter

from assistant.communications import (
    ChatTicket,
    Conversation,
    Delivery,
    Feed,
    Message,
    Reply,
    SourceDate,
    SourceDateStatus,
    SourceTime,
    TeamsActivity,
    Update,
    UpdateKind,
    WindowsNotice,
    chat_tickets,
    update_fingerprint,
    update_order,
)
from assistant.notification_sources import Notices
from contracts.feed_origin import App, Origin, application
from contracts.members import every_member

_CHAT_KEY = TypeAdapter(tuple[str, str])
_TEAMS = Origin(App.TEAMS, App.TEAMS.value)


@dataclass(frozen=True, slots=True)
class PendingFeed:
    """Each observer's latest report; consumers list sources from it, never from one observer."""

    teams: Feed = field(default_factory=Feed)
    notices: Notices = field(default_factory=Notices)


@dataclass(frozen=True, slots=True)
class TeamsObserved:
    feed: Feed


@dataclass(frozen=True, slots=True)
class NoticesObserved:
    notices: Notices


type FeedUpdate = TeamsObserved | NoticesObserved


def observe(feed: PendingFeed, update: FeedUpdate) -> PendingFeed:
    match update:
        case TeamsObserved(feed=teams):
            return replace(feed, teams=teams)
        case NoticesObserved(notices=notices):
            return replace(feed, notices=notices)
        case _:
            assert_never(update)


def needs_attention(feed: PendingFeed, update: Update) -> bool:
    """Unhandled at this revision and not hidden by the notices' filter."""
    key, revision = update.key, update_fingerprint(update)
    return not any(
        mark.key == key and mark.fingerprint == revision for mark in chain(feed.teams.handled, feed.notices.handled)
    ) and not feed.notices.filter.hides(update)


class SourceKind(Enum):
    """The prefix of triage evidence identities."""

    CHAT = "chat"
    ACTIVITY = "activity"
    WINDOWS = "windows"
    REPLY = "reply"


@dataclass(frozen=True, slots=True)
class SourceKey:
    kind: SourceKind
    identity: str


@dataclass(frozen=True, slots=True)
class ChatTicketSource:
    """A followed chat's unseen messages, handled together."""

    ticket: ChatTicket
    chat: Conversation | None


@dataclass(frozen=True, slots=True)
class UpdateSource:
    """A pending Teams activity or Windows notice; `Update.source` already names which."""

    update: Update


@dataclass(frozen=True, slots=True)
class ReplySource:
    reply: Reply


type FeedSource = ChatTicketSource | UpdateSource | ReplySource


class Attention(Enum):
    """The one pending rule. The feed keeps every unresolved source visible; triage assesses only TRIAGE."""

    # Unresolved work the triage agent can group, rank or keep quiet.
    TRIAGE = auto()
    # A send still in flight: visible while it resolves, not yet work to assess.
    SETTLING = auto()
    RESOLVED = auto()


@dataclass(frozen=True, slots=True)
class Candidate:
    """A source revision quoted to triage as evidence, never as instructions."""

    identity: str
    revision: str
    kind: SourceKind
    origin: Origin
    title: str
    body: str
    created_at: float
    reaction: bool = field(default=False, kw_only=True)
    source_time: SourceTime = field(default=SourceDateStatus.UNKNOWN, kw_only=True)


@dataclass(frozen=True, slots=True)
class Excerpt:
    title: str
    body: str
    created_at: float


def attention(source: FeedSource) -> Attention:
    match source:
        case ChatTicketSource() | UpdateSource():
            return Attention.TRIAGE
        case ReplySource(reply=reply):
            return _delivery(reply.delivery)
        case _:
            assert_never(source)


DELIVERY_ATTENTION: Final = every_member(
    Delivery,
    {
        Delivery.UNKNOWN: Attention.TRIAGE,
        Delivery.FAILED: Attention.TRIAGE,
        Delivery.QUEUED: Attention.SETTLING,
        Delivery.SENDING: Attention.SETTLING,
        Delivery.OBSERVED: Attention.RESOLVED,
        Delivery.REVIEWED: Attention.RESOLVED,
    },
)
"""How much attention a message needs, by its delivery state."""


def _delivery(delivery: Delivery) -> Attention:
    return DELIVERY_ATTENTION[delivery]


def key(source: FeedSource) -> SourceKey:
    """The source's identity in the pending listing and its triage evidence."""
    match source:
        case ChatTicketSource(ticket=ticket):
            return SourceKey(SourceKind.CHAT, ticket.conversation)
        case UpdateSource(update=update):
            return _update_key(update)
        case ReplySource(reply=reply):
            return SourceKey(SourceKind.REPLY, reply.identity)
        case _:
            assert_never(source)


def _update_key(update: Update) -> SourceKey:
    _, identity = update.key
    match update.source:
        case TeamsActivity():
            return SourceKey(SourceKind.ACTIVITY, identity)
        case WindowsNotice():
            return SourceKey(SourceKind.WINDOWS, identity)


def origin(source: FeedSource) -> Origin:
    match source:
        case ChatTicketSource() | ReplySource():
            return _TEAMS
        case UpdateSource(update=update):
            match update.source:
                case TeamsActivity():
                    return _TEAMS
                case WindowsNotice(app_id=app_id):
                    return application(update.app_name, app_id)
        case _:
            assert_never(source)


def title(source: FeedSource) -> str:
    match source:
        case ChatTicketSource(chat=chat):
            return chat.title if chat is not None else "Teams"
        case UpdateSource(update=update):
            return update.app_name
        case ReplySource(reply=reply):
            return reply.title
        case _:
            assert_never(source)


def evidence(source: FeedSource) -> tuple[Candidate, ...]:
    """Quote only TRIAGE sources; in-flight sends and resolved sources are never assessed."""
    if attention(source) is not Attention.TRIAGE:
        return ()
    match source:
        case ChatTicketSource(ticket=ticket, chat=chat):
            return tuple(_message_evidence(message, chat) for message in ticket.messages)
        case UpdateSource(update=update):
            excerpt = Excerpt(update.app_name + ": " + update.title, update.text, update.created_at)
            captured = replace(_captured(_update_key(update), origin(source), excerpt), reaction=update.kind is UpdateKind.REACTION)
            match update.source:
                case TeamsActivity():
                    # Activity ordering keeps first observation apart from the provider's own date.
                    return (replace(captured, source_time=update.source_time),)
                case WindowsNotice():
                    return (captured,)
        case ReplySource(reply=reply):
            excerpt = Excerpt("Reply to " + reply.title, reply.detail, reply.created_at)
            return (_captured(key(source), origin(source), excerpt),)
        case _:
            assert_never(source)


def _message_key(message: Message) -> SourceKey:
    # Triage identities predate the rendered message key; the JSON pair stays unambiguous.
    return SourceKey(SourceKind.CHAT, _CHAT_KEY.dump_json(message.key).decode())


def _message_evidence(message: Message, chat: Conversation | None) -> Candidate:
    excerpt = Excerpt((chat.title if chat is not None else "Chat") + " · " + message.sender, message.text, message.created_at)
    return _captured(_message_key(message), _TEAMS, excerpt)


def _identity(source: SourceKey) -> str:
    return source.kind.value + ":" + hashlib.sha256(source.identity.encode()).hexdigest()[:24]


def _captured(source: SourceKey, at: Origin, excerpt: Excerpt) -> Candidate:
    return Candidate(
        _identity(source),
        hashlib.sha256((excerpt.title + "\n" + excerpt.body).encode()).hexdigest(),
        source.kind,
        at,
        excerpt.title[:512],
        excerpt.body[:6000],
        excerpt.created_at,
        source_time=SourceDate(excerpt.created_at) if excerpt.created_at > 0 else SourceDateStatus.UNKNOWN,
    )


def listed(feed: PendingFeed) -> Iterator[FeedSource]:
    """The feed's pending sources in display order.

    Filtered notices stay out of pending work without being handled. Replies remain
    listed after delivery, so the person sees each outcome before it retires.
    """
    for ticket in chat_tickets(feed.teams):
        yield ChatTicketSource(ticket, feed.teams.conversation(ticket.conversation))
    for update in sorted(chain(feed.teams.updates, feed.notices.updates), key=update_order):
        if needs_attention(feed, update):
            yield UpdateSource(update)
    yield from map(ReplySource, feed.teams.replies)


def triage_evidence(feed: PendingFeed) -> tuple[Candidate, ...]:
    return tuple(chain.from_iterable(map(evidence, listed(feed))))


def chat_message(feed: Feed, identity: str) -> Message | None:
    """The captured message a chat evidence identity names, seen or not."""
    return next((message for message in feed.messages if _identity(_message_key(message)) == identity), None)
