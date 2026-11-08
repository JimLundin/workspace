"""Windows bindings at their boundaries, without touching the real keyboard."""

import ctypes
import sys
import unittest
import uuid
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import replace

if sys.platform != "win32":
    raise unittest.SkipTest("Windows bindings")


from components import Window
from config import APPS
from desktop_ui.desktop_controls import (
    FeatureRequest,
    WindowInput,
    control_event,
)
from miryoku import hook_watch
from miryoku.engine import Indicator
from miryoku.layout import ESCAPE, Key, Layer, Mod, Scancode
from miryoku.win import WINDOWS, Keyboard, WinHost, release_keyboard
from protocol import (
    LAYOUT_MAGIC,
    MAGIC,
    SWITCHER_TITLE,
    WM_CHORD,
    WM_INDICATOR,
    WM_KEY_STATE,
    WM_LAYOUT_STATE,
    WM_QUERY_LAYOUT_STATE,
    WM_REQUEST,
    WM_TOGGLE_LAYOUT,
    WM_WINDOWS_KEY_TAP,
    LayoutState,
    Side,
    Tool,
    decode_indicator,
    encode,
)
from usage import Detail
from winapi import inputs, shell, system, windows
from winapi._core import LRESULT, fn, user32
from winapi.shapes import Point

_SendMessage = fn(user32, "SendMessageW", LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_GetWindowLong = fn(user32, "GetWindowLongW", wintypes.LONG, wintypes.HWND, ctypes.c_int)
_SetWindowLong = fn(user32, "SetWindowLongW", wintypes.LONG, wintypes.HWND, ctypes.c_int, wintypes.LONG)


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
        self.handles: dict[Side, int | None] = {Side.DESKTOP: 1, Side.ASSISTANT: 2}
        """Each side's running window; None while that side is down."""
        self.sounds: list[int] = []
        self.reject_down: Key | Mod | None = None
        self.messages: list[tuple[int, int, int]] = []
        self.routes: list[Side] = []
        """The side each of `messages` reached."""
        self.output: list[tuple[Key | Mod, bool]] = []
        self.recoveries: list[tuple[tuple[str, Detail], ...]] = []
        self.usage: list[tuple[tuple[str, int], ...]] = []

    def send_key(self, key: Key | Mod, *, down: bool) -> None:
        self.output.append((key, down))
        if self.send_error is not None:
            raise self.send_error
        if down and key is self.reject_down:
            raise OSError("Sensitive content must not enter recovery logs")

    def cursor_position(self) -> Point:
        return Point(0, 0)

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
        return next((self.handles[side] for side, known in WINDOWS.items() if known == window), None)

    # Keep the native delivery fields together in the concrete driver fixture.
    def post_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> bool:
        if self.delivery_error is not None:
            raise self.delivery_error
        side = next((side for side, handle in self.handles.items() if handle == hwnd), None)
        if side is None:
            return False
        self.messages.append((message, wparam, lparam))
        self.routes.append(side)
        return True

    def to(self, side: Side) -> list[tuple[int, int, int]]:
        """What reached `side`'s window, in order."""
        return [message for message, route in zip(self.messages, self.routes, strict=True) if route is side]

    def set_timer(self, ms: int) -> int:
        return 17

    def kill_timer(self, timer: int) -> None:
        pass

    def beep(self, sound: int) -> None:
        self.sounds.append(sound)

    def type_text(self, text: str) -> None:
        pass

    def record_recovery(self, details: Mapping[str, Detail]) -> None:
        self.recoveries.append(tuple(details.items()))

    def record_counts(self, counts: Mapping[str, int]) -> None:
        self.usage.append(tuple(counts.items()))

    def post_quit(self) -> None:
        pass


APPS_THUMB, DICTATE_KEY, AGENT_KEY, TOGGLE_KEY = Scancode(0x2D), Scancode(0x26), Scancode(0x25), Scancode(0x2B)
"""Physical X holds the Apps layer; on it L holds dictation, K agent speech, and the quote key toggles dictation."""
SPACEBAR, N_KEY, B_KEY = Scancode(0x39), Scancode(0x31), Scancode(0x30)
"""The retired voice keys, blocked now."""


def hook_key(keyboard: Keyboard, driver: KeyboardFixture, scancode: Scancode, *, down: bool, at: int) -> int:
    driver.key = inputs.KeyEvent(0, scancode, 0, at, 0)
    return keyboard.hook_proc(0, system.WM_KEYDOWN if down else system.WM_KEYUP, 0)


def hold_apps(keyboard: Keyboard, *, at: int) -> None:
    """Hold the Apps thumb past the tapping term (the fixture's timer is 17)."""
    keyboard.swallow(inputs.KeyEvent(0, APPS_THUMB, 0, at, 0), down=True)
    keyboard.engine.timeout(keyboard.host, 17)


@contextmanager
def observed_keyboard(*, platform: KeyboardFixture | None = None) -> Generator[tuple[Keyboard, list[tuple[int, int, int]]]]:
    """Use the same driver seam for input observations and captured notifications."""
    driver = platform if platform is not None else KeyboardFixture()
    yield Keyboard(driver), driver.messages


def test_physical_press_is_reported_before_a_tap_hold_is_resolved() -> None:
    with observed_keyboard() as (keyboard, messages):
        key = inputs.KeyEvent(0x4D, 0x32, 0, 10, 0)  # M: Enter/Symbols thumb
        assert keyboard.swallow(key, down=True)
        assert messages == [(WM_KEY_STATE, 0x32, 1)]
        assert keyboard.engine.layer() is None
        assert keyboard.pressed == {Scancode(0x32)}
        keyboard.swallow(key, down=True)  # auto-repeat must not refresh the highlight
        assert messages == [(WM_KEY_STATE, 0x32, 1)]
        keyboard.swallow(inputs.KeyEvent(0x4D, 0x32, 0, 40, 0), down=False)
        keyboard.swallow(inputs.KeyEvent(0x4D, 0x32, 0, 41, 0), down=False)
        assert messages == [(WM_KEY_STATE, 0x32, 1), (WM_KEY_STATE, 0x32, 0)]
        assert not keyboard.pressed


def test_assistant_outage_keeps_remapping_and_reconnects_without_replaying_shortcuts() -> None:
    # Detect routing temporary assistant unavailability into input-failure
    # recovery, or retaining the old HWND after a fresh assistant starts.
    driver = KeyboardFixture()
    keyboard = Keyboard(driver)
    keyboard.host.found = frozendict({Side.ASSISTANT: 2})
    driver.handles[Side.ASSISTANT] = None
    hold_apps(keyboard, at=5)
    assert hook_key(keyboard, driver, DICTATE_KEY, down=True, at=10) == 1
    assert hook_key(keyboard, driver, DICTATE_KEY, down=False, at=20) == 1
    assert hook_key(keyboard, driver, APPS_THUMB, down=False, at=25) == 1
    assert keyboard.engine.enabled and keyboard.fault is None
    assert driver.sounds == [system.MB_ICONHAND]
    assert driver.to(Side.ASSISTANT) == []
    keyboard.swallow(inputs.KeyEvent(0x34, 0x05, 0, 30, 0), down=True)
    keyboard.swallow(inputs.KeyEvent(0x34, 0x05, 0, 40, 0), down=False)
    assert driver.output
    driver.handles[Side.ASSISTANT] = 3
    hold_apps(keyboard, at=45)
    keyboard.swallow(inputs.KeyEvent(0, DICTATE_KEY, 0, 50, 0), down=True)
    keyboard.swallow(inputs.KeyEvent(0, DICTATE_KEY, 0, 60, 0), down=False)
    keyboard.swallow(inputs.KeyEvent(0, APPS_THUMB, 0, 65, 0), down=False)
    assert keyboard.host.found[Side.ASSISTANT] == 3
    assert [(wparam, lparam) for message, wparam, lparam in driver.messages if message == WM_REQUEST] == [
        (Tool.DICTATE.value, 1),
        (Tool.DICTATE.value, 0),
    ]
    assert keyboard.engine.enabled


def test_each_message_reaches_the_side_that_owns_it() -> None:
    # Defects: an app or window key waits on the assistant (failing while it
    # restarts), dictation goes to the desktop, what the desktop shows (pressed
    # keys, layer, chord) goes to the assistant, or one side misses the layout's state.
    driver = KeyboardFixture()
    keyboard = Keyboard(driver)
    keyboard.swallow(inputs.KeyEvent(0x4D, 0x32, 0, 1, 0), down=True)
    keyboard.swallow(inputs.KeyEvent(0x4D, 0x32, 0, 2, 0), down=False)
    keyboard.on_message(WM_QUERY_LAYOUT_STATE)
    for request in (Tool.DICTATE, Tool.OPEN_INBOX, Tool.DESKTOP_2, APPS[0]):
        keyboard.host.request(request, down=True)
    desktop, assistant = driver.to(Side.DESKTOP), driver.to(Side.ASSISTANT)
    assert {message for message, _, _ in desktop} == {WM_KEY_STATE, WM_LAYOUT_STATE, WM_INDICATOR, WM_CHORD, WM_REQUEST}
    assert {message for message, _, _ in assistant} == {WM_LAYOUT_STATE, WM_REQUEST}
    assert [wparam for message, wparam, _ in desktop if message == WM_REQUEST] == [Tool.OPEN_INBOX.value, Tool.DESKTOP_2.value, encode(APPS[0], APPS)]
    assert [wparam for message, wparam, _ in assistant if message == WM_REQUEST] == [Tool.DICTATE.value]
    driver.handles[Side.DESKTOP] = None
    keyboard.host.found = frozendict()
    keyboard.host.request(Tool.DICTATE, down=True)
    assert driver.to(Side.ASSISTANT)[-1] == (WM_REQUEST, Tool.DICTATE.value, 1) and not driver.sounds


def test_generated_and_extended_input_does_not_light_physical_keys() -> None:
    for flags, extra in ((0, LAYOUT_MAGIC), (0, MAGIC), (inputs.LLKHF_INJECTED, 0), (inputs.LLKHF_EXTENDED, 0)):
        with observed_keyboard() as (keyboard, messages):
            keyboard.swallow(inputs.KeyEvent(0x4D, 0x32, flags, 10, extra), down=True)
            keyboard.swallow(inputs.KeyEvent(0x4D, 0x32, flags, 40, extra), down=False)
            assert not any(message == WM_KEY_STATE for message, _, _ in messages)
            assert not keyboard.pressed


def test_blocked_keys_light_up_but_unpictured_keys_do_not() -> None:
    with observed_keyboard() as (keyboard, messages):
        for scancode in (SPACEBAR, N_KEY, 0x15, 0x56, 0x35, B_KEY):
            keyboard.swallow(inputs.KeyEvent(0, scancode, 0, 10, 0), down=True)
            keyboard.swallow(inputs.KeyEvent(0, scancode, 0, 40, 0), down=False)
        keys = [(scancode, down) for message, scancode, down in messages if message == WM_KEY_STATE]
        assert keys == [(scancode, down) for scancode in (SPACEBAR, N_KEY, 0x15, 0x56, 0x35, B_KEY) for down in (1, 0)]
        assert not any(message == WM_REQUEST for message, _, _ in messages)


def test_apps_k_holds_agent_voice_until_release_and_updates_its_highlight() -> None:
    # Defect: K emits the toggle request or repeats instead of sending one
    # hold/release pair through the assistant's existing push-to-talk handler.
    with observed_keyboard() as (keyboard, messages):
        hold_apps(keyboard, at=0)
        messages.clear()
        key = inputs.KeyEvent(0, AGENT_KEY, 0, 10, 0)
        assert keyboard.swallow(key, down=True)
        assert messages == [(WM_KEY_STATE, AGENT_KEY, 1), (WM_REQUEST, Tool.AGENT_VOICE.value, 1)]
        assert keyboard.pressed == {APPS_THUMB, AGENT_KEY}
        keyboard.swallow(key, down=True)
        keyboard.swallow(inputs.KeyEvent(0, AGENT_KEY, 0, 300, 0), down=False)
        assert messages == [
            (WM_KEY_STATE, AGENT_KEY, 1),
            (WM_REQUEST, Tool.AGENT_VOICE.value, 1),
            (WM_KEY_STATE, AGENT_KEY, 0),
            (WM_REQUEST, Tool.AGENT_VOICE.value, 0),
        ]
        assert keyboard.pressed == {APPS_THUMB}


def test_native_modifier_released_after_enabling_does_not_stick_to_space() -> None:
    with observed_keyboard() as (keyboard, messages):
        control = inputs.KeyEvent(0xA2, 0x1D, 0, 10, 0)
        keyboard.engine.restore(replace(keyboard.engine.state, enabled=False))
        assert not keyboard.swallow(control, down=True)
        keyboard.engine.restore(replace(keyboard.engine.state, enabled=True))
        assert not keyboard.swallow(control, down=False)
        hold_apps(keyboard, at=15)
        keyboard.swallow(inputs.KeyEvent(0, DICTATE_KEY, 0, 20, 0), down=True)
        assert (WM_REQUEST, Tool.DICTATE.value, 1) in messages


def test_f6_stays_native_and_the_dictation_toggle_sends_one_pair_per_press() -> None:
    with observed_keyboard() as (keyboard, messages):
        shift = inputs.KeyEvent(0xA0, 0x2A, 0, 0, 0)
        assert not keyboard.swallow(shift, down=True)
        hold_apps(keyboard, at=5)
        key = inputs.KeyEvent(0, TOGGLE_KEY, 0, 10, 0)
        keyboard.swallow(key, down=True)
        keyboard.swallow(key, down=True)
        keyboard.swallow(key, down=False)
        requests = [(tool, down) for message, tool, down in messages if message == WM_REQUEST]
        assert requests == [(Tool.DICTATE_TOGGLE.value, 1), (Tool.DICTATE_TOGGLE.value, 0)]
        messages.clear()
        function = inputs.KeyEvent(0x75, 0x40, 0, 30, 0)
        assert not keyboard.swallow(function, down=True)
        assert not keyboard.swallow(function, down=False)
        assert not any(message == WM_REQUEST for message, _tool, _down in messages)


def test_picker_enter_release_passes_after_the_selected_window_takes_focus() -> None:
    driver = KeyboardFixture()
    driver.current_title = SWITCHER_TITLE
    with observed_keyboard(platform=driver) as (keyboard, messages):
        keyboard.foreground = 0
        enter = inputs.KeyEvent(0x0D, 0x1C, 0, 0, 0)
        assert not keyboard.swallow(enter, down=True)
        keyboard.picker_active = False
        assert not keyboard.swallow(enter, down=False)
        assert not keyboard.native_releases and messages == []


def test_layout_query_resets_then_replays_all_physically_held_keys() -> None:
    with observed_keyboard() as (keyboard, messages):
        for scancode in (0x32, 0x10):
            keyboard.swallow(inputs.KeyEvent(0, scancode, 0, 10, 0), down=True)
        messages.clear()
        keyboard.on_message(WM_QUERY_LAYOUT_STATE)
        assert messages[:2] == [(WM_LAYOUT_STATE, LayoutState.ON.value, 0)] * 2  # The desktop's, then the assistant's.
        assert messages[2][0] == WM_INDICATOR
        assert messages[3:] == [(WM_KEY_STATE, 0, 0), (WM_KEY_STATE, 0x10, 1), (WM_KEY_STATE, 0x32, 1), (WM_CHORD, 0, 0)]


def test_toggle_and_input_failure_clear_held_keys() -> None:
    with observed_keyboard() as (keyboard, messages):
        key = inputs.KeyEvent(0x4D, 0x32, 0, 10, 0)
        keyboard.swallow(key, down=True)
        keyboard.on_message(WM_TOGGLE_LAYOUT)
        assert not keyboard.pressed
        assert messages[-1] == (WM_KEY_STATE, 0, 0)
        messages.clear()
        assert not keyboard.swallow(key, down=True)
        assert messages == []
        keyboard.on_message(WM_TOGGLE_LAYOUT)
        keyboard.swallow(key, down=True)
        sent = len(messages)
        keyboard.input_failed(OSError("Rejected input"))
        assert not keyboard.pressed
        assert (WM_KEY_STATE, 0, 0) in messages[sent:]
        assert not bool(keyboard.engine.enabled)


def test_reinstalling_a_dead_hook_ends_voice_capture_and_a_held_escape() -> None:
    # Defects: real input the hook missed is never probed or reinstalled, dictation
    # stays captured, or the stale Escape press quits the layout on the next tap.
    driver = KeyboardFixture()
    keyboard = Keyboard(driver)
    hold_apps(keyboard, at=990)
    for key in (inputs.KeyEvent(0, DICTATE_KEY, 0, 1_000, 0), inputs.KeyEvent(0xC0, ESCAPE, 0, 1_010, 0)):
        driver.key = key
        keyboard.hook_proc(0, system.WM_KEYDOWN, 0)
    # Windows drops the hook, so both key-ups reach only raw input.
    keyboard.watch = hook_watch.keyboard_input(keyboard.watch, 5_000)
    assert keyboard.watch_hook(5_300) is None
    assert driver.output[-2:] == [(Key.MENU_MASK, True), (Key.MENU_MASK, False)]
    outage = hook_watch.Reinstall(5_000, 1_010)
    assert keyboard.watch_hook(6_300) == outage
    sent = len(driver.messages)
    keyboard.hook_reinstalled(outage, 6_400)
    assert driver.messages[sent:] == [(WM_REQUEST, Tool.DICTATE.value, 0), (WM_KEY_STATE, 0, 0)]
    assert dict(driver.recoveries[-1]) == {"phase": "hook_reinstall", "ok": True, "outage_ms": 1_400, "hook_silent_ms": 5_390}
    for wparam, tick in ((system.WM_KEYDOWN, 7_000), (system.WM_KEYUP, 7_050)):
        driver.key = inputs.KeyEvent(0xC0, ESCAPE, 0, tick, 0)
        keyboard.hook_proc(0, wparam, 0)
    assert not keyboard.engine.enabled  # the tap toggles; the stale press would quit


def test_a_refused_probe_keeps_the_hook_and_its_held_keys() -> None:
    # Defect: typing into an elevated window or on the lock screen, where Windows
    # refuses the probe, reads as a dead hook and drops held keys.
    driver = KeyboardFixture()
    keyboard = Keyboard(driver)
    hold_apps(keyboard, at=990)
    hook_key(keyboard, driver, DICTATE_KEY, down=True, at=1_000)
    driver.send_error = OSError("Windows accepted 0 of 1 input events.")
    verdicts: list[hook_watch.Reinstall | None] = []
    for tick in range(5_000, 20_000, 200):
        keyboard.watch = hook_watch.keyboard_input(keyboard.watch, tick - 100)
        verdicts.append(keyboard.watch_hook(tick))
    assert verdicts == [None] * len(verdicts)
    assert driver.output.count((Key.MENU_MASK, True)) > 1
    assert Tool.DICTATE in keyboard.engine.pressed
    assert not driver.recoveries


def test_hook_failure_passes_input_even_when_recovery_effects_also_fail() -> None:
    driver = KeyboardFixture()
    driver.read_error = RuntimeError("Read failed")
    driver.send_error = OSError("Release failed")
    driver.delivery_error = OSError("Post failed")
    keyboard = Keyboard(driver)
    keyboard.engine.restore(replace(keyboard.engine.state, pressed=(Key.A, *keyboard.engine.pressed[1:])))
    keyboard.host.owned.add(Key.A)
    assert keyboard.hook_proc(0, 0x0100, 1) == 7
    assert not bool(keyboard.engine.enabled) and not keyboard.busy
    assert keyboard.fault is not None and keyboard.fault.kind == "RuntimeError"
    assert not driver.recoveries
    for _ in range(5):
        keyboard.maintenance()
    assert len(driver.recoveries) == 1
    assert dict(driver.recoveries[0])["cleanup_failures"] == 1


def test_rejected_chord_releases_its_added_modifier_and_defers_diagnostics() -> None:
    driver = KeyboardFixture()
    driver.current_foreground = 0
    driver.key = inputs.KeyEvent(0x32, 0x03, 0, 10, 0)
    driver.reject_down = Key.LBRACKET
    keyboard = Keyboard(driver)
    keyboard.engine.restore(replace(keyboard.engine.state, locked=Layer.SYM))
    assert keyboard.hook_proc(0, 0x0100, 1) == 7
    assert not bool(keyboard.engine.enabled) and not keyboard.host.owned
    assert (Mod.SHIFT, False) in driver.output
    assert not driver.recoveries
    keyboard.maintenance()
    assert len(driver.recoveries) == 1
    assert "Sensitive content" not in str(driver.recoveries)


def test_native_output_ownership_survives_rejection_until_release_is_accepted() -> None:
    driver = KeyboardFixture()
    driver.send_error = OSError("Rejected")
    host = WinHost(driver)
    with unittest.TestCase().assertRaises(OSError):
        host.send(Key.A, down=True)
    assert host.owned == {Key.A}
    host.release_owned()
    assert host.owned == {Key.A}
    driver.send_error = None
    host.release_owned()
    assert not host.owned


def test_recovery_retries_are_bounded_and_enabling_waits_for_accepted_releases() -> None:
    driver = KeyboardFixture()
    driver.send_error = OSError("Rejected")
    keyboard = Keyboard(driver)
    keyboard.host.owned.add(Key.A)
    keyboard.input_failed(OSError("Input rejected"))
    for _ in range(10):
        keyboard.maintenance()
    assert len(driver.output) == 6  # Immediate cleanup plus five timer attempts.
    assert not keyboard.recovery_ticks and keyboard.fault is None
    keyboard.on_message(WM_TOGGLE_LAYOUT)
    assert not bool(keyboard.engine.enabled)
    driver.send_error = None
    keyboard.on_message(WM_TOGGLE_LAYOUT)
    assert bool(keyboard.engine.enabled) and not keyboard.host.owned


def test_capture_watchdog_timer_is_delivered_to_its_hidden_window() -> None:
    hwnd = windows.create_hidden("Workspace watchdog fixture")
    timer = system.set_window_timer(hwnd, 20)
    try:
        message = next(system.messages())
        while message.message != system.WM_TIMER:
            message = next(system.messages())
        assert message.hwnd == hwnd and message.wparam == timer
    finally:
        system.kill_window_timer(hwnd, timer)
        windows.destroy(hwnd)


def test_firmware_keyboard_bypasses_remapping_and_restores_the_previous_mode() -> None:
    """Detect firmware keys invoking voice/remapping, stuck output, or unwanted enable."""
    driver = KeyboardFixture()
    keyboard = Keyboard(driver)
    keyboard.swallow(inputs.KeyEvent(0x32, 0x03, 0, 10, 0), down=True)
    assert driver.output[-1] == (Key.Q, True)
    driver.devices = (r"\\?\HID#VID_A8F8&PID_1832&MI_00#connected",)
    keyboard.update_devices()
    assert not keyboard.engine.enabled and driver.output[-1] == (Key.Q, False)
    assert not keyboard.pressed and keyboard.firmware is not None
    output = tuple(driver.output)
    for key in (inputs.KeyEvent(0x4E, N_KEY, 0, 20, 0), inputs.KeyEvent(0, ESCAPE, 0, 20, 0)):
        assert not keyboard.swallow(key, down=True)
        assert not keyboard.swallow(key, down=False)
    keyboard.on_message(WM_TOGGLE_LAYOUT)
    assert not keyboard.engine.enabled and tuple(driver.output) == output
    shift = inputs.KeyEvent(0xA0, 0x2A, 0, 30, 0)
    assert not keyboard.swallow(shift, down=True)
    driver.devices = ()
    keyboard.update_devices()
    assert_host_remapping_restored(keyboard)
    assert not keyboard.swallow(shift, down=False)
    assert keyboard.swallow(inputs.KeyEvent(0x54, 0x14, 0, 40, 0), down=True)
    keyboard.swallow(inputs.KeyEvent(0x54, 0x14, 0, 50, 0), down=False)
    assert driver.output[-2:] == [(Key.G, True), (Key.G, False)]
    keyboard.on_message(WM_TOGGLE_LAYOUT)
    driver.devices = (r"\\?\HID#VID_A8F8&PID_1832&MI_00#reconnected",)
    keyboard.update_devices()
    driver.devices = ()
    keyboard.update_devices()
    assert not keyboard.engine.enabled
    keyboard.swallow(inputs.KeyEvent(0, ESCAPE, 0, 60, 0), down=True)
    keyboard.swallow(inputs.KeyEvent(0, ESCAPE, 0, 65, 0), down=False)
    assert bool(keyboard.engine.enabled), "After restoring off mode, the physical toggle must still work."
    keyboard.swallow(inputs.KeyEvent(0x32, 0x03, 0, 70, 0), down=True)
    driver.send_error = OSError("Native release refused")
    driver.devices = (r"\\?\HID#VID_A8F8&PID_1832&MI_00#connected",)
    keyboard.update_devices()
    assert keyboard.firmware is not None and not keyboard.firmware.resume_layout
    driver.send_error = None
    driver.devices = ()
    keyboard.update_devices()
    assert not keyboard.engine.enabled, "A failed release must not automatically enable remapping."
    keyboard.maintenance()


def assert_host_remapping_restored(keyboard: Keyboard) -> None:
    assert keyboard.engine.enabled and keyboard.firmware is None


def firmware_keyboard() -> tuple[Keyboard, KeyboardFixture]:
    driver = KeyboardFixture()
    driver.devices = (r"\\?\HID#VID_A8F8&PID_1832&MI_00#voice",)
    keyboard = Keyboard(driver)
    keyboard.update_devices()
    driver.messages.clear()
    return keyboard, driver


APPS_KEY = inputs.KeyEvent(0xA5, 0x38, inputs.LLKHF_EXTENDED, 10, 0)  # Right Alt: the Charybdis's held Tab thumb
CTRL = inputs.KeyEvent(0xA2, 0x1D, 0, 10, 0)
ALT = inputs.KeyEvent(0xA4, 0x38, 0, 10, 0)
SHIFT = inputs.KeyEvent(0xA0, 0x2A, 0, 10, 0)
DICTATE_LETTER = inputs.KeyEvent(0x48, 0x23, 0, 10, 0)  # H
AGENT_LETTER = inputs.KeyEvent(0x4B, 0x25, 0, 10, 0)  # K


def requests_of(driver: KeyboardFixture) -> list[tuple[int, int]]:
    return [(wparam, lparam) for message, wparam, lparam in driver.messages if message == WM_REQUEST]


def test_firmware_apps_thumb_voice_holds_pair_each_press_with_its_release() -> None:
    """Detect Right Alt reaching applications, repeat starts, leaked keys, or a hold cut short by releasing the thumb."""
    for voice_key, tool in ((DICTATE_LETTER, Tool.DICTATE), (AGENT_LETTER, Tool.AGENT_VOICE)):
        keyboard, driver = firmware_keyboard()
        assert keyboard.swallow(APPS_KEY, down=True)
        assert keyboard.swallow(APPS_KEY, down=True)  # its auto-repeat
        assert keyboard.swallow(voice_key, down=True)
        assert keyboard.swallow(voice_key, down=True)
        assert requests_of(driver) == [(tool.value, 1)]
        assert keyboard.swallow(APPS_KEY, down=False)
        assert requests_of(driver) == [(tool.value, 1)]
        assert keyboard.swallow(voice_key, down=False)
        assert requests_of(driver) == [(tool.value, 1), (tool.value, 0)]
        assert [message for message in driver.messages if message[0] == WM_CHORD] == [(WM_CHORD, 1, 0), (WM_CHORD, 0, 0)]
        assert not keyboard.shortcuts and not keyboard.native_releases
        assert not driver.output and not keyboard.engine.enabled


def test_firmware_keys_without_the_apps_thumb_or_already_held_stay_native() -> None:
    """Detect taking keys without the thumb, the retired modifier chords, or starting voice halfway through native repeat."""
    for voice_key in (DICTATE_LETTER, AGENT_LETTER):
        for modifiers in ((), (CTRL, SHIFT), (CTRL, ALT, SHIFT)):
            keyboard, driver = firmware_keyboard()
            for key in modifiers:
                assert not keyboard.swallow(key, down=True)
            assert not keyboard.swallow(voice_key, down=True)
            assert not keyboard.swallow(voice_key, down=False)
            assert not requests_of(driver)
    keyboard, driver = firmware_keyboard()
    assert not keyboard.swallow(DICTATE_LETTER, down=True)
    assert keyboard.swallow(APPS_KEY, down=True)
    assert not keyboard.swallow(DICTATE_LETTER, down=True)
    assert not keyboard.swallow(DICTATE_LETTER, down=False)
    assert not requests_of(driver)


def test_firmware_voice_finishes_on_unplug_and_swallows_the_late_voice_key_release() -> None:
    """Detect capture remaining open, the Apps thumb staying held, or a phantom remapped key."""
    keyboard, driver = firmware_keyboard()
    for key in (APPS_KEY, AGENT_LETTER):
        keyboard.swallow(key, down=True)
    driver.devices = ()
    keyboard.update_devices()
    assert_host_remapping_restored(keyboard)
    assert requests_of(driver) == [(Tool.AGENT_VOICE.value, 1), (Tool.AGENT_VOICE.value, 0)]
    assert not keyboard.apps_held
    assert keyboard.swallow(AGENT_LETTER, down=True)
    assert keyboard.swallow(AGENT_LETTER, down=False)
    assert not keyboard.shortcuts and not keyboard.native_releases


def test_firmware_voice_finishes_on_hook_failure_and_keyboard_shutdown() -> None:
    """Detect an orphaned microphone request when the input owner stops or fails."""
    stops: tuple[Callable[[Keyboard], None], ...] = (release_keyboard, lambda keyboard: keyboard.input_failed(OSError("hook failed")))
    for stop in stops:
        keyboard, driver = firmware_keyboard()
        for key in (APPS_KEY, DICTATE_LETTER):
            keyboard.swallow(key, down=True)
        stop(keyboard)
        keyboard.swallow(DICTATE_LETTER, down=False)
        assert requests_of(driver) == [(Tool.DICTATE.value, 1), (Tool.DICTATE.value, 0)]


def test_generated_input_neither_arms_nor_finishes_firmware_voice_shortcuts() -> None:
    """Detect dictation/automation output impersonating the Apps thumb or a voice key."""
    for flags, extra in ((inputs.LLKHF_INJECTED, 0), (0, MAGIC), (0, LAYOUT_MAGIC)):
        keyboard, driver = firmware_keyboard()
        for vk, scan in ((0xA5, 0x38), (0x48, 0x23)):
            assert not keyboard.swallow(inputs.KeyEvent(vk, scan, flags, 10, extra), down=True)
        assert not keyboard.swallow(DICTATE_LETTER, down=True)
        assert not requests_of(driver)
        keyboard.swallow(DICTATE_LETTER, down=False)
        keyboard.swallow(APPS_KEY, down=True)
        keyboard.swallow(DICTATE_LETTER, down=True)
        assert not keyboard.swallow(inputs.KeyEvent(0x48, 0x23, flags, 10, extra), down=False)
        assert requests_of(driver) == [(Tool.DICTATE.value, 1)]
        assert keyboard.swallow(DICTATE_LETTER, down=False)
        assert requests_of(driver) == [(Tool.DICTATE.value, 1), (Tool.DICTATE.value, 0)]


def test_firmware_apps_thumb_reaches_navigation_and_swallows_the_letter_press_and_release() -> None:
    """Detect a typed letter, an unpaired release, Right Alt leaking, or a request outside the Apps map."""
    keyboard, driver = firmware_keyboard()
    assert keyboard.swallow(APPS_KEY, down=True)
    assert driver.messages == [(WM_CHORD, 1, 0)]
    letter = inputs.KeyEvent(0x4A, 0x24, 0, 20, 0)  # J
    assert keyboard.swallow(letter, down=True)
    assert keyboard.swallow(letter, down=True)
    assert keyboard.swallow(letter, down=False)
    assert keyboard.swallow(APPS_KEY, down=False)
    requests = [control_event(WindowInput(*message), APPS) for message in driver.messages if message[0] == WM_REQUEST]
    assert requests == [FeatureRequest(Tool.DESKTOP_1, down=True), FeatureRequest(Tool.DESKTOP_1, down=False)]
    assert [message for message in driver.messages if message[0] == WM_CHORD] == [(WM_CHORD, 1, 0), (WM_CHORD, 0, 0)]
    assert not keyboard.shortcuts and not keyboard.native_releases and not driver.output
    assert keyboard.swallow(APPS_KEY, down=True)
    app = inputs.KeyEvent(0x51, 0x10, 0, 40, 0)  # Q
    assert keyboard.swallow(app, down=True)
    driver.devices = ()
    keyboard.update_devices()
    shortcuts = [message for message in driver.messages if message[0] in (WM_REQUEST, WM_CHORD)]
    assert shortcuts[-3:] == [(WM_REQUEST, 1000, 1), (WM_CHORD, 0, 0), (WM_REQUEST, 1000, 0)]
    assert control_event(WindowInput(*shortcuts[-3]), APPS) == FeatureRequest(APPS[0], down=True)
    assert keyboard.swallow(app, down=False)


def test_laptop_apps_layer_reaches_navigation_and_publishes_the_chord_like_firmware() -> None:
    """Detect an Apps layer key that types its letter, or a held layer that never shows the pager's chord hints."""
    driver = KeyboardFixture()
    with observed_keyboard(platform=driver) as (keyboard, messages):
        hold_apps(keyboard, at=0)
        letter = inputs.KeyEvent(0, 0x09, 0, 20, 0)  # Colemak J
        assert keyboard.swallow(letter, down=True)
        assert keyboard.swallow(letter, down=False)
        assert keyboard.swallow(inputs.KeyEvent(0, APPS_THUMB, 0, 30, 0), down=False)
        requests = [control_event(WindowInput(*message), APPS) for message in messages if message[0] == WM_REQUEST]
        assert requests == [FeatureRequest(Tool.DESKTOP_1, down=True), FeatureRequest(Tool.DESKTOP_1, down=False)]
        assert [message for message in messages if message[0] == WM_CHORD] == [(WM_CHORD, 1, 0), (WM_CHORD, 0, 0)]
        assert not driver.output
        assert not keyboard.host.owned


def test_laptop_home_row_ctrl_alt_shift_types_the_letter() -> None:
    """Detect the retired three-finger chord still swallowing a letter on the laptop."""
    driver = KeyboardFixture()
    with observed_keyboard(platform=driver) as (keyboard, messages):
        mods = [inputs.KeyEvent(0, scan, 0, 10, 0) for scan in (0x11, 0x12, 0x13)]  # R S T
        for key in mods:
            keyboard.swallow(key, down=True)
        keyboard.swallow(inputs.KeyEvent(0, 0x09, 0, 20, 0), down=True)
        keyboard.swallow(inputs.KeyEvent(0, 0x09, 0, 30, 0), down=False)
        assert not any(message[0] == WM_REQUEST for message in messages)
        assert (Key.J, True) in driver.output


def test_escape_toggle_clears_highlights_with_other_keys_still_held() -> None:
    with observed_keyboard() as (keyboard, messages):
        keyboard.swallow(inputs.KeyEvent(0, 0x32, 0, 10, 0), down=True)
        keyboard.swallow(inputs.KeyEvent(0, ESCAPE, 0, 20, 0), down=True)
        keyboard.swallow(inputs.KeyEvent(0, ESCAPE, 0, 40, 0), down=False)
        assert not bool(keyboard.engine.enabled)
        assert not keyboard.pressed
        assert messages[-1] == (WM_KEY_STATE, 0, 0)


def test_apps_enter_thumb_opens_inbox_once_per_press_through_keyboard_and_assistant() -> None:
    # Detect a wrong physical binding, repeated activation, release dispatch or wrong UI action.
    with observed_keyboard() as (keyboard, messages):
        hold_apps(keyboard, at=10)
        assert keyboard.engine.layer() is Layer.APPS
        key = inputs.KeyEvent(0, 0x32, 0, 250, 0)  # the right Enter thumb
        keyboard.swallow(key, down=True)
        keyboard.swallow(key, down=True)
        keyboard.swallow(inputs.KeyEvent(0, 0x32, 0, 280, 0), down=False)
        keyboard.swallow(inputs.KeyEvent(0, APPS_THUMB, 0, 300, 0), down=False)
        requests = tuple((tool, down) for message, tool, down in messages if message == WM_REQUEST)
        assert requests == ((Tool.OPEN_INBOX.value, 1), (Tool.OPEN_INBOX.value, 0))
        assert not keyboard.pressed and keyboard.engine.layer() is None
        actions = tuple(control_event(WindowInput(WM_REQUEST, tool, down), APPS) for tool, down in requests)
        assert actions == (FeatureRequest(Tool.OPEN_INBOX, down=True), FeatureRequest(Tool.OPEN_INBOX, down=False))


def test_overlay_handle_accepts_mouse_input_without_taking_keyboard_focus() -> None:
    hwnd = windows.create_hidden("Workspace overlay style fixture")
    try:
        _SetWindowLong(hwnd, -20, 0x28)
        windows.make_overlay(hwnd)
        assert int(_GetWindowLong(hwnd, -20)) & 0x0808_00A0 == 0x0808_00A0
        windows.make_overlay(hwnd, click_through=False)
        assert int(_GetWindowLong(hwnd, -20)) & 0x0808_00A0 == 0x0808_0080
        assert int(_SendMessage(hwnd, 0x0021, 0, 0)) == 3
    finally:
        windows.destroy(hwnd)


def test_overlay_refuses_mouse_activation_but_still_delivers_other_messages() -> None:
    delivered: list[int] = []

    def default_message(hwnd: int, message: int, wparam: int, lparam: int) -> int | None:
        if message in (0x0201, 0x0082):
            delivered.append(message)
            return 7
        return None

    window = shell.AppWindow.create("Workspace overlay delivery " + uuid.uuid4().hex, default_message)
    try:
        windows.make_overlay(window.handle, click_through=False)
        assert int(_SendMessage(window.handle, 0x0021, 0, 0)) == 3
        assert int(_SendMessage(window.handle, 0x0201, 0, 0)) == 7
    finally:
        window.destroy()
    assert delivered == [0x0201, 0x0082]


def test_layout_output_preserves_snippets_but_assistant_input_resets_them() -> None:
    keyboard = Keyboard(KeyboardFixture())
    keyboard.foreground = 1
    keyboard.engine.restore(replace(keyboard.engine.state, typed=",,t"))
    assert not keyboard.swallow(inputs.KeyEvent(0x54, 0, 0, 0, LAYOUT_MAGIC), down=True)
    assert keyboard.engine.typed == ",,t"
    assert not keyboard.swallow(inputs.KeyEvent(0x48, 0, 0, 0, MAGIC), down=True)
    assert keyboard.engine.typed == ""


def test_native_arrow_reaches_apps_and_clears_snippets() -> None:
    keyboard = Keyboard(KeyboardFixture())
    keyboard.foreground = 1
    keyboard.engine.restore(replace(keyboard.engine.state, typed=",,t"))
    assert not keyboard.swallow(inputs.KeyEvent(0x25, 0x4B, inputs.LLKHF_EXTENDED, 0, 0), down=True)
    assert keyboard.engine.typed == ""


def test_physical_shift_arrow_selection_remains_native_with_layout_enabled() -> None:
    with observed_keyboard() as (keyboard, messages):
        assert bool(keyboard.engine.enabled)
        for vk, scancode in ((0x10, 0x2A), (0xA0, 0x2A), (0xA1, 0x36)):
            shift = inputs.KeyEvent(vk, scancode, 0, 0, 0)
            assert not keyboard.swallow(shift, down=True)
            for arrow_vk, arrow_scancode in ((0x25, 0x4B), (0x26, 0x48), (0x27, 0x4D), (0x28, 0x50)):
                arrow = inputs.KeyEvent(arrow_vk, arrow_scancode, inputs.LLKHF_EXTENDED, 1, 0)
                assert not keyboard.swallow(arrow, down=True)
                assert not keyboard.swallow(arrow, down=True)  # Holding an arrow still repeats.
                assert not keyboard.swallow(arrow, down=False)
            assert not keyboard.swallow(shift, down=False)
        assert messages == [] and not keyboard.pressed


def test_extended_keys_never_fall_into_layout_bindings_and_function_controls_remain_available() -> None:
    with observed_keyboard() as (keyboard, messages):
        for vk, scancode in ((0x0D, 0x1C), (0x12, 0x38), (0x2E, 0x53), (0x4D, 0x32)):
            for down in (True, False):
                assert keyboard.swallow(inputs.KeyEvent(vk, scancode, inputs.LLKHF_EXTENDED, 0, 0), down=down)
        assert messages == []
        for vk, scancode in ((0x70, 0x3B), (0x7B, 0x58), (0xAD, 0x20), (0xAE, 0x2E), (0xAF, 0x30), (0xB3, 0x22), (0x5B, 0x5B)):
            for down in (True, False):
                assert not keyboard.swallow(inputs.KeyEvent(vk, scancode, inputs.LLKHF_EXTENDED, 0, 0), down=down)
        assert messages == []
        for down in (True, False):
            assert not keyboard.swallow(inputs.KeyEvent(0xA3, 0x1D, inputs.LLKHF_EXTENDED, 0, 0), down=down)
        keyboard.engine.restore(replace(keyboard.engine.state, enabled=False))
        for vk, scancode in ((0x0D, 0x1C), (0x11, 0x1D), (0x12, 0x38), (0x2E, 0x53)):
            for down in (True, False):
                assert not keyboard.swallow(inputs.KeyEvent(vk, scancode, inputs.LLKHF_EXTENDED, 0, 0), down=down)


def test_modifiers_pressed_while_disabled_can_release_after_enabling_the_layout() -> None:
    with observed_keyboard() as (keyboard, messages):
        for vk, scancode, flags in ((0xA2, 0x1D, 0), (0xA3, 0x1D, inputs.LLKHF_EXTENDED)):
            keyboard.engine.restore(replace(keyboard.engine.state, enabled=False))
            assert not keyboard.swallow(inputs.KeyEvent(vk, scancode, flags, 0, 0), down=True)
            keyboard.engine.restore(replace(keyboard.engine.state, enabled=True))
            assert not keyboard.swallow(inputs.KeyEvent(vk, scancode, flags, 1, 0), down=False)
            assert not keyboard.swallow(inputs.KeyEvent(vk, scancode, flags, 2, 0), down=True)
            assert not keyboard.swallow(inputs.KeyEvent(vk, scancode, flags, 3, 0), down=False)
        assert messages == []


def test_native_function_key_clears_a_partial_snippet_without_remapping() -> None:
    with observed_keyboard() as (keyboard, messages):
        keyboard.engine.restore(replace(keyboard.engine.state, typed=",,t"))
        assert not keyboard.swallow(inputs.KeyEvent(0x70, 0x3B, 0, 0, 0), down=True)
        assert keyboard.engine.typed == ""
        assert messages == []


def test_layout_replies_to_queries_and_tray_toggles_without_key_injection() -> None:
    driver = KeyboardFixture()
    keyboard = Keyboard(driver)
    keyboard.on_message(WM_QUERY_LAYOUT_STATE)
    keyboard.on_message(WM_TOGGLE_LAYOUT)
    keyboard.on_message(WM_QUERY_LAYOUT_STATE)
    keyboard.on_message(WM_TOGGLE_LAYOUT)
    for side in Side:
        states = [wparam for message, wparam, _ in driver.to(side) if message == WM_LAYOUT_STATE]
        assert states == [LayoutState.ON.value, LayoutState.OFF.value, LayoutState.OFF.value, LayoutState.ON.value], side
    assert not keyboard.busy


def test_failed_key_release_during_tray_toggle_still_turns_the_layout_off() -> None:
    driver = KeyboardFixture()
    driver.send_error = OSError("input was refused")
    keyboard = Keyboard(driver)
    keyboard.engine.restore(replace(keyboard.engine.state, pressed=(Key.Q, *keyboard.engine.pressed[1:])))  # An output held before opening the tray.
    keyboard.on_message(WM_TOGGLE_LAYOUT)
    assert not bool(keyboard.engine.enabled)
    assert not keyboard.busy


def test_layout_query_includes_the_current_locked_layer_for_a_new_overlay() -> None:
    driver = KeyboardFixture()
    keyboard = Keyboard(driver)
    keyboard.engine.restore(replace(keyboard.engine.state, shown=Indicator(Layer.SYM, locked=True, caps_word=True, chord=False)))
    keyboard.on_message(WM_QUERY_LAYOUT_STATE)
    layers = [decode_indicator(wparam) for message, wparam, _ in driver.messages if message == WM_INDICATOR]
    assert layers == [(Layer.SYM.value, True, True)]


def test_a_bare_windows_key_tap_asks_the_assistant_for_the_taskbar_once() -> None:
    # Defects: the hook stops reporting taps now that the assistant has no hook
    # of its own, a home row Win (the layout's own output) is ignored, or
    # another program's injected Win toggles the taskbar.
    for flags, extra, expected in ((0, 0, 1), (inputs.LLKHF_INJECTED, LAYOUT_MAGIC, 1), (inputs.LLKHF_INJECTED, 0, 0)):
        driver = KeyboardFixture()
        keyboard = Keyboard(driver)
        for message in (system.WM_KEYDOWN, system.WM_KEYUP):
            driver.key = inputs.KeyEvent(0x5B, 0x5B, flags | inputs.LLKHF_EXTENDED, 10, extra)
            keyboard.hook_proc(0, message, 0)
        assert [m for m, _w, _l in driver.messages].count(WM_WINDOWS_KEY_TAP) == expected
