"""Windows bindings at their boundaries, without touching the real keyboard."""

import ctypes
import queue
import sys
import unittest
import uuid
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from typing import cast

if sys.platform != "win32":
    raise unittest.SkipTest("Windows bindings")

from assistant.control_policy import (
    Action,
    FeatureRequest,
    Menu,
    MenuState,
    OverlayChange,
    PhysicalKey,
    WindowInput,
    change_overlay,
    control_event,
    initialize_controls,
    meeting_file_job,
    menu_items,
    toggle_layout,
)
from assistant.overlay import OverlayState, load_enabled, save_enabled
from config import APPS
from keeper import LAYOUT_WINDOW
from miryoku.engine import Indicator
from miryoku.layout import AGENT, DICTATE_TOGGLE, ESCAPE, TALK, Key, Layer, Mod, Scancode
from miryoku.win import Keyboard, WinHost
from protocol import (
    LAYOUT_MAGIC,
    MAGIC,
    WM_INDICATOR,
    WM_KEY_STATE,
    WM_LAYOUT_STATE,
    WM_QUERY_LAYOUT_STATE,
    WM_REQUEST,
    WM_TOGGLE_LAYOUT,
    LayoutState,
    Tool,
    decode_indicator,
)
from tests.test_engine import Harness
from usage import Detail
from winapi import inputs, shell, system, windows
from winapi._core import LRESULT, fn, user32

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
        self.key = inputs.KeyEvent(0, 0, 0, 0, 0)
        self.read_error: Exception | None = None
        self.send_error: Exception | None = None
        self.delivery_error: Exception | None = None
        self.reject_down: Key | Mod | None = None
        self.messages: list[tuple[int, int, int]] = []
        self.output: list[tuple[Key | Mod, bool]] = []
        self.recoveries: list[tuple[tuple[str, Detail], ...]] = []
        self.usage: list[tuple[tuple[str, int], ...]] = []

    def send_key(self, key: Key | Mod, *, down: bool) -> None:
        self.output.append((key, down))
        if self.send_error is not None:
            raise self.send_error
        if down and key is self.reject_down:
            raise OSError("Sensitive content must not enter recovery logs")

    def cursor_position(self) -> tuple[int, int]:
        return 0, 0

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

    def find_assistant(self) -> int | None:
        return 1

    # Keep the native delivery fields together in the concrete driver fixture.
    def post_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> bool:
        if self.delivery_error is not None:
            raise self.delivery_error
        self.messages.append((message, wparam, lparam))
        return True

    def set_timer(self, ms: int) -> int:
        return 17

    def kill_timer(self, timer: int) -> None:
        pass

    def beep(self, sound: int) -> None:
        pass

    def type_text(self, text: str) -> None:
        pass

    def record_recovery(self, details: Mapping[str, Detail]) -> None:
        self.recoveries.append(tuple(details.items()))

    def record_counts(self, counts: Mapping[str, int]) -> None:
        self.usage.append(tuple(counts.items()))

    def post_quit(self) -> None:
        pass


@contextmanager
def observed_keyboard(*, platform: KeyboardFixture | None = None) -> Generator[tuple[Keyboard, list[tuple[int, int, int]]]]:
    """Use the same driver seam for input observations and captured notifications."""
    driver = platform if platform is not None else KeyboardFixture()
    yield Keyboard(driver), driver.messages


def test_physical_press_is_reported_before_a_tap_hold_is_resolved() -> None:
    with observed_keyboard() as (keyboard, messages):
        key = inputs.KeyEvent(0x4D, 0x32, 0, 10, 0)  # M: Enter/Symbols thumb
        assert keyboard.swallow(key, True)
        assert messages == [(WM_KEY_STATE, 0x32, 1)]
        assert keyboard.engine.layer() is None
        assert keyboard.pressed == {Scancode(0x32)}
        keyboard.swallow(key, True)  # auto-repeat must not refresh the highlight
        assert messages == [(WM_KEY_STATE, 0x32, 1)]
        keyboard.swallow(inputs.KeyEvent(0x4D, 0x32, 0, 40, 0), False)
        keyboard.swallow(inputs.KeyEvent(0x4D, 0x32, 0, 41, 0), False)
        assert messages == [(WM_KEY_STATE, 0x32, 1), (WM_KEY_STATE, 0x32, 0)]
        assert not keyboard.pressed


def test_generated_and_extended_input_does_not_light_physical_keys() -> None:
    for flags, extra in ((0, LAYOUT_MAGIC), (0, MAGIC), (inputs.LLKHF_INJECTED, 0), (inputs.LLKHF_EXTENDED, 0)):
        with observed_keyboard() as (keyboard, messages):
            keyboard.swallow(inputs.KeyEvent(0x4D, 0x32, flags, 10, extra), True)
            keyboard.swallow(inputs.KeyEvent(0x4D, 0x32, flags, 40, extra), False)
            assert not any(message == WM_KEY_STATE for message, _, _ in messages)
            assert not keyboard.pressed


def test_voice_and_unused_keys_light_up_but_unpictured_keys_do_not() -> None:
    with observed_keyboard() as (keyboard, messages):
        for scancode in (TALK, AGENT, 0x15, 0x56, 0x35, DICTATE_TOGGLE):
            keyboard.swallow(inputs.KeyEvent(0, scancode, 0, 10, 0), True)
            keyboard.swallow(inputs.KeyEvent(0, scancode, 0, 40, 0), False)
        keys = [(scancode, down) for message, scancode, down in messages if message == WM_KEY_STATE]
        assert keys == [(scancode, down) for scancode in (TALK, AGENT, 0x15, 0x56, 0x35, DICTATE_TOGGLE) for down in (1, 0)]


def test_n_toggles_agent_voice_immediately_and_updates_its_highlight() -> None:
    with observed_keyboard() as (keyboard, messages):
        control = inputs.KeyEvent(0xA2, 0x1D, 0, 0, 0)
        assert not keyboard.swallow(control, True)
        key = inputs.KeyEvent(0x4E, AGENT, 0, 10, 0)
        assert keyboard.swallow(key, True)
        assert messages == [(WM_KEY_STATE, AGENT, 1), (WM_REQUEST, Tool.AGENT_VOICE_TOGGLE.value, 1)]
        assert keyboard.pressed == {AGENT}
        keyboard.swallow(key, True)
        assert not keyboard.swallow(control, False)
        keyboard.swallow(inputs.KeyEvent(0x4E, AGENT, 0, 300, 0), False)
        assert messages == [
            (WM_KEY_STATE, AGENT, 1), (WM_REQUEST, Tool.AGENT_VOICE_TOGGLE.value, 1),
            (WM_KEY_STATE, AGENT, 0), (WM_REQUEST, Tool.AGENT_VOICE_TOGGLE.value, 0),
        ]
        assert not keyboard.pressed


def test_native_modifier_released_after_enabling_does_not_stick_to_space() -> None:
    with observed_keyboard() as (keyboard, messages):
        control = inputs.KeyEvent(0xA2, 0x1D, 0, 10, 0)
        keyboard.engine.enabled = False
        assert not keyboard.swallow(control, True)
        keyboard.engine.enabled = True
        assert not keyboard.swallow(control, False)
        keyboard.swallow(inputs.KeyEvent(0x20, 0x39, 0, 20, 0), True)
        assert (WM_REQUEST, Tool.DICTATE.value, 1) in messages


def test_f6_stays_native_and_b_uses_one_toggle_per_press() -> None:
    with observed_keyboard() as (keyboard, messages):
        shift = inputs.KeyEvent(0xA0, 0x2A, 0, 0, 0)
        assert not keyboard.swallow(shift, True)
        key = inputs.KeyEvent(0x42, DICTATE_TOGGLE, 0, 10, 0)
        keyboard.swallow(key, True)
        keyboard.swallow(key, True)
        keyboard.swallow(key, False)
        requests = [(tool, down) for message, tool, down in messages if message == WM_REQUEST]
        assert requests == [(Tool.DICTATE_TOGGLE.value, 1), (Tool.DICTATE_TOGGLE.value, 0)]
        messages.clear()
        function = inputs.KeyEvent(0x75, 0x40, 0, 30, 0)
        assert not keyboard.swallow(function, True)
        assert not keyboard.swallow(function, False)
        assert not any(message == WM_REQUEST for message, _tool, _down in messages)


def test_physical_arrows_navigate_apps_and_release_cleanly_after_the_thumb() -> None:
    with observed_keyboard() as (keyboard, messages):
        thumb = inputs.KeyEvent(0xBE, 0x34, 0, 0, 0)
        control = inputs.KeyEvent(0xA2, 0x1D, 0, 10, 0)
        arrow = inputs.KeyEvent(0x27, 0x4D, inputs.LLKHF_EXTENDED, 20, 0)
        assert keyboard.swallow(thumb, True)
        assert not keyboard.swallow(control, True)
        assert keyboard.swallow(arrow, True)
        assert keyboard.swallow(thumb, False)
        assert keyboard.swallow(arrow, False)
        assert not keyboard.swallow(control, False)
        assert (WM_REQUEST, Tool.TILE_FOCUS_RIGHT.value, 1) in messages
        assert (WM_REQUEST, Tool.TILE_FOCUS_RIGHT.value, 0) in messages
        assert not keyboard.engine.desktop_held
        assert not keyboard.swallow(arrow, True)
        assert not keyboard.swallow(arrow, False)


def test_picker_enter_release_passes_after_the_selected_window_takes_focus() -> None:
    driver = KeyboardFixture()
    driver.current_title = "Workspace window switcher"
    with observed_keyboard(platform=driver) as (keyboard, messages):
        keyboard.foreground = 0
        enter = inputs.KeyEvent(0x0D, 0x1C, 0, 0, 0)
        assert not keyboard.swallow(enter, True)
        keyboard.picker_active = False
        assert not keyboard.swallow(enter, False)
        assert not keyboard.native_releases and messages == []

def test_layout_query_resets_then_replays_all_physically_held_keys() -> None:
    with observed_keyboard() as (keyboard, messages):
        for scancode in (0x32, 0x10):
            keyboard.swallow(inputs.KeyEvent(0, scancode, 0, 10, 0), True)
        messages.clear()
        keyboard.on_message(WM_QUERY_LAYOUT_STATE)
        assert messages[0] == (WM_LAYOUT_STATE, LayoutState.ON.value, 0)
        assert messages[1][0] == WM_INDICATOR
        assert messages[2:] == [(WM_KEY_STATE, 0, 0), (WM_KEY_STATE, 0x10, 1), (WM_KEY_STATE, 0x32, 1)]


def test_toggle_and_input_failure_clear_held_keys() -> None:
    with observed_keyboard() as (keyboard, messages):
        key = inputs.KeyEvent(0x4D, 0x32, 0, 10, 0)
        keyboard.swallow(key, True)
        keyboard.on_message(WM_TOGGLE_LAYOUT)
        assert not keyboard.pressed
        assert messages[-1] == (WM_KEY_STATE, 0, 0)
        messages.clear()
        assert not keyboard.swallow(key, True)
        assert messages == []
        keyboard.on_message(WM_TOGGLE_LAYOUT)
        keyboard.swallow(key, True)
        keyboard.input_failed(OSError("Rejected input"))
        assert not keyboard.pressed
        assert (WM_KEY_STATE, 0, 0) in messages[-3:]
        assert not keyboard.engine.enabled


def test_hook_failure_passes_input_even_when_recovery_effects_also_fail() -> None:
    driver = KeyboardFixture()
    driver.read_error = RuntimeError("Read failed")
    driver.send_error = OSError("Release failed")
    driver.delivery_error = OSError("Post failed")
    keyboard = Keyboard(driver)
    keyboard.engine.pressed[0] = Key.A
    keyboard.host.owned.add(Key.A)
    assert keyboard.hook_proc(0, 0x0100, 1) == 7
    assert not keyboard.engine.enabled and not keyboard.busy
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
    keyboard.engine.locked = Layer.SYM
    assert keyboard.hook_proc(0, 0x0100, 1) == 7
    assert not keyboard.engine.enabled and not keyboard.host.owned
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
        host.send(Key.A, True)
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
    assert not keyboard.engine.enabled
    driver.send_error = None
    keyboard.on_message(WM_TOGGLE_LAYOUT)
    assert keyboard.engine.enabled and not keyboard.host.owned

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


def test_escape_toggle_clears_highlights_with_other_keys_still_held() -> None:
    with observed_keyboard() as (keyboard, messages):
        keyboard.swallow(inputs.KeyEvent(0, 0x32, 0, 10, 0), True)
        keyboard.swallow(inputs.KeyEvent(0, ESCAPE, 0, 20, 0), True)
        keyboard.swallow(inputs.KeyEvent(0, ESCAPE, 0, 40, 0), False)
        assert not keyboard.engine.enabled
        assert not keyboard.pressed
        assert messages[-1] == (WM_KEY_STATE, 0, 0)


def test_assistant_routes_physical_chords_and_resets_to_the_overlay() -> None:
    """Detect native key messages routed as tools or losing their reset marker."""
    actions = tuple(control_event(WindowInput(WM_KEY_STATE, key, down), APPS)
                    for key, down in ((0x32, 1), (0x10, 1), (0x10, 0), (0, 0)))
    assert actions == (
        PhysicalKey(Scancode(0x32), down=True), PhysicalKey(Scancode(0x10), down=True),
        PhysicalKey(Scancode(0x10), down=False), PhysicalKey(Scancode(0), down=False),
    )
    assert tuple(action.reset for action in actions if isinstance(action, PhysicalKey)) == (False, False, False, True)


def test_tools_t_opens_inbox_once_per_press_through_keyboard_and_assistant() -> None:
    # Detect a wrong physical binding, repeated activation, release dispatch or wrong UI action.
    with observed_keyboard() as (keyboard, messages):
        keyboard.swallow(inputs.KeyEvent(0x56, 0x2F, 0, 10, 0), True)
        keyboard.engine.timeout(keyboard.host, 17)
        assert keyboard.engine.layer() is Layer.TOOLS
        key = inputs.KeyEvent(0x54, 0x14, 0, 250, 0)
        keyboard.swallow(key, True)
        keyboard.swallow(key, True)
        keyboard.swallow(inputs.KeyEvent(0x54, 0x14, 0, 280, 0), False)
        keyboard.swallow(inputs.KeyEvent(0x56, 0x2F, 0, 300, 0), False)
        requests = tuple((tool, down) for message, tool, down in messages if message == WM_REQUEST)
        assert requests == ((Tool.OPEN_INBOX.value, 1), (Tool.OPEN_INBOX.value, 0))
        assert not keyboard.pressed and keyboard.engine.layer() is None
        actions = tuple(control_event(WindowInput(WM_REQUEST, tool, down), APPS) for tool, down in requests)
        assert actions == (Action.OPEN_INBOX, None)


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

    window = shell.AppWindow("Workspace overlay delivery " + uuid.uuid4().hex, default_message)
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
    keyboard.engine.typed = ",,t"
    assert not keyboard.swallow(inputs.KeyEvent(0x54, 0, 0, 0, LAYOUT_MAGIC), True)
    assert keyboard.engine.typed == ",,t"
    assert not keyboard.swallow(inputs.KeyEvent(0x48, 0, 0, 0, MAGIC), True)
    assert keyboard.engine.typed == ""

def test_native_arrow_reaches_apps_and_clears_snippets() -> None:
    keyboard = Keyboard(KeyboardFixture())
    keyboard.foreground = 1
    keyboard.engine.typed = ",,t"
    assert not keyboard.swallow(inputs.KeyEvent(0x25, 0x4B, inputs.LLKHF_EXTENDED, 0, 0), True)
    assert keyboard.engine.typed == ""

def test_physical_shift_arrow_selection_remains_native_with_layout_enabled() -> None:
    with observed_keyboard() as (keyboard, messages):
        assert keyboard.engine.enabled
        for vk, scancode in ((0x10, 0x2A), (0xA0, 0x2A), (0xA1, 0x36)):
            shift = inputs.KeyEvent(vk, scancode, 0, 0, 0)
            assert not keyboard.swallow(shift, True)
            for arrow_vk, arrow_scancode in ((0x25, 0x4B), (0x26, 0x48), (0x27, 0x4D), (0x28, 0x50)):
                arrow = inputs.KeyEvent(arrow_vk, arrow_scancode, inputs.LLKHF_EXTENDED, 1, 0)
                assert not keyboard.swallow(arrow, True)
                assert not keyboard.swallow(arrow, True)  # Holding an arrow still repeats.
                assert not keyboard.swallow(arrow, False)
            assert not keyboard.swallow(shift, False)
        assert messages == [] and not keyboard.pressed


def test_extended_keys_never_fall_into_layout_bindings_and_function_controls_remain_available() -> None:
    with observed_keyboard() as (keyboard, messages):
        for vk, scancode in ((0x0D, 0x1C), (0x12, 0x38), (0x2E, 0x53), (0x4D, 0x32)):
            for down in (True, False):
                assert keyboard.swallow(inputs.KeyEvent(vk, scancode, inputs.LLKHF_EXTENDED, 0, 0), down)
        assert messages == []
        for vk, scancode in ((0x70, 0x3B), (0x7B, 0x58), (0xAD, 0x20), (0xAE, 0x2E), (0xAF, 0x30), (0xB3, 0x22), (0x5B, 0x5B)):
            for down in (True, False):
                assert not keyboard.swallow(inputs.KeyEvent(vk, scancode, inputs.LLKHF_EXTENDED, 0, 0), down)
        assert messages == []
        for down in (True, False):
            assert not keyboard.swallow(inputs.KeyEvent(0xA3, 0x1D, inputs.LLKHF_EXTENDED, 0, 0), down)
        keyboard.engine.enabled = False
        for vk, scancode in ((0x0D, 0x1C), (0x11, 0x1D), (0x12, 0x38), (0x2E, 0x53)):
            for down in (True, False):
                assert not keyboard.swallow(inputs.KeyEvent(vk, scancode, inputs.LLKHF_EXTENDED, 0, 0), down)


def test_modifiers_pressed_while_disabled_can_release_after_enabling_the_layout() -> None:
    with observed_keyboard() as (keyboard, messages):
        for vk, scancode, flags in ((0xA2, 0x1D, 0), (0xA3, 0x1D, inputs.LLKHF_EXTENDED)):
            keyboard.engine.enabled = False
            assert not keyboard.swallow(inputs.KeyEvent(vk, scancode, flags, 0, 0), True)
            keyboard.engine.enabled = True
            assert not keyboard.swallow(inputs.KeyEvent(vk, scancode, flags, 1, 0), False)
            assert not keyboard.swallow(inputs.KeyEvent(vk, scancode, flags, 2, 0), True)
            assert not keyboard.swallow(inputs.KeyEvent(vk, scancode, flags, 3, 0), False)
        assert messages == []


def test_native_function_key_clears_a_partial_snippet_without_remapping() -> None:
    with observed_keyboard() as (keyboard, messages):
        keyboard.engine.typed = ",,t"
        assert not keyboard.swallow(inputs.KeyEvent(0x70, 0x3B, 0, 0, 0), True)
        assert keyboard.engine.typed == ""
        assert messages == []


def test_rejected_sendinput_is_reported_without_real_injection() -> None:
    with unittest.TestCase().assertRaises(OSError):
        inputs.send_keys([inputs.KeyStroke(0x41, True)], MAGIC, submit=lambda events: 0)

def test_extra_mouse_buttons_and_horizontal_scroll_preserve_native_flags() -> None:
    events: list[tuple[int, int, int]] = []

    def send(batch: Sequence[inputs.INPUT]) -> int:
        for event in batch:
            mouse = cast(inputs.MOUSEINPUT, cast(inputs.INPUT_UNION, event.u).mi)
            events.append((cast(int, mouse.dwFlags), cast(int, mouse.mouseData), cast(int, mouse.dwExtraInfo)))
        return len(batch)

    inputs.mouse_button("x1", MAGIC, down=True, submit=send)
    inputs.mouse_button("x1", MAGIC, down=False, submit=send)
    inputs.mouse_button("x2", MAGIC, down=True, submit=send)
    inputs.mouse_button("x2", MAGIC, down=False, submit=send)
    inputs.scroll(2, MAGIC, horizontal=True, submit=send)
    inputs.scroll(-1, MAGIC, submit=send)
    assert events == [
        (0x80, 1, MAGIC), (0x100, 1, MAGIC), (0x80, 2, MAGIC), (0x100, 2, MAGIC),
        (0x1000, 240, MAGIC), (0x800, 0xFFFF_FF88, MAGIC),
    ]

def test_snippets_still_expand_with_tagged_layout_output() -> None:
    rig = Harness()
    for name in (";", ";", "r", "l", "a"):
        rig.tap(name)
    assert "~Thanks!" in rig.take()


def test_layout_replies_to_queries_and_tray_toggles_without_key_injection() -> None:
    driver = KeyboardFixture()
    keyboard = Keyboard(driver)
    keyboard.on_message(WM_QUERY_LAYOUT_STATE)
    keyboard.on_message(WM_TOGGLE_LAYOUT)
    keyboard.on_message(WM_QUERY_LAYOUT_STATE)
    keyboard.on_message(WM_TOGGLE_LAYOUT)
    states = [wparam for message, wparam, _ in driver.messages if message == WM_LAYOUT_STATE]
    assert states == [LayoutState.ON.value, LayoutState.OFF.value, LayoutState.OFF.value, LayoutState.ON.value]
    assert not keyboard.busy

def test_failed_key_release_during_tray_toggle_still_turns_the_layout_off() -> None:
    driver = KeyboardFixture()
    driver.send_error = OSError("input was refused")
    keyboard = Keyboard(driver)
    keyboard.engine.pressed[0] = Key.Q  # An output held before opening the tray.
    keyboard.on_message(WM_TOGGLE_LAYOUT)
    assert not keyboard.engine.enabled
    assert not keyboard.busy

def test_layout_query_includes_the_current_locked_layer_for_a_new_overlay() -> None:
    driver = KeyboardFixture()
    keyboard = Keyboard(driver)
    keyboard.engine.shown = Indicator(Layer.SYM, True, True)
    keyboard.on_message(WM_QUERY_LAYOUT_STATE)
    layers = [decode_indicator(wparam) for message, wparam, _ in driver.messages if message == WM_INDICATOR]
    assert layers == [(Layer.SYM.value, True, True)]

class LayoutFixture:
    """Own observed layout identity and native-effect receipts for this interface."""

    def __init__(self, handle: int | None) -> None:
        self.handle = handle
        self.messages: tuple[tuple[int, int, int, int], ...] = ()
        self.timeline: tuple[str, ...] = ()

    def find_window(self, title: str) -> int | None:
        assert title == LAYOUT_WINDOW
        self.timeline += ("find layout",)
        return self.handle

    # The four fields belong to one native message, not independent options.
    def post(self, handle: int, message: int, wparam: int, lparam: int) -> bool:
        self.messages += ((handle, message, wparam, lparam),)
        self.timeline += ("post layout",)
        return True

    def start_timer(self, handle: int) -> int:
        assert handle == 7
        self.timeline += ("timer",)
        return 17

    def start_workers(self) -> None:
        assert self.timeline == ("timer",)
        self.timeline += ("workers",)

    def ready(self) -> None:
        self.timeline += ("ready",)


class OverlayFixture:
    """A fully constructed preference adapter with real local persistence."""

    def __init__(self, overlay: OverlayState, path: Path) -> None:
        self.overlay, self.path = overlay, path
        self.shown: tuple[bool, ...] = ()

    def display_overlay(self, change: OverlayChange) -> None:
        self.overlay.enabled = change.enabled
        self.shown += (self.overlay.visible,)

    def persist_overlay(self, change: OverlayChange) -> None:
        save_enabled(change.enabled, self.path)


def test_layout_status_is_the_toggle_and_shows_its_hotkey() -> None:
    for layout in (LayoutState.ON, LayoutState.OFF):
        state = MenuState(layout=layout, overlay_enabled=True, agent_running=False, capturing=False)
        item = menu_items(state)[0]
        assert item.id == Menu.TOGGLE_LAYOUT.value
        assert item.text == f"Layout: {layout.name.lower()}\tTap §"
        assert item.enabled and item.checked == (layout is LayoutState.ON)
        effects = LayoutFixture(2)
        assert toggle_layout(effects)
        assert effects.messages == ((2, WM_TOGGLE_LAYOUT, 0, 0),)


def test_stopped_layout_has_a_start_action_and_no_active_toggle_hotkey() -> None:
    for layout in (None, LayoutState.QUIT):
        state = MenuState(layout=layout, overlay_enabled=True, agent_running=False, capturing=False)
        items = menu_items(state)
        assert items[0].text == "Layout: not running"
        assert not items[0].enabled and not items[0].checked
        assert items[1].id == Menu.RESTART_LAYOUT.value and items[1].text == "Start layout" and items[1].enabled
    unavailable = LayoutFixture(None)
    assert not toggle_layout(unavailable) and not unavailable.messages


def test_tray_overlay_toggle_updates_and_remembers_the_preference(tmp_path: Path) -> None:
    effects = OverlayFixture(OverlayState(layout_on=True), tmp_path / "overlay.json")
    for enabled in (False, True):
        assert change_overlay(OverlayChange(enabled=enabled), effects) is None
        assert load_enabled(effects.path) is enabled
        state = MenuState(layout=LayoutState.ON, overlay_enabled=enabled, agent_running=False, capturing=False)
        item = next(item for item in menu_items(state) if item.id == Menu.OVERLAY.value)
        assert item.checked is enabled
    assert effects.shown == (False, True)


def test_overlay_feedback_survives_a_preference_write_failure(tmp_path: Path) -> None:
    """Detect persistence failure preventing feedback or silently reporting success."""
    destination = tmp_path / "directory"
    destination.mkdir()
    effects = OverlayFixture(OverlayState(layout_on=True), destination)
    problem = change_overlay(OverlayChange(enabled=False), effects)
    assert effects.shown == (False,)
    assert problem == "The overlay changed, but its setting couldn't be saved."


def test_assistant_queries_a_layout_that_started_before_it() -> None:
    """Detect readiness announced before worker startup or without layout replay."""
    for layout in (2, None):
        effects = LayoutFixture(layout)
        assert initialize_controls(7, effects.start_workers, effects) == 17
        if layout is None:
            assert effects.messages == ()
            assert effects.timeline == ("timer", "workers", "find layout", "ready")
        else:
            assert effects.messages == ((2, WM_QUERY_LAYOUT_STATE, 0, 0),)
            assert effects.timeline == ("timer", "workers", "find layout", "post layout", "ready")


def test_meeting_file_handoff_keeps_canonical_path_and_reports_shell_failure(tmp_path: Path) -> None:
    path = tmp_path / "saved-follow-up.eml"
    opened: list[Path] = []
    problems: list[str] = []
    def unavailable(target: Path) -> None:
        opened.append(target)
        raise OSError("The registered application cannot open this path")
    jobs: queue.Queue[Callable[[], None]] = queue.Queue()
    jobs.put(meeting_file_job(path, unavailable, problems.append))
    assert not opened and not problems
    jobs.get_nowait()()
    assert opened == [path]
    assert problems == ["Windows could not open this file. You can still review it in Meetings."]


def test_control_event_gates_desktop_actions_without_losing_voice_release() -> None:
    """Detect press-only UI actions on release or dropping a capture's key-up."""
    choices = ((Tool.WINDOW_SWITCHER, Action.SWITCH_WINDOWS), (Tool.OPEN_INBOX, Action.OPEN_INBOX),
               (Tool.MEETING_TOGGLE, Action.TOGGLE_MEETING), (Tool.TILE_BALANCE, Action.BALANCE_WINDOWS))
    for tool, action in choices:
        assert control_event(WindowInput(WM_REQUEST, tool.value, 1), APPS) is action
        assert control_event(WindowInput(WM_REQUEST, tool.value, 0), APPS) is None
    assert control_event(WindowInput(WM_REQUEST, Tool.DICTATE.value, 1), APPS) == FeatureRequest(Tool.DICTATE, down=True)
    assert control_event(WindowInput(WM_REQUEST, Tool.DICTATE.value, 0), APPS) == FeatureRequest(Tool.DICTATE, down=False)
    assert control_event(WindowInput(WM_REQUEST, 999, 1), APPS) is None
