"""Native shell behavior with isolated views and controlled Windows boundaries."""

import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows desktop shell")

lazy from PySide6 import QtCore, QtGui

from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import application
from desktop_ui.shell_controls import TaskbarControl
from miryoku.win import Keyboard, maintain_keyboard
from protocol import WM_TOGGLE_LAYOUT
from tests.test_windows_bindings import KeyboardFixture
from winapi import keyboard_language
lazy from desktop_ui.window_switcher import WindowSwitcher
lazy from winapi.shapes import Window

prepare()


class TaskbarDesktop:
    """Own the fixture Explorer visibility catalog, including simulated restarts."""

    def __init__(self) -> None:
        self.shown = {101: True}

    def taskbars(self) -> tuple[int, ...]:
        return tuple(self.shown)

    def visible(self, hwnd: int) -> bool:
        return self.shown[hwnd]

    def taskbar_visible(self, hwnd: int, *, show: bool) -> None:
        self.shown[hwnd] = show


class RecoveryGuard:
    """Own the fixture recovery process's readiness and exit observation."""

    def __init__(self, *, ready: bool = True) -> None:
        self.handshake = ready
        self.code: int | None = None
        self.closed = False

    def ready(self) -> bool:
        return self.handshake

    def poll(self) -> int | None:
        return self.code

    def close(self) -> None:
        self.closed = True
        self.code = 0


def test_taskbar_is_rehidden_after_explorer_reappears_and_restored_on_close() -> None:
    desktop, guard = TaskbarDesktop(), RecoveryGuard()
    control = TaskbarControl(desktop, lambda: guard)
    control.start()
    control.enforce()
    assert desktop.shown == {101: False}
    desktop.shown[101] = True
    desktop.shown[202] = True  # Explorer restart or a secondary monitor.
    control.enforce()
    assert desktop.shown == {101: False, 202: False}
    control.toggle()
    assert all(desktop.shown.values())
    control.toggle()
    assert not any(desktop.shown.values())
    control.close()
    assert all(desktop.shown.values()) and guard.closed
    control.enforce()
    assert all(desktop.shown.values())


def test_lost_recovery_guard_restores_taskbar_instead_of_leaving_it_hidden() -> None:
    desktop, guard = TaskbarDesktop(), RecoveryGuard()
    control = TaskbarControl(desktop, lambda: guard)
    control.start()
    control.enforce()
    guard.code = 1
    with unittest.TestCase().assertRaises(OSError):
        control.enforce()
    assert desktop.shown == {101: True}
    assert not control.ready
    control.close()


def test_taskbars_are_never_hidden_without_the_recovery_handshake() -> None:
    """Detect acquiring shell ownership after a failed recovery startup."""
    desktop, guard = TaskbarDesktop(), RecoveryGuard(ready=False)
    control = TaskbarControl(desktop, lambda: guard)
    with unittest.TestCase().assertRaisesRegex(OSError, "recovery could not start"):
        control.start()
    control.enforce()
    assert desktop.shown == {101: True} and guard.closed


class LanguageDesktop:
    """Own changing foreground observations and language requests in this scenario."""

    def __init__(self) -> None:
        self.observations = iter(((11, 0xF002041D), (22, 0x4090409), (22, 0x4090409)))
        self.loads: tuple[str, ...] = ()
        self.activations: tuple[int, ...] = ()
        self.requests: tuple[tuple[int, int], ...] = ()

    def load(self, identity: str) -> int:
        self.loads += (identity,)
        return 0x4090409 if identity == "00000409" else 0xF002041D

    def colemak(self) -> str:
        return "d001041d"

    def activate(self, layout: int) -> None:
        self.activations += (layout,)

    def foreground(self) -> tuple[int, int]:
        return next(self.observations)

    def request(self, hwnd: int, layout: int) -> None:
        self.requests += ((hwnd, layout),)


def test_keyboard_language_rechecks_each_foreground_and_both_toggle_states() -> None:
    desktop = LanguageDesktop()
    languages = keyboard_language.KeyboardLanguages(desktop)
    languages.enforce(enabled=True)
    languages.enforce(enabled=True)
    languages.enforce(enabled=False)
    assert desktop.loads == ("00000409", "d001041d")
    assert desktop.activations == (0x4090409, 0xF002041D)
    assert desktop.requests == ((11, 0x4090409), (22, 0xF002041D))


def test_firmware_keyboard_keeps_english_when_remapping_is_off_and_on_shutdown() -> None:
    """Detect Colemak being applied a second time to firmware-generated output."""
    desktop = LanguageDesktop()
    desktop.observations = iter(((11, 0x4090409), (11, 0xF002041D), (22, 0xF002041D), (22, 0x4090409), (22, 0x4090409)))
    languages = keyboard_language.KeyboardLanguages(desktop)
    driver = KeyboardFixture()
    keyboard = Keyboard(driver)
    keyboard.on_message(WM_TOGGLE_LAYOUT)
    maintain_keyboard(keyboard, languages)
    driver.devices = (r"\\?\HID#VID_A8F8&PID_1832&MI_00#connected",)
    maintain_keyboard(keyboard, languages)
    maintain_keyboard(keyboard, languages)
    languages.close()
    assert desktop.activations == (0xF002041D, 0x4090409)
    assert desktop.requests == ((11, 0xF002041D), (11, 0x4090409), (22, 0x4090409))
    driver.devices = ()
    maintain_keyboard(keyboard, languages)
    assert not keyboard.engine.enabled
    assert_language_restored(desktop)


def assert_language_restored(desktop: LanguageDesktop) -> None:
    assert desktop.activations[-1] == 0xF002041D and desktop.requests[-1] == (22, 0xF002041D)


def test_window_switcher_search_navigation_and_activation() -> None:
    app = application()
    focused: list[int] = []
    picker = WindowSwitcher(
        (
            Window(1, "Editor · current", "editor.exe", minimized=False),
            Window(2, "Planning board", "browser.exe", minimized=False),
            Window(3, "Archived planning", "browser.exe", minimized=True),
        ),
        focused.append,
    )
    try:
        assert picker.items.currentRow() == 1  # F6 defaults to the previous window.
        picker.search.setText("planning browser")
        assert picker.items.count() == 2
        key = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Down, QtCore.Qt.KeyboardModifier.NoModifier)
        assert picker.eventFilter(picker.search, key)
        assert picker.items.currentRow() == 1
        picker.activate()
        assert focused == [3]
        picker.filter("no such window")
        picker.activate()
        assert focused == [3]
    finally:
        picker.close()
        app.processEvents()
