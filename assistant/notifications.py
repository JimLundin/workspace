"""A bounded notification projection; expiry never edits the conversation.

Session observations and monotonic timestamps enter here. The UI owns windows,
timer callbacks and motion; the model remembers which content has been seen so
an expired reply cannot reappear on the next status update.
"""

from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import Final, assert_never

from assistant.agent_session import AgentRequest, Answered, Cancelled, ChatMessage, MeetingMessage, Snapshot, message_body, pending, presentation
from assistant.recording_state import RecordingState, duration, phase_label
from automation.presentation import Answer, Failed, ReasoningSummary, StreamState, Succeeded, ToolActivity, ToolStatus
from automation.task import Approval, ApprovalDecision, Question

MAX_VISIBLE: Final = 5
WIDTH: Final = 360  # maximum logical width, independent of the full history window
MIN_SECONDS: Final = 12.0
MAX_SECONDS: Final = 30.0
MOTION_SECONDS: Final = 0.28  # Vault of Glass: motion.base
REVEAL_SECONDS: Final = 0.16  # Vault of Glass: motion.fast


class Kind(Enum):
    RECORDING = auto()


class Busy(Enum):
    THINKING = auto()
    WAITING = auto()
    STOPPING = auto()


class Tone(Enum):
    USER = auto()
    THINKING = auto()
    ACTION = auto()
    REPLY = auto()
    QUESTION = auto()
    ERROR = auto()
    RECORDING = auto()


@dataclass(frozen=True, slots=True)
class MessageKey:
    index: int


@dataclass(frozen=True, slots=True)
class ResponseKey:
    index: int


@dataclass(frozen=True, slots=True)
class TurnKey:
    request: int


@dataclass(frozen=True, slots=True)
class PhaseKey:
    identity: str


type Key = Kind | MessageKey | ResponseKey | TurnKey | PhaseKey


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


@dataclass(frozen=True, slots=True)
class Recording:
    state: RecordingState


type Content = Turn | Entry | Response | Recording


class Held(Enum):
    ACTIVE = auto()
    READING = auto()


@dataclass(frozen=True, slots=True)
class Expires:
    at: float


@dataclass(frozen=True, slots=True)
class Paused:
    remaining: float


type Lifetime = Held | Expires | Paused


@dataclass(frozen=True, slots=True)
class Toast:
    key: Key
    content: Content
    lifetime: Lifetime
    order: int


@dataclass(frozen=True, slots=True)
class Stack:
    identity: str = ""
    observed: tuple[Content, ...] = ()
    toasts: tuple[Toast, ...] = ()
    serial: int = 0
    pages: int = 1
    hidden: frozenset[Key] = frozenset()


def key_of(content: Content) -> Key:
    match content:
        case Turn(request):
            return TurnKey(request)
        case Recording():
            return Kind.RECORDING
        case Entry(index):
            return MessageKey(index)
        case Response(index):
            return ResponseKey(index)
        case _:
            assert_never(content)


def active(content: Content) -> bool:
    match content:
        case Turn(entries=entries, state=state):
            return isinstance(state, Working) or any(active(entry) for entry in entries)
        case Recording(state):
            return state.phase in ("starting", "recording", "stopping", "finishing", "paused")
        case Entry(message=Answer(state=StreamState.RUNNING) | ToolActivity(outcome=ToolStatus.RUNNING)):
            return True
        case Entry(message=AgentRequest() as message):
            return pending(message)
        case Entry(message=ChatMessage(source=source)) if source is not None and source.identity.startswith("canvas:question:"):
            return True
        case Entry() | Response():
            return False
        case _:
            assert_never(content)


def can_stop(content: Content) -> bool:
    match content:
        case Turn(state=state):
            return isinstance(state, Working)
        case Recording(state):
            return state.capturing
        case Entry() | Response():
            return False
        case _:
            assert_never(content)


def observe(session: Snapshot) -> tuple[Content, ...]:
    result: list[Content] = []
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
                    case AgentRequest(reply=Answered(text)):
                        target.append(Response(index, text, message.created_at))
                    case AgentRequest(reply=ApprovalDecision() as decision):
                        target.append(Response(index, decision.name.capitalize(), message.created_at))
                    case _:
                        pass
            case MeetingMessage() | ReasoningSummary():
                pass
            case _:
                assert_never(message)
    finish_turn()
    if session.recording.visible:
        result.append(Recording(session.recording))
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


def results(turn: Turn) -> tuple[Entry | Response, ...]:
    """Keep the latest reply and pending input attached when steps are collapsed.

    An answered question stays visible with its response until a new reply or
    question replaces it. Earlier replies and resolved input remain in steps.
    """
    latest = next(
        (
            entry.index
            for entry in reversed(turn.entries)
            if isinstance(entry, Entry)
            and isinstance(entry.message, (Answer, ChatMessage, AgentRequest))
            and not (isinstance(entry.message, ChatMessage) and entry.message.speaker == "You")
        ),
        -1,
    )
    return tuple(
        entry
        for entry in turn.entries
        if entry.index == latest or (isinstance(entry, Entry) and isinstance(entry.message, AgentRequest) and pending(entry.message))
    )


def steps(turn: Turn) -> tuple[Entry | Response, ...]:
    attached = {entry.index for entry in results(turn)}
    return tuple(
        entry
        for entry in turn.entries
        if entry.index not in attached
        and not (isinstance(entry, Entry) and isinstance(entry.message, ChatMessage) and entry.message.speaker == "You")
    )


def caption(content: Content) -> str:
    if not isinstance(content, Turn):
        return ""
    actions = tuple(entry.message for entry in content.entries if isinstance(entry, Entry) and isinstance(entry.message, ToolActivity))
    count = len(actions)
    if not count:
        return "Show steps" if steps(content) else ""
    complete = sum(isinstance(action.outcome, Succeeded) for action in actions)
    if complete == count:
        return f"{count} completed step" + ("s" if count != 1 else "")
    return f"{complete} of {count} steps complete"


def reading_seconds(content: Content) -> float:
    text = body(content)
    minimum = 20.0 if tone(content) is Tone.ERROR else MIN_SECONDS
    return min(MAX_SECONDS, max(minimum, 4 + len(text.split()) / 3))


def advance(
    stack: Stack, session: Snapshot, now: float, *, history: bool = False, page: int = 0, reveal: bool = False, limit: int = MAX_VISIBLE
) -> Stack:
    if stack.identity != session.identity:
        stack = Stack(identity=session.identity, serial=stack.serial)
    previous = {key_of(content): content for content in stack.observed}
    existing = {toast.key: toast for toast in stack.toasts}
    observed = observe(session)
    current = next((content.request for content in reversed(observed) if isinstance(content, Turn)), None)
    remembered: list[Content] = []
    toasts: list[Toast] = []
    serial = stack.serial
    for observation in observed:
        content = observation
        key = key_of(content)
        prior = previous.get(key)
        # Session.result belongs only to the newest turn. Preserve an older
        # completion once observed so a follow-up cannot revive it as changed.
        if (
            isinstance(content, Turn)
            and content.request != current
            and isinstance(prior, Turn)
            and isinstance(prior.state, Settled)
            and content.entries == prior.entries
        ):
            content = replace(content, state=prior.state)
        remembered.append(content)
        if key in stack.hidden:
            continue
        toast = existing.get(key)
        changed = previous.get(key) != content
        if toast is None and not changed and not active(content) and not reveal and not history:
            continue
        if toast is None:
            serial += 1
            toast = Toast(key, content, Held.ACTIVE, serial)
        lifetime = toast.lifetime
        if active(content) or history or ((session.busy or session.waiting) and isinstance(content, (Turn, Entry, Response))):
            if lifetime is not Held.READING:
                lifetime = Held.ACTIVE
        elif lifetime is Held.READING:
            pass  # The view releases this after the last line becomes readable.
        elif changed or lifetime is Held.ACTIVE:
            seconds = reading_seconds(content)
            lifetime = Paused(seconds) if isinstance(lifetime, Paused) else Expires(now + seconds)
        if isinstance(lifetime, Expires) and lifetime.at <= now:
            continue
        toasts.append(replace(toast, content=content, lifetime=lifetime))
    # Keep controls and pending input, then the newest conversation entries. Overflow only
    # leaves this projection; every message remains in the session's history.
    toasts.sort(key=lambda toast: (priority(toast.content), order_of(toast)), reverse=True)
    pinned = [toast for toast in toasts if priority(toast.content) >= 2]
    limit = max(1, min(MAX_VISIBLE, limit))
    # Leave a pageable slot when urgent work itself overflows the viewport.
    # Every request remains reachable even on a screen that fits only one card.
    keep = min(len(pinned), limit if len(toasts) <= limit else limit - 1)
    ordinary = [*pinned[keep:], *(toast for toast in toasts if priority(toast.content) < 2)]
    room = limit - keep
    pages = max(1, (len(ordinary) + room - 1) // room) if room else 1
    start = min(max(0, page), pages - 1) * room
    visible = tuple(sorted((*pinned[:keep], *ordinary[start : start + room]), key=order_of))
    return Stack(session.identity, tuple(remembered), visible, serial, pages, stack.hidden)


def reading_hold(stack: Stack, key: Key, *, reading: bool, now: float, busy: bool, hovered: bool) -> Stack:
    # A keyed reading request, its timestamp and independent owner/pointer
    # observations determine the lifetime; the stack alone cannot supply them.
    toasts: list[Toast] = []
    changed = False
    for toast in stack.toasts:
        lifetime = toast.lifetime
        if toast.key == key:
            if reading:
                lifetime = Held.READING
            elif lifetime is Held.READING:
                seconds = reading_seconds(toast.content)
                lifetime = Held.ACTIVE if busy or active(toast.content) else Paused(seconds) if hovered else Expires(now + seconds)
        changed = changed or lifetime != toast.lifetime
        toasts.append(toast if lifetime == toast.lifetime else replace(toast, lifetime=lifetime))
    return replace(stack, toasts=tuple(toasts)) if changed else stack


def priority(content: Content) -> int:
    match content:
        case Turn() if hint(content):
            return 2
        case Turn() | Recording() if active(content):
            return 3
        case Entry(message=AgentRequest() as message) if pending(message):
            return 2
        case _:
            return int(active(content))


def order_of(toast: Toast) -> tuple[float, int, int]:
    """A turn starts with its request, then thinking and its chronological activity."""
    match toast.content:
        case Entry(index, message):
            return message.created_at, index, 0
        case Response(index, created_at=at):
            return at, index, 1
        case Turn(request=request):
            return toast.content.created_at, request, 2
        case Recording():
            return float("inf"), 0, 0
        case _:
            assert_never(toast.content)


def hover(stack: Stack, key: Key, *, inside: bool, now: float) -> Stack:
    # The current stack, toast target and timed pointer direction form one
    # lifetime transition. Passing the clock observation keeps that decision pure.
    def update(toast: Toast) -> Toast:
        if toast.key != key:
            return toast
        match toast.lifetime, inside:
            case Expires(at), True:
                return replace(toast, lifetime=Paused(max(0, at - now)))
            case Paused(remaining), False:
                return replace(toast, lifetime=Expires(now + remaining))
            case _:
                return toast

    return replace(stack, toasts=tuple(update(toast) for toast in stack.toasts))


def next_expiry(stack: Stack) -> float | None:
    return min((toast.lifetime.at for toast in stack.toasts if isinstance(toast.lifetime, Expires)), default=None)


def body(content: Content) -> str:
    match content:
        case Entry(message=AgentRequest() as message):
            return message.text + ("\n\n" + message.detail if message.detail else "")
        case Turn():
            return "\n\n".join(body(entry) for entry in results(content))
        case Entry(message=message):
            return message_body(message)
        case Response(text=text):
            return text
        case Recording(state):
            return state.detail or state.preview or state.title
        case _:
            assert_never(content)


def heading(content: Content) -> str:
    match content:
        case Turn(state=progress):
            match progress:
                case Working(phase=Busy.STOPPING):
                    return "Stopping…"
                case Working(phase=Busy.WAITING):
                    return "Waiting for you"
                case Working(queued=queued):
                    return "Thinking" + (f" · {queued} queued" if queued else "")
                case Settled.FINISHED:
                    return "Finished"
                case Settled.STOPPED:
                    return "Stopped"
                case Settled.ATTENTION:
                    return "Needs attention"
                case _:
                    assert_never(progress)
        case Entry(message=message):
            return presentation(message).role
        case Response():
            return "You"
        case Recording(state):
            return f"{phase_label(state.phase)} · {duration(state.seconds)}"
        case _:
            assert_never(content)


def hint(content: Content) -> str:
    match content:
        case Turn():
            return next((text for entry in results(content) if (text := hint(entry))), "")
        case Entry(message=AgentRequest(request=Question()) as message) if pending(message):
            return "N toggles a spoken reply"
        case Entry(message=AgentRequest(request=Approval()) as message) if pending(message):
            return "N: say “approve” or “decline”"
        case Recording(state=RecordingState(phase="paused")):
            return "Transcription paused · Retry in Agent session"
        case _:
            return ""


def plain(content: Content) -> bool:
    match content:
        case Entry(message=ToolActivity() | ChatMessage(speaker="You" | "Error")) | Response():
            return True
        case _:
            return False


def spinning(content: Content) -> bool:
    match content:
        case Turn(state=Working(phase=Busy.WAITING)):
            return False
        case Turn(state=Working()):
            return True
        case Recording(state=RecordingState(phase="starting" | "stopping" | "finishing")):
            return True
        case Turn() | Entry() | Response() | Recording():
            return False
        case _:
            assert_never(content)


def tone(content: Content) -> Tone:
    match content:
        case Entry(message=ChatMessage(source=source)) if source is not None and source.identity.startswith("canvas:question:"):
            return Tone.QUESTION
        case Entry(message=ChatMessage(speaker="You")) | Response():
            return Tone.USER
        case Turn() if hint(content):
            return Tone.QUESTION
        case Entry(message=AgentRequest()):
            return Tone.QUESTION
        case Entry(message=ToolActivity(outcome=Failed()) | ChatMessage(speaker="Error")):
            return Tone.ERROR
        case Entry(message=ToolActivity()):
            return Tone.ACTION
        case Turn(state=Settled.ATTENTION):
            return Tone.ERROR
        case Turn(state=Working()):
            return Tone.THINKING
        case Turn() | Entry():
            return Tone.REPLY
        case Recording(state=RecordingState(phase="paused" | "interrupted")):
            return Tone.QUESTION
        case Recording():
            return Tone.RECORDING
        case _:
            assert_never(content)


@dataclass(frozen=True, slots=True)
class Frame:
    y: float
    width: float
    height: float
    alpha: float
    details: float = 0


@dataclass(frozen=True, slots=True)
class Motion:
    start: Frame
    end: Frame
    started: float

    def sample(self, now: float) -> Frame:
        progress = max(0.0, min(1.0, (now - self.started) / MOTION_SECONDS))
        if progress == 0:
            return self.start
        if progress == 1:
            return self.end
        amount = ease_out(progress)
        return Frame(
            self.start.y + (self.end.y - self.start.y) * amount,
            self.start.width + (self.end.width - self.start.width) * amount,
            self.start.height + (self.end.height - self.start.height) * amount,
            self.start.alpha + (self.end.alpha - self.start.alpha) * amount,
            self.start.details + (self.end.details - self.start.details) * amount,
        )

    def finished(self, now: float) -> bool:
        return now >= self.started + MOTION_SECONDS


def ease_out(progress: float) -> float:
    """Vault of Glass's cubic-bezier(0.32, 0.72, 0, 1), without overshoot."""
    if progress <= 0 or progress >= 1:
        return max(0.0, min(1.0, progress))
    low, high = 0.0, 1.0
    for _ in range(18):
        t = (low + high) / 2
        x = 3 * (1 - t) ** 2 * t * 0.32 + t**3
        if x < progress:
            low = t
        else:
            high = t
    t = (low + high) / 2
    return 3 * (1 - t) ** 2 * t * 0.72 + 3 * (1 - t) * t**2 + t**3


def hide(stack: Stack, key: Key) -> Stack:
    return replace(stack, hidden=stack.hidden | {key}, toasts=tuple(toast for toast in stack.toasts if toast.key != key))
