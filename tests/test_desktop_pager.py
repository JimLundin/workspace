"""The desktop pager's view and the bar's swipe."""

from desktop_ui.desktop_pager import NO_HINTS, Hints, PagerDesktop, pager, swipe
from desktop_ui.shell_items import PinnedApp
from desktop_ui.window_layout import CODE, TERMINAL


def test_pager_names_each_desktops_apps_and_marks_the_current_one() -> None:
    view = pager(((TERMINAL, CODE, PinnedApp.TEAMS), (), (PinnedApp.OUTLOOK,)), 1, chord=False)
    assert view.desktops == (
        PagerDesktop("1", "Desktop 1 · windowsterminal, code, Teams", current=False),
        PagerDesktop("2", "Desktop 2 (current) · No placed apps", current=True),
        PagerDesktop("3", "Desktop 3 · Outlook", current=False),
    )
    assert view.hints == NO_HINTS


def test_pager_hints_are_the_chord_letters_while_ctrl_alt_shift_is_held() -> None:
    # Defects: hints show without the chord, a desktop past the direct keys gets
    # one, or previous and next are swapped.
    placed = ((), (), (), (), ())
    assert pager(placed, 0, chord=True).hints == Hints("K", "H", ("J", "L", "U", "Y", None))
    assert pager(placed, 0, chord=False).hints == NO_HINTS


def test_one_swipe_steps_one_desktop_however_many_wheel_events_it_sends() -> None:
    # Defects: a flick's trailing events step again, a tilt held down keeps
    # stepping, a tiny touchpad nudge steps, or the direction is reversed.
    gesture, step = swipe(None, -30, 0.0)
    assert step == 0
    gesture, step = swipe(gesture, -40, 0.05)
    assert step == 1
    for moment in (0.1, 0.2, 0.4, 0.7):
        gesture, step = swipe(gesture, -120, moment)
        assert step == 0
    gesture, step = swipe(gesture, 120, 1.2)
    assert step == -1
    assert swipe(None, 20, 0.0)[1] == 0
