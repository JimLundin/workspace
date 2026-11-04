"""The desktop pager's view and the bar's swipe."""

from desktop_ui.desktop_pager import NO_HINTS, Hints, PagerDesktop, Reach, pager, reach, swipe
from desktop_ui.keymap import shortcut
from desktop_ui.shell_items import PinnedApp
from desktop_ui.window_layout import CODE, TERMINAL
from protocol import Tool


def test_pager_names_each_desktops_apps_and_marks_the_current_one() -> None:
    view = pager(((TERMINAL, CODE, PinnedApp.TEAMS), (), (PinnedApp.OUTLOOK,)), 1, None)
    assert view.desktops == (
        PagerDesktop("1", "Desktop 1 · windowsterminal, code, Teams", current=False),
        PagerDesktop("2", "Desktop 2 (current) · No placed apps", current=True),
        PagerDesktop("3", "Desktop 3 · Outlook", current=False),
    )
    assert view.hints == NO_HINTS


def test_pager_hints_follow_the_keyboard_that_reaches_its_targets() -> None:
    # Defects: hints show on another layer, a desktop past the direct keys gets
    # one, a hint is a literal that a remapped key wouldn't update, or the
    # firmware chord shows laptop keycaps.
    keys = tuple(
        found.tap for tool in (Tool.DESKTOP_PREVIOUS, Tool.DESKTOP_NEXT, Tool.DESKTOP_1, Tool.DESKTOP_2, Tool.DESKTOP_3) if (found := shortcut(tool))
    )
    assert keys == ("K", "L", "Caps", "S", "D")
    assert reach("APPS", chord=False) is Reach.APPS_LAYER
    assert reach("APPS · locked", chord=False) is Reach.APPS_LAYER
    assert reach("NAV", chord=False) is None
    assert reach(None, chord=False) is None
    assert reach(None, chord=True) is Reach.CHORD
    placed = ((), (), (), ())
    assert pager(placed, 0, Reach.APPS_LAYER).hints == Hints("K", "L", ("Caps", "S", "D", None))
    assert pager(placed, 0, Reach.CHORD).hints == Hints("⌃⌥⇧ K", "⌃⌥⇧ H", ("⌃⌥⇧ L", "⌃⌥⇧ U", "⌃⌥⇧ Y", None))
    assert pager(placed, 0, None).hints == NO_HINTS


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
