"""Feed sources: each variant owns its key, origin, pending rule and triage evidence."""

import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from itertools import chain
from typing import assert_never

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
)
from assistant.console_requests import Request, State
from assistant.feed_origin import App, Origin, application

_CHAT_KEY = TypeAdapter(tuple[str, str])
_TEAMS = Origin(App.TEAMS, App.TEAMS.value)


class SourceKind(Enum):
    """Wire names for rendered links and the prefix of triage evidence identities."""

    CHAT = "chat"
    CHAT_MESSAGE = "chat-message"
    ACTIVITY = "activity"
    WINDOWS = "windows"
    REPLY = "reply"
    CONSOLE = "console"
    # A triage proposal groups sources; its rendered row needs a key of its own.
    PROPOSAL = "triage"


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
class ChatMessageSource:
    """One captured message in history, seen or not."""

    message: Message
    chat: Conversation | None
    unseen: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class UpdateSource:
    """A Teams activity or Windows notice; `Update.source` already names which."""

    update: Update
    handled: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class ReplySource:
    reply: Reply


@dataclass(frozen=True, slots=True)
class ConsoleSource:
    request: Request


type FeedSource = ChatTicketSource | ChatMessageSource | UpdateSource | ReplySource | ConsoleSource


class Attention(Enum):
    """The one pending rule. The feed keeps every unresolved source visible; triage assesses only TRIAGE."""

    # Unresolved work the triage agent can group, rank or keep quiet.
    TRIAGE = auto()
    # A console question or approval the person answers exactly; triage never hides it.
    DIRECT = auto()
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
        case ChatTicketSource():
            return Attention.TRIAGE
        case ChatMessageSource(unseen=unseen):
            return Attention.TRIAGE if unseen else Attention.RESOLVED
        case UpdateSource(handled=handled):
            return Attention.RESOLVED if handled else Attention.TRIAGE
        case ReplySource(reply=reply):
            return _delivery(reply.delivery)
        case ConsoleSource(request=request):
            return _console(request.state)
        case _:
            assert_never(source)


def _delivery(delivery: Delivery) -> Attention:
    match delivery:
        case Delivery.UNKNOWN | Delivery.FAILED:
            return Attention.TRIAGE
        case Delivery.QUEUED | Delivery.SENDING:
            return Attention.SETTLING
        case Delivery.OBSERVED | Delivery.REVIEWED:
            return Attention.RESOLVED
        case _:
            assert_never(delivery)


def _console(state: State) -> Attention:
    match state:
        case State.WAITING:
            return Attention.DIRECT
        case State.INFORMATION:
            return Attention.TRIAGE
        case State.ANSWERED | State.EXPIRED:
            return Attention.RESOLVED
        case _:
            assert_never(state)


def key(source: FeedSource) -> SourceKey:
    """The rendered row's identity; a click names it to act on what the person saw."""
    match source:
        case ChatTicketSource(ticket=ticket):
            return SourceKey(SourceKind.CHAT, ticket.conversation)
        case ChatMessageSource(message=message):
            return SourceKey(SourceKind.CHAT_MESSAGE, message.conversation + "/" + message.identity)
        case UpdateSource(update=update):
            return _update_key(update)
        case ReplySource(reply=reply):
            return SourceKey(SourceKind.REPLY, reply.identity)
        case ConsoleSource(request=request):
            return SourceKey(SourceKind.CONSOLE, request.identity)
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
        case ChatTicketSource() | ChatMessageSource() | ReplySource():
            return _TEAMS
        case UpdateSource(update=update):
            match update.source:
                case TeamsActivity():
                    return _TEAMS
                case WindowsNotice(app_id=app_id):
                    return application(update.app_name, app_id)
        case ConsoleSource(request=request):
            return application(request.provider.value)
        case _:
            assert_never(source)


def title(source: FeedSource) -> str:
    match source:
        case ChatTicketSource(chat=chat) | ChatMessageSource(chat=chat):
            return chat.title if chat is not None else "Teams"
        case UpdateSource(update=update):
            return update.app_name
        case ReplySource(reply=reply):
            return reply.title
        case ConsoleSource(request=request):
            return request.provider.value
        case _:
            assert_never(source)


def evidence(source: FeedSource) -> tuple[Candidate, ...]:
    """Quote only TRIAGE sources; direct questions and in-flight sends are never assessed."""
    if attention(source) is not Attention.TRIAGE:
        return ()
    match source:
        case ChatTicketSource(ticket=ticket, chat=chat):
            return tuple(_message_evidence(message, chat) for message in ticket.messages)
        case ChatMessageSource(message=message, chat=chat):
            return (_message_evidence(message, chat),)
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
        case ConsoleSource(request=request):
            excerpt = Excerpt(request.provider.value + ": " + request.title, request.detail, request.created_at)
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


def listed(feed: Feed, requests: Iterable[Request], *, history: bool) -> Iterator[FeedSource]:
    """The feed's sources in display order: pending work, or with history every captured source.

    Filtered notices stay out of pending work without being handled. Replies remain
    listed after delivery, so the person sees each outcome before it retires.
    """
    if history:
        for message in feed.messages:
            yield ChatMessageSource(message, feed.conversation(message.conversation), unseen=feed.unseen(message))
    else:
        for ticket in chat_tickets(feed):
            yield ChatTicketSource(ticket, feed.conversation(ticket.conversation))
    for update in feed.updates:
        if history or feed.needs_attention(update):
            yield UpdateSource(update, handled=not feed.pending_update(update))
    yield from map(ReplySource, feed.replies)
    for request in requests:
        source = ConsoleSource(request)
        if history or attention(source) is not Attention.RESOLVED:
            yield source


def triage_evidence(feed: Feed, requests: Iterable[Request]) -> tuple[Candidate, ...]:
    return tuple(chain.from_iterable(map(evidence, listed(feed, requests, history=False))))


def chat_message(feed: Feed, identity: str) -> Message | None:
    """The captured message a chat evidence identity names, seen or not."""
    return next((message for message in feed.messages if _identity(_message_key(message)) == identity), None)
