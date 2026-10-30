"""Windows-key taskbar intent, independent of Windows and Qt."""

from assistant.shell_state import WindowsKeyTap


def test_bare_windows_keys_toggle_once_on_release() -> None:
    for key in (0x5B, 0x5C):
        state = WindowsKeyTap()
        state, toggle = state.key(key, down=True)
        assert not toggle
        state, toggle = state.key(key, down=True)
        assert not toggle
        state, toggle = state.key(key, down=False)
        assert toggle
        state, toggle = state.key(key, down=False)
        assert not toggle


def test_windows_shortcuts_and_preheld_modifiers_do_not_toggle_taskbar() -> None:
    for chord in ((0x5B, 0x45), (0x11, 0x5B), (0x5B, 0x10, 0x53), (0x5B, 0x5C)):
        for release in (chord, tuple(reversed(chord))):
            state = WindowsKeyTap()
            for key in chord:
                state, toggle = state.key(key, down=True)
                assert not toggle
            for key in release:
                state, toggle = state.key(key, down=False)
                assert not toggle
            assert not state.held
            state, toggle = state.key(0x5B, down=True)
            assert not toggle
            state, toggle = state.key(0x5B, down=False)
            assert toggle
