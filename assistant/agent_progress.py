"""Transient phases of agent work, independent of durable canvas contributions."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from hashlib import sha256
from textwrap import shorten

from assistant.agent_session import ChatMessage, Message, Snapshot
from assistant.canvas_activity import redirect_session
from assistant.notifications import (
    Busy,
    Entry,
    Expires,
    Held,
    PhaseKey,
    Response,
    Stack,
    Toast,
    Turn,
    Working,
    advance,
    reading_seconds,
    settled,
)
from automation.presentation import Answer, ReasoningSummary, ToolActivity

TRAIL_LENGTH = 3
TRAIL_ALPHA = (1.0, 0.42, 0.14, 0.04, 0.02)


@dataclass(frozen=True, slots=True)
class Phase:
    key: PhaseKey
    turn: Turn


@dataclass(frozen=True, slots=True)
class Progress:
    navigation: Stack = field(default_factory=Stack)
    observed: tuple[Phase, ...] = ()
    toasts: tuple[Toast, ...] = ()


def phase_messages(messages: Iterable[Message]) -> Iterator[Message]:
    # Redirect removal must not shift phase indices and replay expired activity.
    for message in messages:
        match message:
            case ChatMessage(speaker="You"):
                yield message
            case ChatMessage(source=source) if source is not None and source.identity.startswith("canvas:"):
                continue
            case _:
                yield message


def phases(session: Snapshot) -> Iterator[Phase]:
    """A public update starts a phase; its tool calls remain inside that phase.

    SDK reasoning *summaries* are public status text. Raw reasoning is never
    supplied here. Streaming updates retain their message identity and bubble.
    """
    entries: tuple[Entry, ...] = ()
    identity = ""
    at = 0.0
    index = -1

    def phase() -> Phase:
        return Phase(PhaseKey(identity), Turn(index, entries, settled(entries), at))

    for position, message in enumerate(phase_messages(session.messages)):
        match message:
            case ChatMessage(speaker="You", created_at=created):
                if entries:
                    yield phase()
                identity, at, index = f"request:{created}", created, position
                entries = (Entry(position, message),)
            case ReasoningSummary(identity=key, text=text, created_at=created):
                if not text.strip():
                    continue
                match entries:
                    case () | (Entry(message=ChatMessage(speaker="You")),):
                        pass
                    case _:
                        yield phase()
                        entries = ()
                identity, at, index = "summary:" + key, created, position
                entries = (*entries, Entry(position, ChatMessage("Workspace", text, created)))
            case Answer(text=text, created_at=created) | ChatMessage(speaker="Workspace" | "Error", text=text, created_at=created):
                if not text.strip():
                    continue
                match entries:
                    case () | (Entry(message=ChatMessage(speaker="You")),):
                        pass
                    case _:
                        yield phase()
                        entries = ()
                identity = update_identity(message)
                at, index = created, position
                entries = (*entries, Entry(position, message))
            case ToolActivity(created_at=created):
                if not entries:
                    identity, at, index = "tool:" + message.identity, created, position
                entries = (*entries, Entry(position, message))
            case _:
                continue
    if entries:
        current = phase()
        if session.busy:
            busy = Busy.STOPPING if session.stopping else Busy.WAITING if session.waiting else Busy.THINKING
            current = replace(current, turn=replace(current.turn, state=Working(session.generation, busy, len(session.queued))))
        yield current


def advance_progress(previous: Progress, session: Snapshot, now: float) -> Progress:
    if previous.navigation.identity != session.identity:
        previous = Progress()
    navigation = advance(previous.navigation, redirect_session(session), now)
    observed = tuple(phases(session))[-TRAIL_LENGTH:]
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
        if phase.key == observed[-1].key and session.busy:
            lifetime = Held.ACTIVE
        elif changed or lifetime is Held.ACTIVE:
            lifetime = Expires(now + reading_seconds(phase.turn))
        if isinstance(lifetime, Expires) and lifetime.at <= now:
            continue
        toasts = (*toasts, Toast(phase.key, phase.turn, lifetime, toast.order if toast is not None else navigation.serial + len(toasts) + 1))
    return Progress(navigation, observed, toasts)


def update_identity(message: Answer | ChatMessage) -> str:
    match message:
        case Answer(identity=key):
            return "answer:" + key
        case ChatMessage(text=text, created_at=at):
            return f"update:{at}:" + sha256(text.encode()).hexdigest()


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
