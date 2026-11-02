"""Transient phases of agent work, independent of durable canvas contributions."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from textwrap import shorten

from assistant.agent_session import ChatMessage, Message, Snapshot
from assistant.canvas_session import redirect_session
from assistant.feed_origin import Initiation
from assistant.notifications import (
    Entry,
    Expires,
    Held,
    PhaseKey,
    Response,
    Stack,
    Toast,
    Turn,
    advance,
    observe,
    reading_seconds,
)
from automation.presentation import Answer, ReasoningSummary

TRAIL_LENGTH = 3


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
    # Notification investigations stay in history; their decisions and canvas
    # findings use the independent navigation projection when attention is needed.
    automatic = False
    for message in messages:
        match message:
            case ChatMessage(speaker="You", source=source):
                automatic = source is not None and source.initiation is Initiation.AUTOMATIC
                if not automatic:
                    yield message
            case ChatMessage(source=source) if source is not None and source.identity.startswith("canvas:"):
                continue
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
        messages = (ChatMessage("You", "", 0), *messages)
    # A quiet automatic task must not synthesize an empty unprompted progress card.
    projected = replace(session, messages=messages, phase=session.phase if messages and not automatic else "idle")
    for content in observe(projected):
        match content:
            case Turn(request=request, created_at=at):
                identity = f"request:{at}" if request >= 0 else "unprompted:" + session.identity
                yield Phase(PhaseKey(identity), content)
            case _:
                pass


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
