"""When the away-screens owner darkens and restores the protected screens, and which ones it turns back on."""

from desktop_ui.away_screens import Change, dark_after, step
from winapi.monitor_power import Detached, Power, Unanswered
from winapi.screen import Monitor
from winapi.shapes import Rect

FOUR_K = Monitor(Rect(1920, -269, 5760, 1891), Rect(1920, -269, 5760, 1891), primary=False, internal=False)
SECOND = Monitor(Rect(-3840, 0, 0, 2160), Rect(-3840, 0, 0, 2160), primary=False, internal=False)


def test_the_lock_darkens_once_and_the_unlock_restores_once() -> None:
    # Defects: a lock leaves the screens lit, a repeated lock message darkens again, or the unlock leaves them dark.
    assert step(dark=False, locked=True, enabled=True) is Change.DARKEN
    assert step(dark=True, locked=True, enabled=True) is None
    assert step(dark=True, locked=False, enabled=True) is Change.RESTORE
    assert step(dark=False, locked=False, enabled=True) is None


def test_turning_it_off_restores_and_keeps_screens_lit_through_a_lock() -> None:
    # Defect: the toggle stops new darkening but leaves a dark screen dark, or still darkens on lock.
    assert step(dark=True, locked=True, enabled=False) is Change.RESTORE
    assert step(dark=False, locked=True, enabled=False) is None


def test_only_screens_turned_off_are_turned_back_on() -> None:
    # Defects: a screen that refused to turn off is later "restored", or a
    # screen that refused to turn back on is forgotten instead of retried.
    darkened = dark_after(frozenset(), frozendict({FOUR_K: Power.OFF, SECOND: Unanswered(31)}))
    assert darkened == frozenset({FOUR_K})
    assert dark_after(darkened, frozendict({FOUR_K: Detached()})) == frozenset({FOUR_K})
    assert dark_after(darkened, frozendict({FOUR_K: Power.ON})) == frozenset()
