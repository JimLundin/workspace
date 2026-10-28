"""A quiet resting toolbar, with independent controls for simultaneous activities."""

from assistant.bar_model import Activity, Resting, toolbar
from assistant.icons import State
from assistant.recording_state import RecordingState


def test_idle_has_an_ambient_presentation_and_no_auxiliary_capsules() -> None:
    view = toolbar(State.READY, RecordingState(), enabled=True, layer=None)
    assert isinstance(view.activity, Resting)
    assert view.capture is None and view.keyboard is None


def test_listening_and_meeting_capture_remain_independently_visible() -> None:
    view = toolbar(State.LISTENING, RecordingState(phase="recording", seconds=125), enabled=True, layer=None)
    assert isinstance(view.activity, Activity)
    assert view.activity.title == "Listening"
    assert view.activity.can_stop
    assert view.capture is not None and view.capture.title == "02:05" and view.capture.can_stop
    working = toolbar(State.AGENT, RecordingState(phase="recording", seconds=125), enabled=True, layer=None)
    assert isinstance(working.activity, Activity)
    assert working.activity.can_stop and working.capture == view.capture


def test_only_temporary_keyboard_modes_occupy_space() -> None:
    for state in (State.READY, State.AGENT):
        assert toolbar(state, RecordingState(), enabled=True, layer="NAV · locked").keyboard == "NAV · locked"
        assert toolbar(state, RecordingState(), enabled=False, layer=None).keyboard == "Colemak"
        assert toolbar(state, RecordingState(), enabled=True, layer=None).keyboard is None


def test_capture_retracts_after_save_and_stopping_cannot_be_repeated() -> None:
    for recording in (RecordingState(phase="stopping"), RecordingState(phase="finishing")):
        view = toolbar(State.READY, recording, enabled=True, layer=None)
        assert view.capture is not None and not view.capture.can_stop
    saved = toolbar(State.READY, RecordingState(phase="saved", seconds=900), enabled=True, layer=None)
    assert saved.capture is None
