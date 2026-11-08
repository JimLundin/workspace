"""The desktop's control decisions, as values: events in, state and effects out."""

from collections.abc import Iterable
from functools import reduce

from contracts.desktop_link import Notify, RecordingChanged, UseTool, VoiceChanged
from contracts.recording_state import RecordingState
from contracts.status import State
from desktop_ui.desktop_control import (
    AssistantSaid,
    Beep,
    Controlled,
    DesktopState,
    Effect,
    Event,
    Flash,
    Fold,
    LayoutReported,
    LayoutShown,
    MenuChosen,
    OverlayEnabled,
    OverlayToggled,
    Send,
    ShowViews,
    TrayNotify,
    TrayShow,
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
    listening, effects = folded((AssistantSaid(VoiceChanged(State.LISTENING)),))
    assert effects[-1] == TrayShow(State.LISTENING)
    _, recording = folded((AssistantSaid(RecordingChanged(RecordingState(phase="recording"))),), listening)
    assert recording[-1] == TrayShow(State.RECORDING)


def test_a_warning_from_the_assistant_beeps_once_and_reaches_the_tray_and_the_views() -> None:
    # Defect: a warning is silent, beeps twice, or never reaches the views that show it.
    notice = Notify("Meeting transcript", "Interrupted.", warning=True)
    _, effects = folded((AssistantSaid(notice),))
    assert effects.count(Beep()) == 1
    assert TrayNotify("Meeting transcript", "Interrupted.", warning=True) in effects and ShowViews(notice) in effects


def test_the_layout_flashes_its_change_but_not_its_quit_and_keeps_a_known_state_over_noise() -> None:
    # Defect: quitting the layout flashes "Layout off", or a malformed message turns it off.
    state, effects = folded((LayoutReported(LayoutState.ON.value), LayoutReported(99)))
    assert state.layout is LayoutState.ON and state.overlay.layout_on
    assert effects.count(Flash("Layout on")) == 2 and LayoutShown(enabled=True) in effects
    _, quitting = folded((LayoutReported(LayoutState.QUIT.value),), state)
    assert not any(isinstance(effect, Flash) for effect in quitting) and LayoutShown(enabled=False) in quitting


def test_assistant_tools_go_over_the_link_and_desktop_requests_stay_here() -> None:
    # Defect: a tool the assistant owns is handled locally, or a desktop key release acts like a press.
    _, chosen = folded((Controlled(ChosenTool(Tool.MEETING_TOGGLE)),))
    assert chosen == (Send(UseTool(Tool.MEETING_TOGGLE)),)
    _, released = folded((Controlled(FeatureRequest(Tool.ZOOM, down=False)),))
    assert released == ()


def test_the_overlay_menu_choice_toggles_and_saves_the_overlay() -> None:
    # Defect: the tray's overlay item changes the view without saving the setting, or saves the old value.
    _, chosen = folded((MenuChosen(Menu.OVERLAY.value),))
    assert chosen == (Fold(OverlayToggled()),)
    toggled, effects = folded((OverlayToggled(),))
    assert not toggled.overlay.enabled and OverlayEnabled(enabled=False) in effects
    assert folded((MenuChosen(0),))[1] == ()
