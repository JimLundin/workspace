"""The layout's Windows-key tap recognition, independent of Windows."""

from miryoku.windows_key import WindowsKeyTap


def test_bare_windows_keys_toggle_once_on_release() -> None:
    # Defects: a repeat re-arms or toggles, or a second release toggles again.
    for key in (0x5B, 0x5C):
        state = WindowsKeyTap()
        assert not state.key(key, down=True)
        assert not state.key(key, down=True)
        assert state.key(key, down=False)
        assert not state.key(key, down=False)


def test_windows_shortcuts_and_preheld_modifiers_do_not_toggle_taskbar() -> None:
    # Defects: Win+E or Ctrl+Win toggles the taskbar, or a chord leaves a key
    # held so that the next bare tap is missed.
    for chord in ((0x5B, 0x45), (0x11, 0x5B), (0x5B, 0x10, 0x53), (0x5B, 0x5C)):
        for release in (chord, tuple(reversed(chord))):
            state = WindowsKeyTap()
            for key in chord:
                assert not state.key(key, down=True)
            for key in release:
                assert not state.key(key, down=False)
            assert not state.held
            assert not state.key(0x5B, down=True)
            assert state.key(0x5B, down=False)
