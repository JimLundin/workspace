from desktop_ui.application_observer import Seating, lost_track, seating
from winapi.shapes import Window

TERMINALS = (
    Window(1, "One", "windowsterminal.exe", minimized=False),
    Window(2, "Two", "windowsterminal.exe", minimized=False),
)
EDGE = Window(3, "News", "msedge.exe", minimized=False)


def test_a_lost_app_is_warned_about_once_until_another_of_its_windows_is_lost() -> (
    None
):
    shown = (*TERMINALS, EDGE)
    assert len(tuple(lost_track(shown, frozenset({1, 2}), frozenset()))) == 1
    assert not tuple(lost_track(shown, frozenset({1, 2}), frozenset({1, 2})))
    assert len(tuple(lost_track(shown, frozenset({1, 3}), frozenset({1})))) == 1
    assert not tuple(lost_track(shown, frozenset(), frozenset()))


def test_a_lost_window_is_tucked_away_off_its_desktop_unless_it_is_in_front() -> (
    None
):
    assert seating(None, 0, 0, front=False) is Seating.PLACE
    assert seating(None, 0, 1, front=False) is Seating.TUCK
    assert seating(None, 0, 1, front=True) is Seating.LEAVE
    assert seating(1, 0, 1, front=False) is Seating.MOVE
    assert seating(0, 0, 1, front=False) is Seating.PLACE
