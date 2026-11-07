"""The assistant's control decisions: events in, a new state and effects out.

Every part of the assistant reports what happened as an `Event`; none calls back
into the application. The control thread folds each event through `transition`,
which returns the next `ControlState` and the `Effect`s to perform, lazily and in
order. Only `assistant.app` performs effects; this module decides them and touches
nothing, so every reaction can be checked with values alone.

An event is either a fact (`WorkObserved`, `RecordingUpdated`) whose reaction
depends on the state, or a request (`HandleKey`, `Command`): an instruction from a
part, the keys or the desktop that is its own effect and passes straight through.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import assert_never

from assistant.agent_window import AgentWindow
from assistant.meeting_store import MeetingStore
from contracts.attention import AttentionSnapshot
from contracts.canvas_activity import CanvasRun
from contracts.desktop_link import AutomaticChanged, CanvasChanged, JobChanged, Notify, RecordingChanged, ShowWork, ToDesktop, WorkChanged
from contracts.meeting_detection import AutomaticStatus
from contracts.personal_work import Catalog, PersonalView, WorkThread
from contracts.recording_state import Phase, RecordingAction, RecordingState
from contracts.status import Job, State
from contracts.work_canvas_contracts import CanvasPublication
from contracts.work_commands import WorkViewCommand
from contracts.work_snapshot import WorkSnapshot
from protocol import LayoutState, Request, Tool
from winapi.system_notices import Observed

# ---- facts: what happened, whose reaction depends on the state ---------------------


@dataclass(frozen=True, slots=True)
class JobReported:
    job: Job | None


@dataclass(frozen=True, slots=True)
class Notified:
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class Problem:
    """Something failed that the user should hear about; it is also logged."""

    message: str


@dataclass(frozen=True, slots=True)
class WorkObserved:
    snapshot: WorkSnapshot


@dataclass(frozen=True, slots=True)
class PersonalObserved:
    view: PersonalView


@dataclass(frozen=True, slots=True)
class AgentStarted:
    pass


@dataclass(frozen=True, slots=True)
class AgentDone:
    pass


@dataclass(frozen=True, slots=True)
class CanvasPublished:
    publication: CanvasPublication


@dataclass(frozen=True, slots=True)
class RecordingUpdated:
    recording: RecordingState


@dataclass(frozen=True, slots=True)
class AutomaticShown:
    """The automatic-recording attention policy decided the desktop should show this status."""

    status: AutomaticStatus


@dataclass(frozen=True, slots=True)
class AutomaticUnavailable:
    pass


@dataclass(frozen=True, slots=True)
class SessionOpened:
    window: AgentWindow


@dataclass(frozen=True, slots=True)
class WorkShown:
    pass


@dataclass(frozen=True, slots=True)
class LayoutReported:
    value: int
    """The layout's raw `LayoutState`; an unknown value keeps the last known one."""


@dataclass(frozen=True, slots=True)
class Started:
    """The controls run: the capture timer exists and work and personal views have their first values."""

    capture_timer: int
    work: WorkSnapshot
    personal: PersonalView


type Fact = (
    Started
    | JobReported
    | Notified
    | Problem
    | WorkObserved
    | PersonalObserved
    | AgentStarted
    | AgentDone
    | CanvasPublished
    | RecordingUpdated
    | AutomaticShown
    | AutomaticUnavailable
    | SessionOpened
    | WorkShown
    | LayoutReported
)

# ---- requests: instructions that are their own effect --------------------------------


@dataclass(frozen=True, slots=True)
class Show:
    """Show `state` in the tray, unless listening or running agent work takes precedence."""

    state: State


@dataclass(frozen=True, slots=True)
class ContinueRun:
    """The canvas saved a research run that needs its task submitted."""

    run: CanvasRun


@dataclass(frozen=True, slots=True)
class CancelResearch:
    """The user dismissed work; cancel only its research runs."""

    work: WorkThread


@dataclass(frozen=True, slots=True)
class TakeMeeting:
    """Personal work takes in a saved meeting journal."""

    store: MeetingStore


@dataclass(frozen=True, slots=True)
class AttendAutomatic:
    """The automatic meeting monitor's latest status, for its attention policy."""

    status: AutomaticStatus


@dataclass(frozen=True, slots=True)
class Record:
    action: RecordingAction


@dataclass(frozen=True, slots=True)
class RefreshWork:
    pass


@dataclass(frozen=True, slots=True)
class HandleKey:
    request: Request
    down: bool


@dataclass(frozen=True, slots=True)
class ExpireCapture:
    """The control window's capture timer fired."""

    at: float


@dataclass(frozen=True, slots=True)
class Quit:
    pass


@dataclass(frozen=True, slots=True)
class HandleFrame:
    """A command frame from the desktop."""

    frame: bytes


@dataclass(frozen=True, slots=True)
class Speak:
    """Spoken words for the agent: the desktop routes them by its focus, else the conversation takes them."""

    text: str


@dataclass(frozen=True, slots=True)
class ShowAgent:
    pass


@dataclass(frozen=True, slots=True)
class StopAgent:
    pass


@dataclass(frozen=True, slots=True)
class ToggleMeeting:
    pass


@dataclass(frozen=True, slots=True)
class Command:
    command: WorkViewCommand


@dataclass(frozen=True, slots=True)
class Voice:
    """Typed or dictated words for the conversation itself."""

    text: str


@dataclass(frozen=True, slots=True)
class NotifyCanvas:
    title: str
    target: str


@dataclass(frozen=True, slots=True)
class Notices:
    observed: Observed


@dataclass(frozen=True, slots=True)
class Resume:
    task_id: str


type Instruction = (
    Show
    | ContinueRun
    | CancelResearch
    | TakeMeeting
    | AttendAutomatic
    | Record
    | RefreshWork
    | HandleKey
    | ExpireCapture
    | Quit
    | HandleFrame
    | Speak
    | ShowAgent
    | StopAgent
    | ToggleMeeting
    | Command
    | Voice
    | NotifyCanvas
    | Notices
    | Resume
)

type Event = Fact | Instruction
"""Everything a part, Windows or the desktop can tell the assistant."""

# ---- effects that only reactions produce ---------------------------------------------


@dataclass(frozen=True, slots=True)
class Send:
    message: ToDesktop


@dataclass(frozen=True, slots=True)
class Log:
    text: str


@dataclass(frozen=True, slots=True)
class ShowIdle:
    """Show listening, ready or layout-off, whichever state the keys are in."""


@dataclass(frozen=True, slots=True)
class IdleKeys:
    """Return the keys to idle unless a capture is still listening."""


@dataclass(frozen=True, slots=True)
class ObserveWork:
    """The canvas and the feed observe the work journal's latest snapshot."""

    snapshot: WorkSnapshot


@dataclass(frozen=True, slots=True)
class ObserveCatalog:
    catalog: Catalog


@dataclass(frozen=True, slots=True)
class ShowAttention:
    session: AgentWindow
    attention: AttentionSnapshot


@dataclass(frozen=True, slots=True)
class PrepareSession:
    """Open the agent session, if it isn't, and show it the recording."""

    recording: RecordingState


@dataclass(frozen=True, slots=True)
class UseLayout:
    on: bool


type Effect = Instruction | Send | Log | ShowIdle | IdleKeys | ObserveWork | ObserveCatalog | ShowAttention | PrepareSession | UseLayout
"""Something only the application's parts can do."""

# ---- the state the control thread keeps ----------------------------------------------


@dataclass(frozen=True, slots=True)
class ControlState:
    recording_phase: Phase = "idle"
    """The meeting recorder's last phase, to tell an interruption from a finish."""
    layout: LayoutState | None = None
    """What the layout last reported; None until it does."""
    publication: CanvasPublication | None = None
    """The canvas's latest publication, whose attention a new session shows."""
    session: AgentWindow | None = None
    """The agent session, once the work frontend has opened it."""
    work: WorkSnapshot = field(default_factory=WorkSnapshot)
    personal: PersonalView = field(default_factory=PersonalView)
    agent_active: bool = False
    """Agent work has started and not yet finished; the activity tracker reads it."""
    capture_timer: int | None = None
    """The control window's timer that bounds a voice capture, once the controls run."""


AUTOMATIC_UNAVAILABLE = Notify(
    "Automatic Teams recording",
    "Meeting detection is unavailable. Check the browser connection or choose Record a meeting manually.",
    warning=True,
)
CAPTURING: frozenset[Phase] = frozenset({"starting", "recording", "stopping"})


def recording_notice(prior: Phase, recording: RecordingState) -> Notify | None:
    """A warning when a recording pauses, is interrupted, or a capture ends with a problem."""
    failed_capture = prior in CAPTURING and recording.phase == "finishing" and bool(recording.detail)
    if (prior != recording.phase and recording.phase in ("paused", "interrupted")) or failed_capture:
        detail = recording.detail or "Recording was interrupted. Choose Open meeting transcripts for the saved part."
        return Notify("Meeting transcript", detail, warning=True)
    return None


def _reacted(state: ControlState, fact: Fact) -> Iterator[Effect]:
    """The effects of `fact` given the state it arrived in."""
    match fact:
        case Started(work=work, personal=personal):
            yield Send(WorkChanged(replace(work, personal=personal)))
        case JobReported(job):
            yield Send(JobChanged(job))
        case Notified(title, text):
            yield Send(Notify(title, text))
        case Problem(message):
            yield Log(message)
            yield Send(Notify("Workspace", message, warning=True))
        case WorkObserved(snapshot):
            yield ObserveWork(snapshot)
            yield Send(WorkChanged(replace(snapshot, personal=state.personal)))
        case PersonalObserved(view):
            yield ObserveCatalog(view.catalog)
            yield Send(WorkChanged(replace(state.work, personal=view)))
        case AgentStarted():
            yield Show(State.AGENT)
        case AgentDone():
            yield IdleKeys()
        case CanvasPublished(publication):
            if state.session is not None:
                yield ShowAttention(state.session, publication.attention)
            yield Send(CanvasChanged(publication))
        case RecordingUpdated(recording):
            yield Send(RecordingChanged(recording))
            yield PrepareSession(recording)
            if (notice := recording_notice(state.recording_phase, recording)) is not None:
                yield Send(notice)
            yield ShowIdle()
        case AutomaticShown(status):
            yield Send(AutomaticChanged(status))
        case AutomaticUnavailable():
            yield Send(AUTOMATIC_UNAVAILABLE)
        case SessionOpened(window):
            if state.publication is not None:
                yield ShowAttention(window, state.publication.attention)
        case WorkShown():
            yield Send(ShowWork(focus=True))
            yield RefreshWork()
        case LayoutReported():
            yield UseLayout(on=_layout(fact, state) is LayoutState.ON)
        case _:
            assert_never(fact)


def _layout(reported: LayoutReported, state: ControlState) -> LayoutState | None:
    try:
        return LayoutState(reported.value)
    except ValueError:
        return state.layout


def _remembered(state: ControlState, fact: Fact) -> ControlState:
    """The state after `fact`; most facts change nothing the control thread keeps."""
    match fact:
        case Started(timer, work, personal):
            return replace(state, capture_timer=timer, work=work, personal=personal)
        case WorkObserved(snapshot):
            return replace(state, work=snapshot)
        case PersonalObserved(view):
            return replace(state, personal=view)
        case AgentStarted():
            return replace(state, agent_active=True)
        case AgentDone():
            return replace(state, agent_active=False)
        case CanvasPublished(publication):
            return replace(state, publication=publication)
        case RecordingUpdated(recording):
            return replace(state, recording_phase=recording.phase)
        case SessionOpened(window):
            return replace(state, session=window)
        case LayoutReported():
            return replace(state, layout=_layout(fact, state))
        case _:
            return state


def transition(state: ControlState, event: Event) -> tuple[ControlState, Iterator[Effect]]:
    """The state after `event` and the effects it calls for, in order, produced lazily."""
    match event:
        case (
            Show()
            | ContinueRun()
            | CancelResearch()
            | TakeMeeting()
            | AttendAutomatic()
            | Record()
            | RefreshWork()
            | HandleKey()
            | ExpireCapture()
            | Quit()
            | HandleFrame()
            | Speak()
            | ShowAgent()
            | StopAgent()
            | ToggleMeeting()
            | Command()
            | Voice()
            | NotifyCanvas()
            | Notices()
            | Resume()
        ):
            return state, iter((event,))
        case _:
            return _remembered(state, event), _reacted(state, event)


def tray_state(requested: State, *, listening: Tool | None, running: bool, waiting: bool) -> State:
    """What the tray shows: a live capture first, then running agent work over a resting state."""
    if listening is not None:
        return State.LISTENING
    if requested in (State.READY, State.LAYOUT_OFF) and running:
        return State.NEEDS_INPUT if waiting else State.AGENT
    return requested


def idle_state(*, listening: Tool | None, layout_on: bool) -> State:
    """What the keys rest in: listening, ready, or the layout switched off."""
    return State.LISTENING if listening is not None else State.READY if layout_on else State.LAYOUT_OFF
