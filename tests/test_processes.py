from winapi.processes import CloseWindows, Terminate, ending


def test_an_app_with_windows_is_asked_to_close_them_not_ended() -> None:
    owners = frozendict({100: 7, 101: 8, 102: 7, 103: 9})
    assert ending(owners, frozenset({7, 8})) == CloseWindows((100, 101, 102))


def test_an_app_without_windows_is_ended() -> None:
    owners = frozendict({100: 7})
    assert ending(owners, frozenset({3, 4})) == Terminate(frozenset({3, 4}))
