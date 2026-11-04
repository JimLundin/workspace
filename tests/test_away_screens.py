"""Which screens the lock-screen owner turns back on."""

from desktop_ui.locked_screens import dark_after
from winapi.monitor_power import Detached, Power, Unanswered
from winapi.screen import Monitor
from winapi.shapes import Rect

FOUR_K = Monitor(Rect(1920, -269, 5760, 1891), Rect(1920, -269, 5760, 1891), primary=False, internal=False)
SECOND = Monitor(Rect(-3840, 0, 0, 2160), Rect(-3840, 0, 0, 2160), primary=False, internal=False)


def test_only_screens_turned_off_are_turned_back_on() -> None:
    # Defects: a screen that refused to turn off is later "restored", or a
    # screen that refused to turn back on is forgotten instead of retried.
    darkened = dark_after(frozenset(), frozendict({FOUR_K: Power.OFF, SECOND: Unanswered(31)}))
    assert darkened == frozenset({FOUR_K})
    assert dark_after(darkened, frozendict({FOUR_K: Detached()})) == frozenset({FOUR_K})
    assert dark_after(darkened, frozendict({FOUR_K: Power.ON})) == frozenset()
