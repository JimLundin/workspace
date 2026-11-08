"""The assistant's control decisions: events in, a new state and effects out.

Every part of the assistant reports what happened as an `Event`; none calls back
into the application. The control thread folds each event through `transition`,
which returns the next `ControlState` and the `Effect`s to perform, lazily and in
order. Only `assistant.app` performs effects; this module decides them and touches
nothing, so every reaction can be checked with values alone.

An event is either a fact (`RecordingUpdated`, `LayoutReported`) whose reaction
depends on the state, or a request (`HandleKey`, `Record`): an instruction from a
part, the keys or the desktop that is its own effect and passes straight through.
"""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import assert_never

from contracts.desktop_link import JobChanged, Notify, RecordingChanged, ToDesktop
from contracts.recording_state import Phase, RecordingAction, RecordingState
from contracts.status import Job, State
from protocol import LayoutState, Request, Tool

# ---- facts: what happened, whose reaction depends on the state ---------------------


@dataclass(frozen=True, slots=True)
class Started:
    """The controls run, with the capture timer that bounds a voice capture."""

    capture_timer: int


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
class RecordingUpdated:
    recording: RecordingState


@dataclass(frozen=True, slots=True)
class LayoutReported:
    value: int
    """The layout's raw `LayoutState`; an unknown value keeps the last known one."""


type Fact = Started | JobReported | Notified | Problem | RecordingUpdated | LayoutReported

# ---- requests: instructions that are their own effect --------------------------------


@dataclass(frozen=True, slots=True)
class Show:
    """Show `state` in the tray, unless listening takes precedence."""

    state: State


@dataclass(frozen=True, slots=True)
class Record:
    action: RecordingAction


@dataclass(frozen=True, slots=True)
class ToggleMeeting:
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
class HandleFrame:
    """A command frame from the desktop."""

    frame: bytes


@dataclass(frozen=True, slots=True)
class Quit:
    pass


type Instruction = Show | Record | ToggleMeeting | HandleKey | ExpireCapture | HandleFrame | Quit

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
class UseLayout:
    on: bool


type Effect = Instruction | Send | Log | ShowIdle | UseLayout
"""Something only the application's parts can do."""

# ---- the state the control thread keeps ----------------------------------------------


@dataclass(frozen=True, slots=True)
class ControlState:
    recording_phase: Phase = "idle"
    """The meeting recorder's last phase, to tell an interruption from a finish."""
    layout: LayoutState | None = None
    """What the layout last reported; None until it does."""
    capture_timer: int | None = None
    """The control window's timer that bounds a voice capture, once the controls run."""


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
        case Started():
            yield ShowIdle()
        case JobReported(job):
            yield Send(JobChanged(job))
        case Notified(title, text):
            yield Send(Notify(title, text))
        case Problem(message):
            yield Log(message)
            yield Send(Notify("Workspace", message, warning=True))
        case RecordingUpdated(recording):
            yield Send(RecordingChanged(recording))
            if (notice := recording_notice(state.recording_phase, recording)) is not None:
                yield Send(notice)
            yield ShowIdle()
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
        case Started(timer):
            return replace(state, capture_timer=timer)
        case RecordingUpdated(recording):
            return replace(state, recording_phase=recording.phase)
        case LayoutReported():
            return replace(state, layout=_layout(fact, state))
        case _:
            return state


def transition(state: ControlState, event: Event) -> tuple[ControlState, Iterator[Effect]]:
    """The state after `event` and the effects it calls for, in order, produced lazily."""
    match event:
        case Show() | Record() | ToggleMeeting() | HandleKey() | ExpireCapture() | HandleFrame() | Quit():
            return state, iter((event,))
        case _:
            return _remembered(state, event), _reacted(state, event)


def idle_state(*, listening: Tool | None, layout_on: bool) -> State:
    """What the keys rest in: listening, ready, or the layout switched off."""
    return State.LISTENING if listening is not None else State.READY if layout_on else State.LAYOUT_OFF
