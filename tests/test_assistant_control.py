"""The assistant's control decisions, as values: events in, state and effects out."""

from collections.abc import Iterable
from functools import reduce
from typing import cast

from assistant.agent_window import AgentWindow
from assistant.control import (
    AUTOMATIC_UNAVAILABLE,
    AutomaticUnavailable,
    CanvasPublished,
    ControlState,
    Event,
    HandleKey,
    LayoutReported,
    ObserveCatalog,
    ObserveWork,
    PersonalObserved,
    RecordingUpdated,
    Send,
    SessionOpened,
    ShowAttention,
    UseLayout,
    WorkObserved,
    idle_state,
    recording_notice,
    transition,
    tray_state,
)
from contracts.attention import AttentionSnapshot
from contracts.desktop_link import Notify, RecordingChanged, WorkChanged
from contracts.personal_work import PersonalView
from contracts.recording_state import RecordingState
from contracts.status import State
from contracts.work_canvas_contracts import CanvasPublication
from contracts.work_canvas_model import CanvasDocument
from contracts.work_snapshot import WorkSnapshot
from protocol import LayoutState, Tool


def folded(events: Iterable[Event], state: ControlState | None = None) -> tuple[ControlState, tuple[object, ...]]:
    """The state after `events` and every effect they produced, in order."""

    def step(folding: tuple[ControlState, tuple[object, ...]], event: Event) -> tuple[ControlState, tuple[object, ...]]:
        current, effects = folding
        following, produced = transition(current, event)
        return following, (*effects, *produced)

    return reduce(step, events, (state if state is not None else ControlState(), ()))


def test_work_and_personal_views_reach_the_desktop_together() -> None:
    # Defect: a work snapshot is published without the latest personal view, or a
    # personal change republishes stale work, so the desktop's My work loses one half.
    work = WorkSnapshot(status="journal busy")
    personal = PersonalView(status="Connected.")
    state, effects = folded((PersonalObserved(personal), WorkObserved(work)))
    assert state.work == work and state.personal == personal
    assert ObserveCatalog(personal.catalog) in effects and ObserveWork(work) in effects
    published = [effect.message for effect in effects if isinstance(effect, Send) and isinstance(effect.message, WorkChanged)]
    assert published[-1].snapshot.personal == personal and published[-1].snapshot.status == "journal busy"


def test_a_session_opened_after_a_canvas_change_still_shows_its_attention() -> None:
    # Defect: the agent session opened after the canvas published misses that
    # publication's attention, or attention goes to no session at all.
    attention = AttentionSnapshot()
    publication = CanvasPublication(CanvasDocument(), (), frozenset(), attention=attention)
    state, before = folded((CanvasPublished(publication),))
    assert not any(isinstance(effect, ShowAttention) for effect in before)
    window = cast(AgentWindow, object())  # an opaque session stands in; the decision never calls it
    _, after = transition(state, SessionOpened(window))
    assert tuple(after) == (ShowAttention(window, attention),)


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
    _, effects = folded((AutomaticUnavailable(),))
    assert effects == (Send(AUTOMATIC_UNAVAILABLE),)


def test_the_tray_shows_a_live_capture_first_then_running_agent_work() -> None:
    # Defect: running agent work hides a live capture, or a resting tray hides running work.
    assert tray_state(State.READY, listening=Tool.DICTATE, running=True, waiting=False) is State.LISTENING
    assert tray_state(State.READY, listening=None, running=True, waiting=True) is State.NEEDS_INPUT
    assert tray_state(State.LAYOUT_OFF, listening=None, running=True, waiting=False) is State.AGENT
    assert tray_state(State.READY, listening=None, running=False, waiting=False) is State.READY
    assert idle_state(listening=None, layout_on=False) is State.LAYOUT_OFF
