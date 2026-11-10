"""The dictation marker's decisions, as values: what it shows, where, and when the bar shows dictation instead."""

from contracts.status import TRANSCRIBING, TYPING
from desktop_ui.dictation_marker import (
    PROBING,
    UNFOUND,
    FindAnchor,
    MarkerState,
    Outcome,
    Step,
    anchored,
    faded,
    failed,
    found,
    job_changed,
    listened,
    marked,
    on_bar,
    placed,
)
from winapi.caret import Caret, Field, Window
from winapi.shapes import Rect, Size

CARET = Caret(Rect(400, 300, 402, 320))
WORK = Rect(0, 0, 1920, 1160)
SIZE = Size(120, 32)


IDLE = MarkerState()


def started(state: MarkerState = IDLE) -> MarkerState:
    after = listened(state, listening=True)
    assert found(state, after) == FindAnchor(after.capture)
    return anchored(after, after.capture, CARET)


def test_a_dictation_shows_each_step_at_its_caret_then_done() -> None:
    # Defect: the marker skips a step, shows nothing once listening ends, or never says it's done.
    state = started()
    assert marked(state) == (CARET, Step.LISTENING)
    state = job_changed(listened(state, listening=False), TRANSCRIBING)
    assert marked(state) == (CARET, Step.TRANSCRIBING)
    state = job_changed(state, TYPING)
    assert marked(state) == (CARET, Step.TYPING)
    state = job_changed(state, None)
    assert marked(state) == (CARET, Outcome.DONE)
    assert marked(faded(state)) is None


def test_a_failure_flashes_instead_of_done() -> None:
    # Defect: a failed transcription ends with a tick, or its cross is replaced when the job ends.
    state = job_changed(listened(started(), listening=False), TRANSCRIBING)
    state = job_changed(failed(state), None)
    assert marked(state) == (CARET, Outcome.FAILED)


def test_a_capture_too_short_to_transcribe_just_hides() -> None:
    # Defect: a discarded capture leaves the marker listening, or flashes an outcome nothing had.
    state = job_changed(listened(started(), listening=False), None)
    assert marked(state) is None


def test_a_failure_with_nothing_showing_stays_in_the_tray() -> None:
    # Defect: a capture that couldn't start flashes a cross at the previous dictation's caret.
    finished = faded(job_changed(job_changed(listened(started(), listening=False), TYPING), None))
    assert marked(failed(finished)) is None


def test_an_earlier_dictation_finishing_during_a_capture_doesnt_flash_after_it() -> None:
    # Defect: the previous dictation's tick appears once the new capture ends.
    typing = job_changed(listened(started(), listening=False), TYPING)
    state = job_changed(started(typing), None)
    assert marked(state) == (CARET, Step.LISTENING)
    assert marked(job_changed(listened(state, listening=False), None)) is None


def test_only_the_current_captures_first_anchor_places_it() -> None:
    # Defect: a slow answer for an earlier capture, or the fallback arriving after the caret, moves the marker.
    first = listened(MarkerState(), listening=True)
    second = listened(listened(first, listening=False), listening=True)
    window = Window(Rect(0, 0, 800, 600))
    assert anchored(second, first.capture, window).where is PROBING
    placed_once = anchored(second, second.capture, CARET)
    assert anchored(placed_once, second.capture, window).where == CARET


def test_the_bar_shows_dictation_only_when_nothing_was_found() -> None:
    # Defect: both the bar and the marker show a capture, the bar flickers while the caret is looked for,
    # or a capture with no anchor shows nowhere.
    probing = listened(MarkerState(), listening=True)
    assert not on_bar(probing)
    assert not on_bar(anchored(probing, probing.capture, CARET))
    unfound = anchored(probing, probing.capture, UNFOUND)
    assert on_bar(unfound)
    assert marked(unfound) is None


def test_the_marker_sits_above_the_caret_or_below_it_at_the_top() -> None:
    # Defect: the marker covers the line being dictated into, or leaves the screen near its top.
    gap = 6
    assert placed(CARET, SIZE, WORK, gap) == Rect(400, 262, 520, 294)
    top = Caret(Rect(400, 10, 402, 30))
    assert placed(top, SIZE, WORK, gap) == Rect(400, 36, 520, 68)


def test_the_marker_stays_on_its_monitor() -> None:
    # Defect: a caret at the right edge, or on a monitor left of and above the primary, puts the marker off screen.
    left_monitor = Rect(-1280, -200, 0, 824)
    edge = Caret(Rect(-5, 400, -3, 420))
    assert placed(edge, SIZE, left_monitor, 6) == Rect(-120, 362, 0, 394)
    corner = Field(Rect(-1280, -200, -600, 300))
    assert placed(corner, SIZE, left_monitor, 6) == Rect(-1274, -194, -1154, -162)


def test_a_field_is_marked_outside_its_corner_and_a_window_at_its_top() -> None:
    # Defect: the marker hides the field's text when there's room above it, or sits off-centre on a window.
    assert placed(Field(Rect(100, 200, 700, 260)), SIZE, WORK, 6) == Rect(100, 162, 220, 194)
    assert placed(Window(Rect(100, 100, 1100, 900)), SIZE, WORK, 6) == Rect(540, 106, 660, 138)
