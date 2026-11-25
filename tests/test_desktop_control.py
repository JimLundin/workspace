from collections.abc import Iterable
from functools import reduce

from contracts.recording_state import RecordingState
from contracts.status import State
from desktop_ui.bar_events import DictationShown, RecordingShown
from desktop_ui.desktop_control import (
    Anchored,
    Controlled,
    DesktopState,
    DictationFailed,
    Effect,
    Event,
    FeatureRequest,
    Flash,
    HandleKey,
    LayoutReported,
    LayoutShown,
    Log,
    Menu,
    MenuChosen,
    MenuState,
    OverlayEnabled,
    OverlayToggled,
    PhysicalKey,
    Problem,
    Record,
    RecordingChanged,
    ShowActivity,
    ShowIdle,
    ShowMarker,
    SwitchWindows,
    ToggleMeeting,
    Tracked,
    TrayNotify,
    TrayShow,
    UseLayout,
    VoiceShown,
    control_event,
    menu_items,
    recording_notice,
    transition,
)
from desktop_ui.dictation_marker import UNFOUND, FindAnchor
from keyboard.physical import Scancode
from protocol import LayoutState, Message, Tool
from tests.layouts import APPS
from winapi.caret import Caret
from winapi.shapes import Rect


def folded(
    events: Iterable[Event], state: DesktopState | None = None
) -> tuple[DesktopState, tuple[Effect, ...]]:
    def step(
        folding: tuple[DesktopState, tuple[Effect, ...]], event: Event
    ) -> tuple[DesktopState, tuple[Effect, ...]]:
        current, effects = folding
        following, produced = transition(current, event)
        return following, (*effects, *produced)

    start: tuple[DesktopState, tuple[Effect, ...]] = (
        state if state is not None else DesktopState(),
        (),
    )
    return reduce(step, events, start)


def test_the_tray_shows_a_live_recording_before_the_voice_state() -> None:
    listening, effects = folded((VoiceShown(State.LISTENING),))
    assert effects[-1] == TrayShow(State.LISTENING)
    _, recording = folded(
        (RecordingChanged(RecordingState(phase="recording")),), listening
    )
    assert TrayShow(State.RECORDING) in recording


def test_dictation_shows_on_the_bar_only_when_the_marker_has_nowhere_to_go() -> (
    None
):
    listening, effects = folded((VoiceShown(State.LISTENING),))
    assert ShowActivity(DictationShown(active=False)) in effects
    assert effects.index(ShowMarker(listening.marker)) < effects.index(
        FindAnchor(listening.marker.capture)
    )
    unfound, effects = folded(
        (Anchored(listening.marker.capture, UNFOUND),), listening
    )
    assert ShowActivity(DictationShown(active=True)) in effects
    assert (
        ShowActivity(DictationShown(active=False))
        in folded((VoiceShown(State.WORKING),), unfound)[1]
    )
    _, effects = folded(
        (Anchored(listening.marker.capture, Caret(Rect(10, 10, 12, 30))),),
        listening,
    )
    assert ShowActivity(DictationShown(active=False)) in effects


def test_following_the_caret_redraws_the_marker_only_when_it_moves() -> None:
    at = Caret(Rect(10, 10, 12, 30))
    resting, effects = folded((Tracked(0, at),))
    assert effects == (ShowMarker(resting.marker),)
    assert folded((Tracked(0, at),), resting)[1] == ()


def test_recording_warnings_only_announce_interruptions_and_failed_captures() -> (
    None
):
    recording = RecordingState(phase="recording")
    assert (
        recording_notice(recording, RecordingState(phase="finishing")) is None
    )
    assert (
        recording_notice(
            recording, RecordingState(phase="finishing", detail="Disk full.")
        )
        is not None
    )
    assert (
        recording_notice(recording, RecordingState(phase="interrupted"))
        is not None
    )
    assert (
        recording_notice(
            RecordingState(phase="paused"), RecordingState(phase="paused")
        )
        is None
    )
    paused = RecordingState(phase="paused")
    state, effects = folded(
        (RecordingChanged(recording), RecordingChanged(paused))
    )
    assert state.shown.recording == paused
    assert (
        ShowActivity(RecordingShown(paused)) in effects
        and effects[-1] == ShowIdle()
    )
    assert (
        sum(
            isinstance(effect, TrayNotify) and effect.warning
            for effect in effects
        )
        == 1
    )


def test_a_problem_is_logged_and_shown_once_as_a_warning() -> None:
    for fact in (
        Problem("The disk is full."),
        DictationFailed("The disk is full."),
    ):
        _, effects = folded((fact,))
        assert effects.count(Log("The disk is full.")) == 1
        warnings = [
            effect for effect in effects if isinstance(effect, TrayNotify)
        ]
        assert warnings == [
            TrayNotify("Workspace", "The disk is full.", warning=True)
        ], f"{fact}: {warnings}"


def test_the_layout_flashes_its_change_but_not_its_quit_and_keeps_a_known_state_over_noise() -> (
    None
):
    state, effects = folded(
        (LayoutReported(LayoutState.ON.value), LayoutReported(99))
    )
    assert state.layout is LayoutState.ON and state.overlay.layout_on
    assert (
        sum(isinstance(effect, Flash) for effect in effects) == 2
        and LayoutShown(enabled=True) in effects
    )
    assert effects.count(UseLayout(on=True)) == 2
    _, quitting = folded((LayoutReported(LayoutState.QUIT.value),), state)
    assert (
        not any(isinstance(effect, Flash) for effect in quitting)
        and LayoutShown(enabled=False) in quitting
    )
    assert UseLayout(on=False) in quitting


def test_dictation_keys_pass_both_edges_and_the_desktops_own_keys_act_on_press() -> (
    None
):
    _, edges = folded(
        (
            Controlled(FeatureRequest(Tool.DICTATE, down=True)),
            Controlled(FeatureRequest(Tool.DICTATE, down=False)),
        )
    )
    assert edges == (
        HandleKey(Tool.DICTATE, down=True),
        HandleKey(Tool.DICTATE, down=False),
    )
    _, released = folded(
        (
            Controlled(FeatureRequest(Tool.ZOOM, down=False)),
            Controlled(FeatureRequest(Tool.MEETING_TOGGLE, down=False)),
        )
    )
    assert released == ()
    _, pressed = folded(
        (
            Controlled(FeatureRequest(Tool.MEETING_TOGGLE, down=True)),
            Controlled(FeatureRequest(Tool.WINDOW_SWITCHER, down=True)),
        )
    )
    assert pressed == (ToggleMeeting(), SwitchWindows())


def test_the_tray_records_meetings_and_opens_their_folder() -> None:
    assert folded((MenuChosen(Menu.MEETING.value),))[1] == (ToggleMeeting(),)
    assert folded((MenuChosen(Menu.TRANSCRIPTS.value),))[1] == (
        Record("folder"),
    )


def test_the_overlay_menu_choice_toggles_and_saves_the_overlay() -> None:
    for event in (MenuChosen(Menu.OVERLAY.value), OverlayToggled()):
        toggled, effects = folded((event,))
        assert (
            not toggled.overlay.enabled
            and OverlayEnabled(enabled=False) in effects
        )
    assert folded((MenuChosen(0),))[1] == ()


def test_physical_key_messages_become_key_actions_with_a_reset_marker() -> None:
    actions = tuple(
        control_event(Message.KEY_STATE, key, down, APPS)
        for key, down in ((0x32, 1), (0x10, 1), (0x10, 0), (0, 0))
    )
    assert actions == (
        PhysicalKey(Scancode(0x32), down=True),
        PhysicalKey(Scancode(0x10), down=True),
        PhysicalKey(Scancode(0x10), down=False),
        PhysicalKey(Scancode(0), down=False),
    )
    assert tuple(action.reset for action in actions) == (
        False,
        False,
        False,
        True,
    )


def test_layout_status_is_the_toggle_and_is_checked_while_on() -> None:
    for layout in (LayoutState.ON, LayoutState.OFF):
        state = MenuState(layout=layout, overlay_enabled=True, capturing=False)
        item = next(
            each
            for each in menu_items(state)
            if each.id == Menu.TOGGLE_LAYOUT.value
        )
        assert item.enabled and item.checked == (layout is LayoutState.ON)


def test_stopped_layout_has_a_start_action_and_no_active_toggle_hotkey() -> (
    None
):
    for layout in (None, LayoutState.QUIT):
        state = MenuState(layout=layout, overlay_enabled=True, capturing=False)
        items = {item.id: item for item in menu_items(state)}
        toggle, restart = (
            items[Menu.TOGGLE_LAYOUT.value],
            items[Menu.RESTART_LAYOUT.value],
        )
        assert not toggle.enabled and not toggle.checked and restart.enabled


def test_tray_keeps_saved_meeting_transcripts_reachable_while_recording_or_idle() -> (
    None
):
    for capturing in (False, True):
        state = MenuState(
            layout=LayoutState.ON, overlay_enabled=True, capturing=capturing
        )
        item = next(
            item
            for item in menu_items(state)
            if item.id == Menu.TRANSCRIPTS.value
        )
        assert item.enabled


def test_tray_overlay_item_is_checked_exactly_when_the_overlay_is_enabled() -> (
    None
):
    for enabled in (False, True):
        state = MenuState(
            layout=LayoutState.ON, overlay_enabled=enabled, capturing=False
        )
        item = next(
            item for item in menu_items(state) if item.id == Menu.OVERLAY.value
        )
        assert item.checked is enabled


def test_control_event_preserves_voice_release_and_rejects_unknown_requests() -> (
    None
):
    assert control_event(
        Message.REQUEST, Tool.DICTATE.value, 0, APPS
    ) == FeatureRequest(Tool.DICTATE, down=False)
    assert control_event(Message.REQUEST, 999, 1, APPS) is None
