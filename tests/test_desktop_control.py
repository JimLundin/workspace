"""The desktop's control decisions, as values: events in, state and effects out."""

from collections.abc import Iterable
from functools import reduce

from contracts.recording_state import RecordingState
from contracts.status import State
from desktop_ui.bar_events import DictationShown, RecordingShown
from desktop_ui.desktop_control import (
    Beep,
    Controlled,
    DesktopState,
    Effect,
    Event,
    Flash,
    HandleKey,
    LayoutReported,
    LayoutShown,
    Log,
    MenuChosen,
    OverlayEnabled,
    OverlayToggled,
    Problem,
    Record,
    RecordingChanged,
    ShowActivity,
    ShowIdle,
    SwitchWindows,
    ToggleMeeting,
    TrayNotify,
    TrayShow,
    UseLayout,
    VoiceShown,
    recording_notice,
    transition,
)
from desktop_ui.desktop_controls import ChosenTool, FeatureRequest, Menu
from protocol import LayoutState, Tool


def folded(events: Iterable[Event], state: DesktopState | None = None) -> tuple[DesktopState, tuple[Effect, ...]]:
    def step(folding: tuple[DesktopState, tuple[Effect, ...]], event: Event) -> tuple[DesktopState, tuple[Effect, ...]]:
        current, effects = folding
        following, produced = transition(current, event)
        return following, (*effects, *produced)

    return reduce(step, events, (state if state is not None else DesktopState(), ()))


def test_the_tray_shows_a_live_recording_before_the_voice_state() -> None:
    # Defect: a live recording is hidden behind the voice state.
    listening, effects = folded((VoiceShown(State.LISTENING),))
    assert effects[-1] == TrayShow(State.LISTENING)
    _, recording = folded((RecordingChanged(RecordingState(phase="recording")),), listening)
    assert TrayShow(State.RECORDING) in recording


def test_voice_state_shows_dictation_on_the_bar_only_while_listening() -> None:
    # Defect: transcription keeps the bar's dictation lit, or listening doesn't light it.
    assert ShowActivity(DictationShown(active=True)) in folded((VoiceShown(State.LISTENING),))[1]
    assert ShowActivity(DictationShown(active=False)) in folded((VoiceShown(State.WORKING),))[1]


def test_recording_warnings_only_announce_interruptions_and_failed_captures() -> None:
    # Defect: an ordinary finish is announced as a warning, or a pause, an
    # interruption or a capture that ended with a problem passes silently.
    recording = RecordingState(phase="recording")
    assert recording_notice(recording, RecordingState(phase="finishing")) is None
    assert recording_notice(recording, RecordingState(phase="finishing", detail="Disk full.")) is not None
    assert recording_notice(recording, RecordingState(phase="interrupted")) is not None
    assert recording_notice(RecordingState(phase="paused"), RecordingState(phase="paused")) is None
    paused = RecordingState(phase="paused")
    state, effects = folded((RecordingChanged(recording), RecordingChanged(paused)))
    assert state.shown.recording == paused
    assert ShowActivity(RecordingShown(paused)) in effects and effects[-1] == ShowIdle()
    assert effects.count(Beep()) == 1 and sum(isinstance(effect, TrayNotify) and effect.warning for effect in effects) == 1


def test_a_problem_is_logged_and_beeps_once_as_a_warning() -> None:
    # Defect: a problem from dictation or meetings is silent, beeps twice, or never reaches the log.
    _, effects = folded((Problem("The disk is full."),))
    assert effects == (Log("The disk is full."), Beep(), TrayNotify("Workspace", "The disk is full.", warning=True))


def test_the_layout_flashes_its_change_but_not_its_quit_and_keeps_a_known_state_over_noise() -> None:
    # Defect: quitting the layout flashes "Layout off", a malformed message turns
    # it (or dictation's view of it) off, or dictation never hears the layout's state.
    state, effects = folded((LayoutReported(LayoutState.ON.value), LayoutReported(99)))
    assert state.layout is LayoutState.ON and state.overlay.layout_on
    assert effects.count(Flash("Layout on")) == 2 and LayoutShown(enabled=True) in effects
    assert effects.count(UseLayout(on=True)) == 2
    _, quitting = folded((LayoutReported(LayoutState.QUIT.value),), state)
    assert not any(isinstance(effect, Flash) for effect in quitting) and LayoutShown(enabled=False) in quitting
    assert UseLayout(on=False) in quitting


def test_dictation_keys_pass_both_edges_and_the_desktops_own_keys_act_on_press() -> None:
    # Defect: a dictation release is dropped (so a hold never stops), a desktop key
    # release acts like a press, or a meeting or window key reaches dictation.
    _, edges = folded((Controlled(FeatureRequest(Tool.DICTATE, down=True)), Controlled(FeatureRequest(Tool.DICTATE, down=False))))
    assert edges == (HandleKey(Tool.DICTATE, down=True), HandleKey(Tool.DICTATE, down=False))
    _, released = folded((Controlled(FeatureRequest(Tool.ZOOM, down=False)), Controlled(FeatureRequest(Tool.MEETING_TOGGLE, down=False))))
    assert released == ()
    _, pressed = folded((Controlled(FeatureRequest(Tool.MEETING_TOGGLE, down=True)), Controlled(ChosenTool(Tool.WINDOW_SWITCHER))))
    assert pressed == (ToggleMeeting(), SwitchWindows())


def test_the_tray_records_meetings_and_opens_their_folder() -> None:
    # Defect: the tray's meeting items do nothing, or open the wrong thing.
    assert folded((MenuChosen(Menu.MEETING.value),))[1] == (ToggleMeeting(),)
    assert folded((MenuChosen(Menu.TRANSCRIPTS.value),))[1] == (Record("folder"),)


def test_the_overlay_menu_choice_toggles_and_saves_the_overlay() -> None:
    # Defect: the tray's overlay item changes the view without saving the setting, or saves the old value.
    for event in (MenuChosen(Menu.OVERLAY.value), OverlayToggled()):
        toggled, effects = folded((event,))
        assert not toggled.overlay.enabled and OverlayEnabled(enabled=False) in effects
    assert folded((MenuChosen(0),))[1] == ()
