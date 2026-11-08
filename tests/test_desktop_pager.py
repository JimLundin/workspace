"""The desktop pager's view."""

from desktop_ui.desktop_pager import NO_HINTS, Hints, PagerDesktop, pager
from desktop_ui.shell_items import PinnedApp
from desktop_ui.window_layout import CODE, TERMINAL


def test_pager_names_and_carries_each_desktops_apps_in_order_and_marks_the_current_one() -> None:
    # Defects: a desktop's icons lose the on-screen order they were given, or an
    # empty desktop gets another desktop's apps.
    view = pager(((PinnedApp.TEAMS,), (TERMINAL, CODE, PinnedApp.TEAMS), (), (PinnedApp.OUTLOOK,)), 2, chord=False)
    assert view.desktops == (
        PagerDesktop("1", "Desktop 1 · Teams", current=False, apps=(PinnedApp.TEAMS,)),
        PagerDesktop("2", "Desktop 2 · windowsterminal, code, Teams", current=False, apps=(TERMINAL, CODE, PinnedApp.TEAMS)),
        PagerDesktop("3", "Desktop 3 (current) · No placed apps", current=True),
        PagerDesktop("4", "Desktop 4 · Outlook", current=False, apps=(PinnedApp.OUTLOOK,)),
    )
    assert view.hints == NO_HINTS


def test_pager_hints_are_the_chord_letters_while_ctrl_alt_shift_is_held() -> None:
    # Defects: hints show without the chord, or a desktop past the direct keys gets one.
    placed = ((), (), (), (), (), ())
    assert pager(placed, 0, chord=True).hints == Hints(("J", "L", "U", "Y", "'", None))
    assert pager(placed, 0, chord=False).hints == NO_HINTS
