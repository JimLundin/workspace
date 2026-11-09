"""A fake keyboard platform and helpers for the layout hook's tests: no desktop effects."""

from collections.abc import Generator, Mapping
from contextlib import contextmanager

from components import DESKTOP
from diagnostics import Detail
from keyboard.keys import Key, Mod
from keyboard.physical import Scancode
from keyboard.win import Keyboard
from protocol import Message, Window
from winapi import inputs, system


class KeyboardFixture:
    """Own disposable input observations and output history, without desktop effects.

    Mutable queues and failures model a driver changing between callbacks; only
    this fixture owns them. The live keyboard consumes its ordinary typed interface.
    """

    def __init__(self) -> None:
        self.current_foreground = 1
        self.current_title = ""
        self.devices: tuple[str, ...] = ()
        self.key = inputs.KeyEvent(0, 0, 0, 0, 0)
        self.read_error: Exception | None = None
        self.send_error: Exception | None = None
        self.delivery_error: Exception | None = None
        self.handle: int | None = 1
        """The desktop's running window; None while it is down."""
        self.reject_down: Key | Mod | None = None
        self.messages: list[tuple[int, int, int]] = []
        self.output: list[tuple[Key | Mod, bool]] = []
        self.recoveries: list[tuple[tuple[str, Detail], ...]] = []

    def send_key(self, key: Key | Mod, *, down: bool) -> None:
        self.output.append((key, down))
        if self.send_error is not None:
            raise self.send_error
        if down and key is self.reject_down:
            raise OSError("Sensitive content must not enter recovery logs")

    def keyboard_devices(self) -> tuple[str, ...]:
        return self.devices

    def foreground(self) -> int:
        return self.current_foreground

    def title(self, hwnd: int) -> str:
        return self.current_title

    def read_key_event(self, lparam: int) -> inputs.KeyEvent:
        if self.read_error is not None:
            raise self.read_error
        return self.key

    def call_next_hook(self, code: int, wparam: int, lparam: int) -> int:
        return 7

    def find_window(self, window: Window) -> int | None:
        return self.handle if window == DESKTOP.window else None

    # Keep the native delivery fields together in the concrete driver fixture.
    def post_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> bool:
        if self.delivery_error is not None:
            raise self.delivery_error
        if self.handle is None or hwnd != self.handle:
            return False
        self.messages.append((message, wparam, lparam))
        return True

    def set_timer(self, ms: int) -> int:
        return 17

    def kill_timer(self, timer: int) -> None:
        pass

    def record_recovery(self, details: Mapping[str, Detail]) -> None:
        self.recoveries.append(tuple(details.items()))

    def post_quit(self) -> None:
        pass


APPS_THUMB, DICTATE_KEY, TOGGLE_KEY = Scancode(0x2D), Scancode(0x26), Scancode(0x2B)
SPACEBAR, N_KEY, B_KEY = Scancode(0x39), Scancode(0x31), Scancode(0x30)


def hook_key(keyboard: Keyboard, driver: KeyboardFixture, scancode: Scancode, *, down: bool, at: int) -> int:
    driver.key = inputs.KeyEvent(0, scancode, 0, at, 0)
    return keyboard.hook_proc(0, system.WindowMessage.KEYDOWN if down else system.WindowMessage.KEYUP, 0)


def hold_apps(keyboard: Keyboard, *, at: int) -> None:
    """Hold the Apps thumb past the tapping term (the fixture's timer is 17)."""
    keyboard.swallow(inputs.KeyEvent(0, APPS_THUMB, 0, at, 0), down=True)
    keyboard.timeout(17)


@contextmanager
def observed_keyboard(*, platform: KeyboardFixture | None = None) -> Generator[tuple[Keyboard, list[tuple[int, int, int]]]]:
    """Use the same driver seam for input observations and captured notifications."""
    driver = platform if platform is not None else KeyboardFixture()
    yield Keyboard.open(driver), driver.messages


def assert_host_remapping_restored(keyboard: Keyboard) -> None:
    assert keyboard.engine_state.enabled and keyboard.state.firmware is None


def firmware_keyboard() -> tuple[Keyboard, KeyboardFixture]:
    driver = KeyboardFixture()
    driver.devices = (r"\\?\HID#VID_A8F8&PID_1832&MI_00#voice",)
    keyboard = Keyboard.open(driver)
    keyboard.update_devices()
    driver.messages.clear()
    return keyboard, driver


APPS_KEY = inputs.KeyEvent(0xA5, 0x38, inputs.LLKHF_EXTENDED, 10, 0)  # Right Alt: the Charybdis's held Tab thumb


CTRL = inputs.KeyEvent(0xA2, 0x1D, 0, 10, 0)


ALT = inputs.KeyEvent(0xA4, 0x38, 0, 10, 0)


SHIFT = inputs.KeyEvent(0xA0, 0x2A, 0, 10, 0)


DICTATE_LETTER = inputs.KeyEvent(0x48, 0x23, 0, 10, 0)  # H


def requests_of(driver: KeyboardFixture) -> list[tuple[int, int]]:
    return [(wparam, lparam) for message, wparam, lparam in driver.messages if message == Message.REQUEST]
