"""When the away-screens owner darkens and restores the protected screens, and which ones it turns back on."""

from collections.abc import Iterable, Iterator
from unittest import TestCase

from desktop_ui.away_screens import Darken, Presence, Reason, Restore, Setting, dark_after, idle_delay, step
from winapi.monitor_power import Detached, Power, Unanswered
from winapi.presence import elapsed
from winapi.screen import Monitor
from winapi.shapes import Rect

FOUR_K = Monitor(Rect(1920, -269, 5760, 1891), Rect(1920, -269, 5760, 1891), primary=False, internal=False)
SECOND = Monitor(Rect(-3840, 0, 0, 2160), Rect(-3840, 0, 0, 2160), primary=False, internal=False)
ON, OFF = Setting(120_000, enabled=True), Setting(120_000, enabled=False)


def present(idle_ms: int, *, locked: bool = False, display_required: bool = False) -> Presence:
    return Presence(idle_ms, locked=locked, display_required=display_required)


def stepped(readings: Iterable[Presence], setting: Setting) -> Iterator[Darken | Restore | None]:
    held: Reason | None = None
    for reading in readings:
        held, change = step(held, reading, setting)
        yield change


def changes(readings: Iterable[Presence], setting: Setting = ON) -> tuple[Darken | Restore | None, ...]:
    """Each poll's change, as the owner steps through successive readings."""
    return tuple(stepped(readings, setting))


def test_idle_darkens_after_the_delay_and_the_next_input_wakes() -> None:
    # Defects: darkening before the delay, darkening again on every poll, or waiting for more than one input to wake.
    readings = (present(0), present(119_999), present(120_000), present(150_000), present(40))
    assert changes(readings) == (None, None, Darken(Reason.IDLE), None, Restore(Reason.IDLE))


def test_a_program_needing_the_display_holds_off_idleness_but_not_the_lock() -> None:
    # Defects: a video or call goes dark mid-watch, a newly started one stays dark, or a requested display survives the lock.
    readings = (present(130_000, display_required=True), present(140_000), present(150_000, display_required=True))
    assert changes(readings) == (None, Darken(Reason.IDLE), Restore(Reason.IDLE))
    assert changes((present(0, locked=True, display_required=True),)) == (Darken(Reason.LOCKED),)


def test_lock_and_idleness_overlap_until_neither_holds() -> None:
    # Defects: unlocking restores a screen that has been idle past the delay, or input on the lock screen wakes it.
    idle_then_locked = (present(130_000), present(140_000, locked=True), present(150_000), present(10))
    assert changes(idle_then_locked) == (Darken(Reason.IDLE), None, None, Restore(Reason.IDLE))
    typing_while_locked = (present(0, locked=True), present(30, locked=True), present(50))
    assert changes(typing_while_locked) == (Darken(Reason.LOCKED), None, Restore(Reason.LOCKED))


def test_turning_it_off_restores_and_keeps_screens_lit() -> None:
    # Defect: the toggle stops new darkening but leaves a dark screen dark, or still darkens on lock.
    assert step(Reason.IDLE, present(130_000), OFF) == (None, Restore(Reason.IDLE))
    assert changes((present(0, locked=True), present(130_000)), OFF) == (None, None)


def test_idle_time_spans_the_32_bit_tick_wrap() -> None:
    # Defect: subtracting the 32-bit last-input tick from the 64-bit clock reads billions of idle ms after 49.7 days.
    assert elapsed(2**32 + 500, 2**32 - 1500) == 2000
    assert elapsed(2 * 2**32 + 100, 50) == 50
    assert elapsed(5000, 1000) == 4000


def test_the_idle_delay_setting_is_whole_minutes_within_an_hour() -> None:
    # Defect: a zero or runaway setting darkens the screen at every pause, or never.
    assert idle_delay(2) == 120_000
    for minutes in (0, -1, 61):
        with TestCase().assertRaisesRegex(ValueError, "DARK_WHEN_IDLE_MINUTES"):
            idle_delay(minutes)


def test_only_screens_turned_off_are_turned_back_on() -> None:
    # Defects: a screen that refused to turn off is later "restored", or a
    # screen that refused to turn back on is forgotten instead of retried.
    darkened = dark_after(frozenset(), frozendict({FOUR_K: Power.OFF, SECOND: Unanswered(31)}))
    assert darkened == frozenset({FOUR_K})
    assert dark_after(darkened, frozendict({FOUR_K: Detached()})) == frozenset({FOUR_K})
    assert dark_after(darkened, frozendict({FOUR_K: Power.ON})) == frozenset()
