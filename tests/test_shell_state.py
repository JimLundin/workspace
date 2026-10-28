"""Windows-key taskbar intent, independent of Windows and Qt."""

from assistant.shell_state import WindowsKeyTap


def test_bare_windows_keys_toggle_once_on_release() -> None:
    for key in (0x5B, 0x5C):
        state = WindowsKeyTap()
        assert not state.key(key, True)
        assert not state.key(key, True)
        assert state.key(key, False)
        assert not state.key(key, False)


def test_windows_shortcuts_and_preheld_modifiers_do_not_toggle_taskbar() -> None:
    for chord in ((0x5B, 0x45), (0x11, 0x5B), (0x5B, 0x10, 0x53), (0x5B, 0x5C)):
        for release in (chord, tuple(reversed(chord))):
            state = WindowsKeyTap()
            assert not any(state.key(key, True) for key in chord)
            assert not any(state.key(key, False) for key in release)
            assert not state.held
            assert not state.key(0x5B, True)
            assert state.key(0x5B, False)
