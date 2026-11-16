"""The dictation marker's decisions, as values: what it shows, where, and when the bar shows dictation instead."""

from dataclasses import replace

from contracts.status import TRANSCRIBING, TYPING
from desktop_ui.dictation_marker import (
    PROBING,
    RESTING,
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
    rested,
    tracked,
    tracking,
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
    finished = faded(
        job_changed(
            job_changed(listened(started(), listening=False), TYPING), None
        )
    )
    assert marked(failed(finished)) is None


def test_an_earlier_dictation_finishing_during_a_capture_doesnt_flash_after_it() -> (
    None
):
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


def test_the_marker_sits_on_the_caret_and_stays_on_screen_at_the_top() -> None:
    # Defect: the marker drifts off the caret's line, or leaves the screen near its top.
    assert placed(CARET, SIZE, WORK, 6) == Rect(341, 294, 461, 326)
    top = Caret(Rect(400, 2, 402, 22))
    assert placed(top, SIZE, WORK, 6) == Rect(341, 0, 461, 32)


def test_the_marker_stays_on_its_monitor() -> None:
    # Defect: a caret at the right edge, or on a monitor left of and above the primary, puts the marker off screen.
    left_monitor = Rect(-1280, -200, 0, 824)
    edge = Caret(Rect(-5, 400, -3, 420))
    assert placed(edge, SIZE, left_monitor, 6) == Rect(-120, 394, 0, 426)
    corner = Field(Rect(-1280, -200, -600, -150))
    assert placed(corner, SIZE, left_monitor, 6) == Rect(
        -1274, -194, -1154, -162
    )


def test_a_field_is_marked_outside_its_corner_and_a_window_at_its_bottom_left() -> (
    None
):
    # Defect: the marker hides the field's text when there's room above it, or covers a window's key hints.
    assert placed(Field(Rect(100, 200, 700, 260)), SIZE, WORK, 6) == Rect(
        100, 162, 220, 194
    )
    assert placed(Window(Rect(100, 100, 1100, 900)), SIZE, WORK, 6) == Rect(
        106, 862, 226, 894
    )


def test_a_pane_sized_field_is_marked_at_its_bottom_left() -> None:
    # Defect: a browser page or editor pane reported as the focused field puts the marker over the key hints.
    pane = Field(Rect(100, 100, 1100, 900))
    assert placed(pane, SIZE, WORK, 6) == Rect(106, 862, 226, 894)


def test_the_marker_rests_beside_the_followed_caret_between_dictations() -> (
    None
):
    # Defect: the resting marker hides when a caret is found, stays after it's lost, or moves during a capture.
    resting = tracked(IDLE, IDLE.capture, CARET)
    assert marked(resting) == (CARET, RESTING)
    assert marked(tracked(resting, IDLE.capture, None)) is None
    assert tracking(resting)
    listening = listened(resting, listening=True)
    assert not tracking(listening)
    assert not tracking(
        job_changed(listened(listening, listening=False), TRANSCRIBING)
    )


def test_a_capture_starts_on_the_resting_caret_without_looking() -> None:
    # Defect: a capture with a known caret waits for a lookup, or flickers onto the bar while it runs.
    resting = tracked(IDLE, IDLE.capture, CARET)
    after = listened(resting, listening=True)
    assert found(resting, after) is None
    assert marked(after) == (CARET, Step.LISTENING)
    assert not on_bar(after)


def test_the_tick_follows_the_caret_to_where_the_text_ended() -> None:
    # Defect: the tick stays over the start of the typed text, a failure or a window-marked capture moves,
    # or a late answer asked before a capture moves it.
    typing = job_changed(listened(started(), listening=False), TYPING)
    done = job_changed(typing, None)
    ended = Caret(Rect(520, 300, 522, 320))
    assert marked(tracked(done, done.capture, ended)) == (ended, Outcome.DONE)
    assert marked(tracked(done, done.capture, None)) == (CARET, Outcome.DONE)
    failure = job_changed(failed(typing), None)
    assert marked(tracked(failure, failure.capture, ended)) == (
        CARET,
        Outcome.FAILED,
    )
    window = Window(Rect(0, 0, 800, 600))
    on_window = job_changed(replace(typing, where=window), None)
    assert marked(tracked(on_window, on_window.capture, ended)) == (
        window,
        Outcome.DONE,
    )
    assert tracked(started(done), done.capture, ended) == started(done)
    rests = faded(tracked(done, done.capture, ended))
    assert marked(rests) == (ended, RESTING)


def test_the_resting_marker_sits_left_of_the_caret_on_its_monitor() -> None:
    # Defect: the resting marker covers the caret, or leaves the screen at a line's start.
    assert rested(CARET, SIZE, WORK, 6) == Rect(274, 294, 394, 326)
    start = Caret(Rect(2, 300, 4, 320))
    assert rested(start, SIZE, WORK, 6) == Rect(0, 294, 120, 326)
