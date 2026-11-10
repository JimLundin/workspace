"""The dictation marker's decisions: which step it shows, where, and when the bar shows dictation instead.

The marker appears beside the caret of the app you dictate into and stays
where the capture started. It shows listening, then transcribing and typing,
then a brief tick or cross. Each capture looks for its caret once
(`FindAnchor`); the first answer for the current capture wins. When nothing
can be found the bar shows dictation as before.
"""

from dataclasses import dataclass, replace
from enum import Enum, auto

from contracts.status import TRANSCRIBING, TYPING, Job
from winapi.caret import Anchor, Caret, Field, Window
from winapi.shapes import Rect, Size

PROBING = sentinel("PROBING")
"""The capture's anchor is being looked for; neither the marker nor the bar shows it yet."""
UNFOUND = sentinel("UNFOUND")
"""Nothing to anchor to: the bar shows dictation."""

type Where = Anchor | PROBING | UNFOUND


class Outcome(Enum):
    """How the last dictation ended, flashed briefly once it has."""

    DONE = auto()
    FAILED = auto()


class Step(Enum):
    LISTENING = auto()
    TRANSCRIBING = auto()
    TYPING = auto()


type Shown = Step | Outcome

_STEPS: frozendict[Job, Step] = frozendict({TRANSCRIBING: Step.TRANSCRIBING, TYPING: Step.TYPING})
"""The step each of dictation's jobs shows."""


@dataclass(frozen=True, slots=True)
class MarkerState:
    listening: bool = False
    job: Job | None = None
    """Dictation's quick job, as it reports it."""
    flash: Outcome | None = None
    capture: int = 0
    """Counts captures, so an anchor found for an earlier one is dropped."""
    where: Where = UNFOUND


@dataclass(frozen=True, slots=True)
class FindAnchor:
    """Look for where `capture`'s text will go, and report it as `anchored`."""

    capture: int


def listened(state: MarkerState, *, listening: bool) -> MarkerState:
    """A capture starting looks for its anchor afresh and drops any flash."""
    if listening and not state.listening:
        return replace(state, listening=True, flash=None, capture=state.capture + 1, where=PROBING)
    return replace(state, listening=listening)


def found(state: MarkerState, after: MarkerState) -> FindAnchor | None:
    """The look for an anchor a new capture asks for."""
    return FindAnchor(after.capture) if after.capture != state.capture else None


def job_changed(state: MarkerState, job: Job | None) -> MarkerState:
    """Typing that ends without a failure is done; a new job ends any flash."""
    if job is not None:
        return replace(state, job=job, flash=None)
    finished = state.job is TYPING and state.flash is not Outcome.FAILED and not state.listening
    return replace(state, job=None, flash=Outcome.DONE if finished else state.flash)


def failed(state: MarkerState) -> MarkerState:
    """A failure flashes only where dictation is showing; the tray reports every failure."""
    return replace(state, flash=Outcome.FAILED) if shown(state) is not None else state


def anchored(state: MarkerState, capture: int, where: Anchor | UNFOUND) -> MarkerState:
    """The first answer for the current capture places it; later and stale answers are dropped."""
    return replace(state, where=where) if capture == state.capture and state.where is PROBING else state


def faded(state: MarkerState) -> MarkerState:
    return replace(state, flash=None)


def shown(state: MarkerState) -> Shown | None:
    """What dictation is doing: listening takes precedence over a job, and a job over a flash."""
    if state.listening:
        return Step.LISTENING
    return _STEPS[state.job] if state.job is not None else state.flash


def marked(state: MarkerState) -> tuple[Anchor, Shown] | None:
    """Where the marker shows and what, or None while it's hidden."""
    match state.where:
        case Caret() | Field() | Window() as anchor if (step := shown(state)) is not None:
            return anchor, step
        case _:
            return None


def on_bar(state: MarkerState) -> bool:
    """The bar shows dictation only when nothing was found to anchor the marker to."""
    return state.where is UNFOUND


def _clamped(x: int, y: int, size: Size, work: Rect) -> Rect:
    left = max(work.left, min(x, work.right - size.width))
    top = max(work.top, min(y, work.bottom - size.height))
    return Rect(left, top, left + size.width, top + size.height)


def placed(anchor: Anchor, size: Size, work: Rect, gap: int) -> Rect:
    """The marker's rect on screen: above the caret or outside the field's corner when there's room, else just inside;
    top-centre inside a window; always within `work`."""
    match anchor:
        case Caret(rect):
            above = rect.top - gap - size.height
            return _clamped(rect.left, above if above >= work.top else rect.bottom + gap, size, work)
        case Field(rect):
            above = rect.top - gap - size.height
            return _clamped(rect.left, above, size, work) if above >= work.top else _clamped(rect.left + gap, rect.top + gap, size, work)
        case Window(rect):
            return _clamped(rect.left + (rect.width - size.width) // 2, rect.top + gap, size, work)
