"""The desktop views' decisions: what the assistant published, folded into what each view shows.

`desktop_ui.ui` turns each publication and each request from the desktop's owner
into an `Event` on the Qt thread's queue and folds it through `transition`, which
returns the next `UiState` and the `Effect`s for the views. Views that don't exist
yet ignore an effect; when the bar is built it reports `BarBuilt`, and the fold
replays what it missed.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace

from contracts.agent_session import ChatMessage, Session, Snapshot, notice_text
from contracts.attention import selected_question
from contracts.canvas_activity import CanvasRequest
from contracts.desktop_link import (
    AutomaticChanged,
    CanvasChanged,
    CanvasStatus,
    JobChanged,
    MeetingPage,
    MicLevel,
    Notify,
    OpenReference,
    RecordingChanged,
    ReplyFailed,
    RouteSpeech,
    RunRefused,
    SessionChanged,
    ShowWork,
    ToDesktop,
    VoiceChanged,
    WorkChanged,
)
from contracts.feed_origin import FeedRequest
from contracts.meeting_detection import AutomaticStatus
from contracts.status import State
from contracts.work_canvas_contracts import CanvasPublication
from desktop_ui.agent_progress import Phase, canvas_phases, hint, phases


@dataclass(frozen=True, slots=True)
class UiState:
    """What the assistant last published that a view built later needs."""

    session: Snapshot = field(default_factory=Session)
    agent_speaking: bool = False
    """Whether the held speech key talks to the agent; a canvas opened during it starts pressed."""
    automatic: AutomaticStatus = AutomaticStatus.OFF
    overlay_enabled: bool = False
    published: CanvasPublication | None = None


# ---- facts --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Published:
    """The assistant published `message`; the tray's notices and the level belong to the desktop's owner."""

    message: ToDesktop


@dataclass(frozen=True, slots=True)
class OverlayPublished:
    enabled: bool


@dataclass(frozen=True, slots=True)
class BarBuilt:
    """The bar exists now and shows nothing yet."""


@dataclass(frozen=True, slots=True)
class InboxOpened:
    """The bell or the inbox key: waiting questions and the agent's recent news, or else the canvas."""


type Fact = Published | OverlayPublished | BarBuilt | InboxOpened

# ---- effects ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BarSession:
    """The bar's agent, requests and notices follow the session."""

    session: Snapshot


@dataclass(frozen=True, slots=True)
class BarDictation:
    active: bool


@dataclass(frozen=True, slots=True)
class CanvasVoice:
    pressed: bool


@dataclass(frozen=True, slots=True)
class BarAutomatic:
    status: AutomaticStatus


@dataclass(frozen=True, slots=True)
class BarOverlay:
    enabled: bool


@dataclass(frozen=True, slots=True)
class PublishCanvas:
    """Every view takes the canvas's publication; a replay to a late view repeats no notice."""

    publication: CanvasPublication
    replay: bool = field(default=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class ShowInbox:
    """Open the bar's inbox with these questions; with none to show, the canvas opens."""

    questions: tuple[Phase, ...]


@dataclass(frozen=True, slots=True)
class Route:
    """Spoken words: a waiting question the session selected takes them, else the canvas decides."""

    text: str
    question: CanvasRequest | None


type ViewMessage = JobChanged | RecordingChanged | WorkChanged | ShowWork | OpenReference | ReplyFailed | MeetingPage | CanvasStatus | RunRefused
"""A publication only one view shows."""


@dataclass(frozen=True, slots=True)
class ToView:
    """A publication only one view shows, delivered as it is if that view exists."""

    message: ViewMessage


type Effect = BarSession | BarDictation | CanvasVoice | BarAutomatic | BarOverlay | PublishCanvas | ShowInbox | Route | ToView


def questions(session: Snapshot, published: CanvasPublication | None) -> tuple[Phase, ...]:
    """The session's own waiting questions, then the canvas's others as previews of their context."""
    asked = tuple(phase for phase in phases(session) if hint(phase.turn))
    if published is None:
        return asked
    routes = frozenset(phase.request for phase in asked)
    preview = Session(
        attention=published.attention,
        messages=tuple(
            ChatMessage(
                "Workspace", notice_text(question.title, question.id), question.created_at, FeedRequest("canvas:" + question.id, question.title)
            )
            for question in published.waiting
            if question.request not in routes
        ),
    )
    return (*asked, *canvas_phases(preview))


def _published(state: UiState, message: ToDesktop) -> Iterator[Effect]:
    match message:
        case SessionChanged(session=session):
            yield BarSession(session)
        case VoiceChanged(state=voice, agent_speaking=speaking):
            # Of the tray's state, the bar shows dictation alone: agent work comes from its session.
            yield BarDictation(active=voice is State.LISTENING)
            yield CanvasVoice(pressed=speaking)
        case AutomaticChanged(status=status):
            yield BarAutomatic(status)
        case CanvasChanged(publication=publication):
            yield PublishCanvas(publication)
        case RouteSpeech(text=text):
            question = selected_question(state.session.attention, state.session.selected_request)
            yield Route(text, question.request if question is not None else None)
        case (
            JobChanged()
            | RecordingChanged()
            | WorkChanged()
            | ShowWork()
            | OpenReference()
            | ReplyFailed()
            | MeetingPage()
            | CanvasStatus()
            | RunRefused()
        ):
            yield ToView(message)
        case MicLevel() | Notify():
            pass


def _replayed(state: UiState) -> Iterator[Effect]:
    """What a freshly built bar missed."""
    yield BarAutomatic(state.automatic)
    yield BarOverlay(state.overlay_enabled)
    if state.published is not None:
        yield PublishCanvas(state.published, replay=True)
    yield BarSession(state.session)


def _remembered(state: UiState, fact: Fact) -> UiState:
    match fact:
        case Published(SessionChanged(session=session)):
            return replace(state, session=session)
        case Published(VoiceChanged(agent_speaking=speaking)):
            return replace(state, agent_speaking=speaking)
        case Published(AutomaticChanged(status=status)):
            return replace(state, automatic=status)
        case Published(CanvasChanged(publication=publication)):
            return replace(state, published=publication)
        case OverlayPublished(enabled):
            return replace(state, overlay_enabled=enabled)
        case _:
            return state


def transition(state: UiState, fact: Fact) -> tuple[UiState, Iterator[Effect]]:
    """The state after `fact` and the view effects it calls for, in order, produced lazily."""
    match fact:
        case Published(message):
            effects = _published(state, message)
        case OverlayPublished(enabled):
            effects = iter((BarOverlay(enabled),))
        case BarBuilt():
            effects = _replayed(state)
        case InboxOpened():
            effects = iter((ShowInbox(questions(state.session, state.published)),))
    return _remembered(state, fact), effects
