"""Agent work as the bar reads it: the session's turns, grouped into phases by their work context."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import assert_never

from assistant.agent_session import AgentRequest, Cancelled, ChatMessage, MeetingMessage, Message, Pending, Snapshot, notice_text, pending
from assistant.attention import AttentionSnapshot, context_of
from assistant.canvas_activity import Attention, CanvasRequest
from assistant.feed_origin import FeedRequest, Initiation
from automation.presentation import Answer, Failed, ReasoningSummary, StreamState, Succeeded, ToolActivity, ToolStatus
from automation.task import Question, TextAnswer


class Busy(Enum):
    THINKING = auto()
    WAITING = auto()
    STOPPING = auto()


@dataclass(frozen=True, slots=True)
class PhaseKey:
    identity: str


@dataclass(frozen=True, slots=True)
class Working:
    generation: int
    phase: Busy
    queued: int


class Settled(Enum):
    FINISHED = auto()
    STOPPED = auto()
    ATTENTION = auto()


@dataclass(frozen=True, slots=True)
class Entry:
    index: int
    message: ChatMessage | Answer | ToolActivity | AgentRequest


@dataclass(frozen=True, slots=True)
class Response:
    index: int
    text: str
    created_at: float = 0


@dataclass(frozen=True, slots=True)
class Turn:
    """One assistant bubble owns its steps and result, even after completion."""

    request: int
    entries: tuple[Entry | Response, ...]
    state: Working | Settled
    created_at: float = 0


def observe(session: Snapshot) -> tuple[Turn | Entry | Response, ...]:
    """The session's turns: each request with its steps, questions and replies."""
    result: list[Turn | Entry | Response] = []
    requests = tuple(index for index, message in enumerate(session.messages) if isinstance(message, ChatMessage) and message.speaker == "You")
    latest = requests[-1] if requests else -1
    initial_input = any(isinstance(message, AgentRequest) for message in session.messages[: requests[0] if requests else None])
    request: int | None = -1 if initial_input or (latest == -1 and session.busy) else None
    entries: list[Entry | Response] = []

    def finish_turn() -> None:
        if request is None:
            return
        state: Working | Settled = settled(tuple(entries))
        if request == latest:
            if session.busy or session.waiting:
                phase = Busy.STOPPING if session.stopping else Busy.WAITING if session.waiting else Busy.THINKING
                state = Working(session.generation, phase, len(session.queued))
            elif session.result == "Stopped":
                state = Settled.STOPPED
            elif session.result == "Needs attention":
                state = Settled.ATTENTION
        at = (
            session.messages[request].created_at
            if request >= 0
            else min((entry.message.created_at for entry in entries if isinstance(entry, Entry)), default=0)
        )
        result.append(Turn(request, tuple(entries), state, at))

    for index, message in enumerate(session.messages):
        match message:
            case ChatMessage(speaker="You"):
                finish_turn()
                request, entries = index, [Entry(index, message)]
            case ChatMessage() | Answer() | ToolActivity() | AgentRequest():
                target = result if request is None else entries
                target.append(Entry(index, message))
                match message:
                    case AgentRequest(reply=TextAnswer(text)):
                        target.append(Response(index, text, message.created_at))
                    case _:
                        pass
            case MeetingMessage() | ReasoningSummary():
                pass
            case _:
                assert_never(message)
    finish_turn()
    return tuple(result)


def settled(entries: tuple[Entry | Response, ...]) -> Settled:
    for entry in reversed(entries):
        match entry:
            case Entry(message=ChatMessage(speaker="Error") | ToolActivity(outcome=Failed())):
                return Settled.ATTENTION
            case Entry(message=Answer(state=StreamState.INTERRUPTED) | ToolActivity(outcome=ToolStatus.CANCELLED)):
                return Settled.STOPPED
            case Entry(message=ChatMessage(speaker="Workspace", text=text)) if text.startswith("Stopped"):
                return Settled.STOPPED
            case Entry(message=AgentRequest(reply=Cancelled())):
                return Settled.STOPPED
            case Entry(message=ChatMessage() | Answer() | ToolActivity(outcome=Succeeded())):
                return Settled.FINISHED
            case _:
                pass
    return Settled.FINISHED


def hint(turn: Turn) -> str:
    """How to answer a pending request without leaving the bar."""
    pending_request = any(isinstance(entry, Entry) and isinstance(entry.message, AgentRequest) and pending(entry.message) for entry in turn.entries)
    return "N toggles a spoken reply" if pending_request else ""


@dataclass(frozen=True, slots=True)
class Phase:
    key: PhaseKey
    turn: Turn
    request: CanvasRequest | None = None


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
