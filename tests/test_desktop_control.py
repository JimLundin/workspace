"""The desktop's control decisions, as values: events in, state and effects out."""

from collections.abc import Iterable
from functools import reduce

from contracts.desktop_link import MicLevel, Notify, RecordingChanged, UseTool, VoiceChanged
from contracts.recording_state import RecordingState
from contracts.status import State
from desktop_ui.desktop_control import (
    AssistantSaid,
    Beep,
    Connection,
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
from link.client import Status
from protocol import LayoutState, Tool


def folded(events: Iterable[Event], state: DesktopState | None = None) -> tuple[DesktopState, tuple[Effect, ...]]:
    def step(folding: tuple[DesktopState, tuple[Effect, ...]], event: Event) -> tuple[DesktopState, tuple[Effect, ...]]:
        current, effects = folding
        following, produced = transition(current, event)
        return following, (*effects, *produced)

    return reduce(step, events, (state if state is not None else DesktopState(), ()))


def test_the_tray_shows_recording_first_and_layout_off_while_the_assistant_is_away() -> None:
    # Defect: a live recording is hidden behind the voice state, or a disconnected
    # assistant's last state stays on the tray as if it were still running.
    connected, effects = folded((Connection(Status.CONNECTED), AssistantSaid(VoiceChanged(State.LISTENING, agent_speaking=False))))
    assert effects[-1] == TrayShow(State.LISTENING)
    _, recording = folded((AssistantSaid(RecordingChanged(RecordingState(phase="recording"))),), connected)
    assert recording[-1] == TrayShow(State.RECORDING)
    away, gone = folded((AssistantSaid(MicLevel(0.4)), Connection(Status.DISCONNECTED)), connected)
    assert gone[-1] == TrayShow(State.LAYOUT_OFF) and away.level is None and not away.shown.agent_running


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
    _, released = folded((Controlled(FeatureRequest(Tool.OPEN_INBOX, down=False)),))
    assert released == ()


def test_the_overlay_menu_choice_toggles_and_saves_the_overlay() -> None:
    # Defect: the tray's overlay item changes the view without saving the setting, or saves the old value.
    _, chosen = folded((MenuChosen(Menu.OVERLAY.value),))
    assert chosen == (Fold(OverlayToggled()),)
    toggled, effects = folded((OverlayToggled(),))
    assert not toggled.overlay.enabled and OverlayEnabled(enabled=False) in effects
    assert folded((MenuChosen(0),))[1] == ()
