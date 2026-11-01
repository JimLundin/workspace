"""Workspace's event identity, terminal retention and volatile-history bounds."""

from unittest import TestCase

from automation import ipc
from automation.outbox import MAX_BUFFER_BYTES, Outbox, enqueue
from automation.presentation import Answer, Failed, Problem, Progress, ReasoningSummary, Said, StreamState, Succeeded, ToolActivity, ToolStatus
from automation.task import RunRef

EPOCH = "a" * 32
RUN = RunRef("notes", "first-run")


def test_coalescing_is_scoped_to_run_event_kind_and_identity() -> None:
    # Defect: matching text-row identities discard another run or event family's update.
    other_run = RunRef("notes", "second-run")
    initial = (
        ipc.LogEvent(RUN, Progress("Reading")),
        ipc.LogEvent(other_run, Progress("Other run")),
        ipc.LogEvent(RUN, Answer("shared", "Answer", 1)),
        ipc.LogEvent(RUN, Answer("other", "Another answer", 1)),
        ipc.LogEvent(other_run, Answer("shared", "Other run answer", 1)),
        ipc.LogEvent(RUN, ReasoningSummary("shared", "Reasoning", 1)),
        ipc.LogEvent(RUN, ToolActivity("shared", "read", "Tool", 1)),
    )
    replacements = (
        ipc.LogEvent(RUN, Progress("Read")),
        ipc.LogEvent(RUN, Answer("shared", "Updated answer", 1)),
        ipc.LogEvent(RUN, ReasoningSummary("shared", "Updated reasoning", 1)),
        ipc.LogEvent(RUN, ToolActivity("shared", "read", "Updated tool", 1)),
    )
    state = Outbox()
    for payload in (*initial, *replacements):
        state, lost = enqueue(state, EPOCH, payload)
        assert not lost
    assert tuple(item.envelope.payload for item in state.entries) == (initial[1], initial[3], initial[4], *replacements)
    assert state.sequence == len(initial) + len(replacements)


def test_finalized_stream_updates_and_speech_survive_later_matching_updates() -> None:
    # Defect: a later stream update erases completion, interruption or tool-effect evidence.
    finalized = (
        ipc.LogEvent(RUN, Answer("complete", "Saved", 1, StreamState.COMPLETE)),
        ipc.LogEvent(RUN, Answer("interrupted", "Stopped", 1, StreamState.INTERRUPTED)),
        ipc.LogEvent(RUN, ReasoningSummary("complete", "Checked", 1, StreamState.COMPLETE)),
        ipc.LogEvent(RUN, ReasoningSummary("interrupted", "Stopped", 1, StreamState.INTERRUPTED)),
        ipc.LogEvent(RUN, ToolActivity("succeeded", "read", "Read", 1, Succeeded("Read"))),
        ipc.LogEvent(RUN, ToolActivity("failed", "read", "Failed", 1, Failed("Unavailable"))),
        ipc.LogEvent(RUN, ToolActivity("cancelled", "read", "Stopped", 1, ToolStatus.CANCELLED)),
        ipc.LogEvent(RUN, Said("Result", 1)),
        ipc.LogEvent(RUN, Problem("Unavailable", 1)),
    )
    later = (
        ipc.LogEvent(RUN, Answer("complete", "Later", 1)),
        ipc.LogEvent(RUN, Answer("interrupted", "Later", 1)),
        ipc.LogEvent(RUN, ReasoningSummary("complete", "Later", 1)),
        ipc.LogEvent(RUN, ReasoningSummary("interrupted", "Later", 1)),
        ipc.LogEvent(RUN, ToolActivity("succeeded", "read", "Later", 1)),
        ipc.LogEvent(RUN, ToolActivity("failed", "read", "Later", 1)),
        ipc.LogEvent(RUN, ToolActivity("cancelled", "read", "Later", 1)),
        ipc.LogEvent(RUN, Said("Result", 1)),
        ipc.LogEvent(RUN, Problem("Unavailable", 1)),
    )
    state = Outbox()
    for payload in (*finalized, *later):
        state, lost = enqueue(state, EPOCH, payload)
        assert not lost
    assert tuple(item.envelope.payload for item in state.entries) == (*finalized, *later)


def test_count_overflow_reports_resync_before_retaining_the_new_event() -> None:
    # Defect: capacity is reduced by one, or discarded live history is silently hidden.
    state = Outbox(sequence=7, acknowledged=7)
    for index in range(ipc.MAX_EVENTS):
        state, lost = enqueue(state, EPOCH, ipc.LogEvent(RUN, Said(f"Result {index}", index)))
        assert not lost
    assert len(state.entries) == ipc.MAX_EVENTS
    previous = state.sequence
    latest = ipc.LogEvent(RUN, Said("Latest result", 200))
    state, lost = enqueue(state, EPOCH, latest)
    assert lost and state.acknowledged == 7
    resync, retained = state.entries
    assert isinstance(resync.envelope.payload, ipc.Resync)
    assert resync.envelope == ipc.Envelope(EPOCH, previous + 1, resync.envelope.payload)
    assert retained.envelope == ipc.Envelope(EPOCH, previous + 2, latest)
    assert state.sequence == retained.envelope.sequence


def sized_speech(state: Outbox, size: int) -> ipc.LogEvent:
    empty = ipc.LogEvent(RUN, Said("", 1))
    overhead = len(ipc.encode_event(ipc.Envelope(EPOCH, state.sequence + 1, empty)))
    return ipc.LogEvent(RUN, Said("x" * (size - overhead), 1))


def test_byte_overflow_keeps_the_exact_budget_and_resets_before_the_next_event() -> None:
    # Defect: byte retention loses history too early or exceeds its independent bound.
    state = Outbox()
    chunk_size = ipc.MAX_FRAME - 8192
    for _ in range(MAX_BUFFER_BYTES // chunk_size):
        state, lost = enqueue(state, EPOCH, sized_speech(state, chunk_size))
        assert not lost
    remaining = MAX_BUFFER_BYTES - sum(item.size for item in state.entries)
    state, lost = enqueue(state, EPOCH, sized_speech(state, remaining))
    assert not lost and sum(item.size for item in state.entries) == MAX_BUFFER_BYTES
    assert len(state.entries) < ipc.MAX_EVENTS
    latest = ipc.LogEvent(RUN, Said("Next", 2))
    state, lost = enqueue(state, EPOCH, latest)
    assert lost
    resync, retained = state.entries
    assert isinstance(resync.envelope.payload, ipc.Resync)
    assert retained.envelope.payload == latest
    assert retained.envelope.sequence == resync.envelope.sequence + 1


def test_event_reserves_reply_overhead_before_enqueueing() -> None:
    # Defect: an individually accepted event leaves too little room for its bounded reply.
    state = Outbox()
    state, lost = enqueue(state, EPOCH, sized_speech(state, ipc.MAX_FRAME - 4096))
    assert not lost
    with TestCase().assertRaisesRegex(ValueError, "too large"):
        enqueue(state, EPOCH, sized_speech(state, ipc.MAX_FRAME - 4095))
