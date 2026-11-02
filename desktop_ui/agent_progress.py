"""Transient phases of agent work, independent of durable canvas contributions."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from textwrap import shorten

from assistant.canvas_activity import Attention, CanvasRequest
from assistant.feed_origin import FeedRequest, Initiation
from automation.presentation import Answer, ReasoningSummary, ToolActivity
from automation.task import Question, TextAnswer
from desktop_ui.agent_session import AgentRequest, Cancelled, ChatMessage, Message, Pending, Snapshot, notice_text, pending
from desktop_ui.attention import AttentionSnapshot, context_of
from desktop_ui.notifications import (
    Busy,
    Entry,
    Expires,
    Held,
    PhaseKey,
    Response,
    Settled,
    Stack,
    Toast,
    Turn,
    Working,
    advance,
    expire_in_order,
    observe,
    reading_seconds,
)

TRAIL_LENGTH = 3


@dataclass(frozen=True, slots=True)
class Phase:
    key: PhaseKey
    turn: Turn
    request: CanvasRequest | None = None


@dataclass(frozen=True, slots=True)
class Progress:
    navigation: Stack = field(default_factory=Stack)
    observed: tuple[Phase, ...] = ()
    toasts: tuple[Toast, ...] = ()


def phase_messages(messages: Iterable[Message]) -> Iterator[Message]:
    # Notification investigations stay in history; their questions and useful
    # canvas findings join the same work-context card when attention is needed.
    automatic = False
    for message in messages:
        match message:
            case ChatMessage(speaker="You", source=source):
                automatic = source is not None and source.initiation is Initiation.AUTOMATIC
                if not automatic:
                    yield message
            case ChatMessage(source=source) if source is not None and source.identity.startswith("canvas:"):
                continue
            case AgentRequest():
                yield message
            case _ if automatic:
                continue
            case ReasoningSummary(text=text, created_at=created):
                if text.strip():
                    yield ChatMessage("Workspace", text, created)
            case _:
                yield message


def phases(session: Snapshot) -> Iterator[Phase]:
    """One requested outcome owns its public updates, actions and final reply."""
    messages = tuple(phase_messages(session.messages))
    latest = next((message for message in reversed(session.messages) if isinstance(message, ChatMessage) and message.speaker == "You"), None)
    automatic = latest is not None and latest.source is not None and latest.source.initiation is Initiation.AUTOMATIC
    if messages and not any(isinstance(message, ChatMessage) and message.speaker == "You" for message in messages):
        messages = (
            ChatMessage(
                "You",
                latest.text if latest is not None else "",
                latest.created_at if latest is not None else 0,
                latest.source if latest is not None else None,
            ),
            *messages,
        )
    # A quiet automatic task must not synthesize an empty unprompted progress card.
    projected = replace(session, messages=messages, phase=session.phase if messages and not automatic else "idle")
    regular: tuple[Phase, ...] = ()
    for content in observe(projected):
        match content:
            case Turn(request=request, created_at=at):
                identity = f"request:{at}" if request >= 0 else "unprompted:" + session.identity
                origin = next(
                    (
                        entry.message.source
                        for entry in content.entries
                        if isinstance(entry, Entry) and isinstance(entry.message, ChatMessage) and entry.message.speaker == "You"
                    ),
                    None,
                )
                question = next(
                    (
                        item
                        for item in session.attention.items
                        if item.question is not None
                        and any(
                            isinstance(entry, Entry)
                            and isinstance(entry.message, AgentRequest)
                            and entry.message.id == item.question.request.request_id
                            for entry in content.entries
                        )
                    ),
                    None,
                )
                if question is not None:
                    identity = "context:" + question.context
                elif origin is not None:
                    identity = "context:" + context_of(session.attention, origin.identity)
                linked = canvas_requests(content, session.attention)
                route = next(
                    (
                        item.question.request
                        for item in session.attention.items
                        if item.question is not None
                        and item.question.reply is Attention.WAITING
                        and any(
                            isinstance(entry, Entry)
                            and isinstance(entry.message, AgentRequest)
                            and entry.message.id == item.question.request.request_id
                            for entry in content.entries
                        )
                    ),
                    None,
                )
                regular = (*regular, Phase(PhaseKey(identity), linked, route))
            case _:
                pass
    yield from coalesced((*regular, *canvas_phases(session)))


def canvas_requests(turn: Turn, attention: AttentionSnapshot) -> Turn:
    """Keep a question's optional canvas control with its complete inline request."""
    entries: tuple[Entry | Response, ...] = ()
    for original in turn.entries:
        entry = original
        match entry:
            case Entry(message=AgentRequest() as request):
                question = next(
                    (item.question for item in attention.items if item.question is not None and item.question.request.request_id == request.id),
                    None,
                )
                if question is not None:
                    entry = replace(entry, message=replace(request, detail=notice_text(request.detail, question.id)))
            case _:
                pass
        entries = (*entries, entry)
    return replace(turn, entries=entries)


def canvas_phases(session: Snapshot) -> Iterator[Phase]:
    notices = tuple(
        message
        for message in session.messages
        if isinstance(message, ChatMessage)
        and message.source is not None
        and message.source.identity.startswith("canvas:")
        and message.source.identity.removeprefix("canvas:") not in session.attention.hidden
    )
    contexts = tuple(frozendict((context_of(session.attention, message.source.identity), None) for message in notices if message.source is not None))
    for context in contexts:
        messages = tuple(
            message for message in notices if message.source is not None and context_of(session.attention, message.source.identity) == context
        )
        newest = max(message.created_at for message in messages)
        latest = next(message for message in messages if message.created_at == newest)
        target = latest.source.identity.removeprefix("canvas:") if latest.source is not None else context
        item = next((item for item in session.attention.items if item.identity == target), None)
        questions = tuple(item.question for item in session.attention.items if item.context == context and item.question is not None)
        title = next(
            (item.title for item in session.attention.items if item.identity == context), latest.source.title if latest.source else "Workspace"
        )
        entries: tuple[Entry | Response, ...] = (Entry(0, ChatMessage("You", title, latest.created_at, FeedRequest(context, title))),)
        if item is None and not questions:
            entries = (*entries, Entry(1, latest))
        for question in questions:
            reply = Pending() if question.reply is Attention.WAITING else question.reply if isinstance(question.reply, TextAnswer) else Cancelled()
            detail = notice_text(question.text, question.id)
            request = AgentRequest(Question(question.request.request_id, question.title, question.text), detail, question.created_at, reply)
            entries = (*entries, Entry(len(entries), request))
            if isinstance(reply, TextAnswer):
                entries = (*entries, Response(len(entries) - 1, reply.text, latest.created_at))
        if item is not None and item.question is None:
            text = "\n\n".join(value for value in (item.title, item.text) if value)
            entries = (*entries, Entry(len(entries), ChatMessage("Workspace", notice_text(text, target), latest.created_at, latest.source)))
        waiting = any(isinstance(entry.message, AgentRequest) and pending(entry.message) for entry in entries if isinstance(entry, Entry))
        state = Working(session.generation, Busy.WAITING, 0) if waiting else Settled.FINISHED
        route = next((question.request for question in questions if question.reply is Attention.WAITING), None)
        yield Phase(PhaseKey("context:" + context), Turn(0, entries, state, min(message.created_at for message in messages)), route)


def entry_identity(entry: Entry | Response) -> tuple[str, str]:
    match entry:
        case Entry(message=AgentRequest() as message):
            return "request", message.id
        case Entry(message=Answer(identity=identity) | ToolActivity(identity=identity)):
            return "activity", identity
        case Entry(message=ChatMessage(source=source)) if source is not None:
            return "source", source.identity
        case Entry(message=ChatMessage() as message):
            return message.speaker, message.text + str(message.created_at)
        case Response(index=index):
            return "response", str(index)
        case Entry(index=index):
            return "entry", str(index)


def coalesced(phases: Iterable[Phase]) -> Iterator[Phase]:
    groups: frozendict[PhaseKey, Phase] = frozendict()
    for observation in phases:
        phase = observation
        previous = groups.get(phase.key)
        if previous is not None:
            turns = (previous.turn, phase.turn)
            entries = frozendict((entry_identity(entry), entry) for turn in turns for entry in turn.entries if isinstance(entry, Entry))
            replies = frozendict(
                (entry_identity(target), entry)
                for turn in turns
                for entry in turn.entries
                if isinstance(entry, Response)
                for target in turn.entries
                if isinstance(target, Entry) and target.index == entry.index
            )
            combined = tuple(
                part
                for index, (identity, entry) in enumerate(entries.items())
                for part in (
                    (replace(entry, index=index), replace(replies[identity], index=index)) if identity in replies else (replace(entry, index=index),)
                )
            )
            state = phase.turn.state if isinstance(phase.turn.state, Working) else previous.turn.state
            phase = replace(phase, turn=replace(previous.turn, entries=combined, state=state), request=phase.request or previous.request)
        groups = frozendict({**groups, phase.key: phase})
    yield from groups.values()


def stable_phases(current: Iterable[Phase], previous: tuple[Phase, ...]) -> Iterator[Phase]:
    """New work connections keep the native card that already owns the source."""
    for phase in current:
        identities = frozenset(entry_identity(entry) for entry in phase.turn.entries if entry_identity(entry)[0] in ("source", "request", "You"))
        before = next((item for item in previous if any(entry_identity(entry) in identities for entry in item.turn.entries)), None)
        yield replace(phase, key=before.key) if before is not None else phase


def advance_progress(previous: Progress, session: Snapshot, now: float) -> Progress:
    if previous.navigation.identity != session.identity:
        previous = Progress()
    navigation = advance(previous.navigation, replace(session, messages=(), phase="idle"), now)
    observed = tuple(coalesced(stable_phases(phases(session), previous.observed)))[-TRAIL_LENGTH:]
    remembered = frozendict((phase.key, phase.turn) for phase in previous.observed)
    existing = frozendict((toast.key, toast) for toast in previous.toasts)
    toasts: tuple[Toast, ...] = ()
    for phase in observed:
        if phase.key in navigation.hidden:
            continue
        toast = existing.get(phase.key)
        changed = remembered.get(phase.key) != phase.turn
        if toast is None and not changed:
            continue
        lifetime = toast.lifetime if toast is not None else Held.ACTIVE
        if isinstance(phase.turn.state, Working):
            lifetime = Held.ACTIVE
        elif changed or lifetime is Held.ACTIVE:
            lifetime = Expires(now + reading_seconds(phase.turn))
        toasts = (*toasts, Toast(phase.key, phase.turn, lifetime, toast.order if toast is not None else navigation.serial + len(toasts) + 1))
    return Progress(navigation, observed, expire_in_order(toasts, now))


def visible(progress: Progress, capacity: int) -> Stack:
    navigation = progress.navigation
    notices = navigation.toasts[-capacity:]
    room = max(0, capacity - len(notices))
    trail = progress.toasts[-room:] if room else ()
    return replace(navigation, toasts=(*trail, *notices))


def retain_lifetimes(progress: Progress, stack: Stack) -> Progress:
    """Carry the native reader/hover observations into the next projection."""
    lifetimes = frozendict((toast.key, toast.lifetime) for toast in stack.toasts)

    def retained(toasts: tuple[Toast, ...]) -> tuple[Toast, ...]:
        return tuple(replace(toast, lifetime=lifetimes.get(toast.key, toast.lifetime)) for toast in toasts)

    return replace(
        progress,
        navigation=replace(progress.navigation, hidden=stack.hidden, toasts=retained(progress.navigation.toasts)),
        toasts=retained(progress.toasts),
    )


def compact(turn: Turn) -> Turn:
    """Earlier phases retain their summary, with full text available in history."""

    def entries() -> Iterator[Entry | Response]:
        for entry in turn.entries:
            match entry:
                case Entry(message=ChatMessage() | Answer() as message):
                    yield replace(entry, message=replace(message, text=shorten(message.text, width=180, placeholder="…")))
                case _:
                    yield entry

    return replace(turn, entries=tuple(entries()))
