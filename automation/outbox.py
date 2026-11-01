"""Pure bounded event retention, coalescing and explicit volatile-history loss."""

from dataclasses import dataclass, replace
from typing import Final

from automation import ipc
from automation.presentation import Answer, Progress, ReasoningSummary, StreamState, ToolActivity, ToolStatus
from automation.task import RunRef

MAX_BUFFER_BYTES: Final = 4 * ipc.MAX_FRAME


@dataclass(frozen=True, slots=True)
class Queued:
    envelope: ipc.Envelope
    size: int


@dataclass(frozen=True, slots=True)
class Outbox:
    sequence: int = 0
    acknowledged: int = 0
    entries: tuple[Queued, ...] = ()


def _update_key(payload: ipc.BridgeEvent) -> tuple[RunRef, str, str] | None:
    match payload:
        case ipc.LogEvent(run, Progress()):
            return run, "progress", ""
        case ipc.LogEvent(run, Answer(identity)):
            return run, "answer", identity
        case ipc.LogEvent(run, ReasoningSummary(identity)):
            return run, "reasoning", identity
        case ipc.LogEvent(run, ToolActivity(identity)):
            return run, "tool", identity
        case _:
            return None


def _replaceable(payload: ipc.BridgeEvent) -> bool:
    match payload:
        case ipc.LogEvent(event=Progress() | Answer(state=StreamState.RUNNING) | ReasoningSummary(state=StreamState.RUNNING)):
            return True
        case ipc.LogEvent(event=ToolActivity(outcome=ToolStatus.RUNNING)):
            return True
        case _:
            return False


def enqueue(state: Outbox, epoch: str, payload: ipc.BridgeEvent) -> tuple[Outbox, bool]:
    """Coalesce unfinished updates; explicitly reset after any other data loss."""
    message = ipc.Envelope(epoch, state.sequence + 1, payload)
    size = len(ipc.encode_event(message))
    if size > ipc.MAX_FRAME - 4096:
        raise ValueError("The event is too large for a bounded IPC reply.")
    key = _update_key(payload)
    entries = tuple(
        item for item in state.entries if not (key is not None and _replaceable(item.envelope.payload) and _update_key(item.envelope.payload) == key)
    )
    lost = len(entries) >= ipc.MAX_EVENTS or sum(item.size for item in entries) + size > MAX_BUFFER_BYTES
    if lost:
        resync = ipc.Envelope(epoch, state.sequence + 1, ipc.Resync("Live updates were discarded; reload work and request fresh approval previews."))
        entries = (Queued(resync, len(ipc.encode_event(resync))),)
        message = replace(message, sequence=state.sequence + 2)
    return Outbox(message.sequence, state.acknowledged, (*entries, Queued(message, size))), lost
