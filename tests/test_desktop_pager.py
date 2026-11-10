"""The desktop pager's view."""

from desktop_ui.desktop_pager import NO_HINTS, PagerSpec, pager
from desktop_ui.shell_items import PinnedApp
from protocol import Request, Tool
from tests.test_shell_items import WEB_APPS
from tests.test_window_layout import CODE, TERMINAL

SPEC = PagerSpec(WEB_APPS, desktop="Space", current="here", empty="Nothing")
LETTERS: frozendict[Request, str] = frozendict({Tool.DESKTOP_1: "Q", Tool.DESKTOP_2: "W", Tool.DESKTOP_3: "E"})
"""The test's own pager: three desktops reachable by a chord letter."""


def test_pager_names_and_carries_each_desktops_apps_in_order_and_marks_the_current_one() -> None:
    # Defects: a desktop's icons lose the on-screen order they were given, an
    # empty desktop gets another desktop's apps, or two desktops read alike.
    placed = ((PinnedApp.TEAMS,), (TERMINAL, CODE, PinnedApp.TEAMS), (), (PinnedApp.OUTLOOK,))
    view = pager(placed, 2, SPEC, LETTERS, chord=False)
    assert tuple(desktop.apps for desktop in view.desktops) == placed
    assert tuple(desktop.current for desktop in view.desktops) == (False, False, True, False)
    assert len({desktop.name for desktop in view.desktops}) == len(placed)
    assert view.hints == NO_HINTS


def test_pager_hints_are_the_chord_letters_while_ctrl_alt_shift_is_held() -> None:
    # Defects: hints show without the chord, or a desktop past the direct keys gets one.
    placed = ((), (), (), ())
    assert pager(placed, 0, SPEC, LETTERS, chord=True).hints.desktops == ("Q", "W", "E", None)
    assert pager(placed, 0, SPEC, LETTERS, chord=False).hints == NO_HINTS
