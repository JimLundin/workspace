"""The assistant's control decisions, as values: events in, state and effects out."""

from collections.abc import Iterable
from functools import reduce

from assistant.control import (
    ControlState,
    Event,
    HandleKey,
    LayoutReported,
    Log,
    Problem,
    RecordingUpdated,
    Send,
    UseLayout,
    recording_notice,
    transition,
)
from contracts.desktop_link import Notify, RecordingChanged
from contracts.recording_state import RecordingState
from protocol import LayoutState, Tool


def folded(events: Iterable[Event], state: ControlState | None = None) -> tuple[ControlState, tuple[object, ...]]:
    """The state after `events` and every effect they produced, in order."""

    def step(folding: tuple[ControlState, tuple[object, ...]], event: Event) -> tuple[ControlState, tuple[object, ...]]:
        current, effects = folding
        following, produced = transition(current, event)
        return following, (*effects, *produced)

    return reduce(step, events, (state if state is not None else ControlState(), ()))


def test_recording_warnings_only_announce_interruptions_and_failed_captures() -> None:
    # Defect: an ordinary finish is announced as a warning, or a pause, an
    # interruption or a capture that ended with a problem passes silently.
    assert recording_notice("recording", RecordingState(phase="finishing")) is None
    assert recording_notice("recording", RecordingState(phase="finishing", detail="Disk full.")) is not None
    assert recording_notice("recording", RecordingState(phase="interrupted")) is not None
    assert recording_notice("paused", RecordingState(phase="paused")) is None
    state, effects = folded((RecordingUpdated(RecordingState(phase="recording")), RecordingUpdated(RecordingState(phase="paused"))))
    assert state.recording_phase == "paused"
    assert Send(RecordingChanged(RecordingState(phase="paused"))) in effects
    assert sum(isinstance(effect, Send) and isinstance(effect.message, Notify) for effect in effects) == 1


def test_an_unknown_layout_value_keeps_the_last_known_layout() -> None:
    # Defect: a malformed layout message switches dictation's layout state off.
    state, effects = folded((LayoutReported(LayoutState.ON.value), LayoutReported(99)))
    assert state.layout is LayoutState.ON and effects == (UseLayout(on=True), UseLayout(on=True))


def test_requests_pass_through_as_their_own_effects_and_facts_do_not() -> None:
    # Defect: a key request is dropped or duplicated, or a fact leaks out as an effect itself.
    request = HandleKey(Tool.DICTATE, down=True)
    assert folded((request,))[1] == (request,)
    _, effects = folded((Problem("The disk is full."),))
    assert effects == (Log("The disk is full."), Send(Notify("Workspace", "The disk is full.", warning=True)))
