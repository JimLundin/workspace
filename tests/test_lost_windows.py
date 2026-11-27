from desktop_ui.application_observer import lost_track
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
