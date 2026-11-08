"""The desktop views' decisions, as values: what a late-built bar replays and where speech goes."""

from dataclasses import replace

from contracts import agent_session
from contracts.agent_session import Begin, Resolution, Session
from contracts.attention import observed_attention
from contracts.canvas_activity import Attention, CanvasQuestion, TaskRequest
from contracts.desktop_link import AutomaticChanged, CanvasChanged, JobChanged, RouteSpeech, SessionChanged, VoiceChanged
from contracts.meeting_detection import AutomaticStatus
from contracts.personal_work import Catalog
from contracts.status import State
from contracts.task import TextAnswer
from contracts.work_canvas_contracts import CanvasPublication
from contracts.work_canvas_model import CanvasDocument
from desktop_ui.ui_control import (
    BarAutomatic,
    BarBuilt,
    BarDictation,
    BarOverlay,
    BarSession,
    CanvasVoice,
    InboxOpened,
    OverlayPublished,
    PublishCanvas,
    Published,
    Route,
    ShowInbox,
    ToView,
    UiState,
    transition,
)
from tests import agent_requests


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


def test_speech_answers_the_question_the_session_selected_while_it_waits() -> None:
    # Defect: a spoken reply to the open request goes to the conversation or the
    # canvas instead of the exact waiting owner, or still goes there once answered.
    asked = CanvasQuestion("question:sheet", "Which sheet?", "Revenue or costs.", 3, TaskRequest("review", "sheet"), Attention.WAITING, ())
    attention = observed_attention(Catalog(), CanvasDocument(activity=(asked,)))
    session = replace(Session(), attention=attention, selected_request=asked.request)
    state, _ = transition(UiState(), Published(SessionChanged(session)))
    _, effects = transition(state, Published(RouteSpeech("Revenue")))
    assert tuple(effects) == (Route("Revenue", asked.request),)
    unselected, _ = transition(state, Published(SessionChanged(replace(session, selected_request=None))))
    _, effects = transition(unselected, Published(RouteSpeech("Revenue")))
    assert tuple(effects) == (Route("Revenue", None),)


def test_the_inbox_lists_only_questions_the_agent_is_waiting_on() -> None:
    # Defect: routine arrivals count as attention, or an answered question still
    # waits in the bell.
    started = agent_session.transition(Session(identity="review"), Begin("Check the budget", 1))
    waiting = agent_session.transition(started, agent_requests.asked("owned", "Which sheet?", "", 3))
    for session, count in ((started, 0), (waiting, 1), (agent_session.transition(waiting, Resolution("owned", TextAnswer("Revenue"))), 0)):
        state, _ = transition(UiState(), Published(SessionChanged(session)))
        _, effects = transition(state, InboxOpened())
        match tuple(effects):
            case (ShowInbox(questions=shown),):
                assert len(shown) == count
            case other:
                raise AssertionError(other)


def test_the_canvas_voice_key_is_pressed_only_while_the_agent_hears_speech() -> None:
    # Defect: background work clears the held key, release leaves it pressed
    # during transcription, dictation lights the agent key, or a canvas opened
    # mid-speech starts unpressed (the canvas reads `agent_speaking` when built).
    state = UiState()
    for voice, speaking in (
        (State.LISTENING, True),
        (State.LISTENING, True),
        (State.WORKING, False),
        (State.AGENT, False),
        (State.LISTENING, False),
        (State.LISTENING, True),
    ):
        state, effects = transition(state, Published(VoiceChanged(voice, agent_speaking=speaking)))
        assert CanvasVoice(pressed=speaking) in tuple(effects) and state.agent_speaking is speaking
