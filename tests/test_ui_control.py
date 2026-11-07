"""The desktop views' decisions, as values: what a late-built bar replays and where speech goes."""

from contracts.agent_session import Session
from contracts.desktop_link import AutomaticChanged, CanvasChanged, JobChanged, RouteSpeech, VoiceChanged
from contracts.meeting_detection import AutomaticStatus
from contracts.status import State
from contracts.work_canvas_contracts import CanvasPublication
from contracts.work_canvas_model import CanvasDocument
from desktop_ui.ui_control import (
    BarAutomatic,
    BarBuilt,
    BarDictation,
    BarOverlay,
    BarSession,
    CanvasVoice,
    OverlayPublished,
    PublishCanvas,
    Published,
    Route,
    ToView,
    UiState,
    transition,
)


def test_a_bar_built_late_replays_what_it_missed_without_repeating_the_notice() -> None:
    # Defect: the bar built after publications shows an old automatic, overlay or
    # canvas state, or the replayed canvas announces its notice a second time.
    publication = CanvasPublication(CanvasDocument(), (), frozenset())
    state = UiState()
    for fact in (Published(AutomaticChanged(AutomaticStatus.CHECKING)), OverlayPublished(enabled=True), Published(CanvasChanged(publication))):
        state, _ = transition(state, fact)
    _, replayed = transition(state, BarBuilt())
    assert tuple(replayed) == (
        BarAutomatic(AutomaticStatus.CHECKING),
        BarOverlay(enabled=True),
        PublishCanvas(publication, replay=True),
        BarSession(Session()),
    )


def test_voice_state_shows_dictation_on_the_bar_and_agent_speech_on_the_canvas() -> None:
    # Defect: agent speech lights the bar's dictation, or a canvas opened mid-speech starts unpressed.
    state, effects = transition(UiState(), Published(VoiceChanged(State.LISTENING, agent_speaking=True)))
    assert tuple(effects) == (BarDictation(active=True), CanvasVoice(pressed=True)) and state.agent_speaking


def test_speech_without_a_selected_question_goes_to_the_canvas_to_decide() -> None:
    # Defect: spoken words answer an unselected question, or are dropped.
    _, effects = transition(UiState(), Published(RouteSpeech("Use the newer plan.")))
    assert tuple(effects) == (Route("Use the newer plan.", None),)


def test_a_publication_for_one_view_reaches_it_unchanged() -> None:
    # Defect: a job change is lost on its way to the bar.
    _, effects = transition(UiState(), Published(JobChanged(None)))
    assert tuple(effects) == (ToView(JobChanged(None)),)
