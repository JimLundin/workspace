"""Windows bindings at their boundaries, without touching the real keyboard."""

import queue
import sys
import threading
import unittest
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import cast
from unittest.mock import patch

if sys.platform != "win32":
    raise unittest.SkipTest("Windows bindings")

from assistant.activity import ActivityTracker
from assistant.app import AssistantApp
from assistant.communications_service import Communications
from assistant.desktop import WinDesktop
from assistant.lifecycle import Timings
from assistant.llm import Settings
from assistant.meeting_store import MeetingArchive
from assistant.meeting_workflow import MeetingWorkflow
from assistant.meetings import Meetings
from assistant.monitor_layout import MonitorLayout
from assistant.overlay import OverlayState
from assistant.tiling import GlazeWM
from assistant.ui import Ui
from miryoku.engine import Indicator
from miryoku.layout import AGENT, DICTATE_TOGGLE, ESCAPE, TALK, Key, Layer, Scancode
from miryoku.win import Keyboard, WinHost
from protocol import (
    LAYOUT_MAGIC,
    LAYOUT_WINDOW,
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
from winapi import audio, inputs, recording, shell, system, windows
from winapi.shapes import Rect

from .test_work_agent import WorkRig


@contextmanager
def observed_keyboard() -> Generator[tuple[Keyboard, list[tuple[int, int, int]]]]:
    """Capture notifications while keeping keyboard output and timers off the desktop."""
    messages: list[tuple[int, int, int]] = []

    def notify(message: int, wparam: int, lparam: int) -> bool:
        messages.append((message, wparam, lparam))
        return True

    with (
        patch("miryoku.win.inputs.cursor_position", return_value=(0, 0)),
        patch("miryoku.win.windows.foreground", return_value=1),
        patch("miryoku.win.WinHost.tell_assistant", side_effect=notify),
        patch("miryoku.win.WinHost.send"),
        patch("miryoku.win.WinHost.start_timer", return_value=17),
        patch("miryoku.win.WinHost.stop_timer"),
        patch("miryoku.win.system.beep"),
        patch("miryoku.win.traceback.print_exc"),
    ):
        yield Keyboard(), messages


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
    with observed_keyboard() as (keyboard, messages), patch('miryoku.win.windows.title', return_value='Workspace window switcher'):
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
    with (
        patch("miryoku.win.inputs.cursor_position", return_value=(0, 0)),
        patch("miryoku.win.inputs.read_key_event", side_effect=RuntimeError("Read failed")),
        patch("miryoku.win.Engine.release_all", side_effect=OSError("Release failed")),
        patch("miryoku.win.WinHost.release_owned", side_effect=OSError("Retry failed")),
        patch("miryoku.win.WinHost.tell_assistant", side_effect=OSError("Post failed")),
        patch("miryoku.win.inputs.call_next_hook", return_value=7),
        patch("miryoku.win.usage.record") as record,
    ):
        keyboard = Keyboard()
        assert keyboard.hook_proc(0, 0x0100, 1) == 7
        assert not keyboard.engine.enabled and not keyboard.busy
        assert keyboard.fault is not None and keyboard.fault.kind == "RuntimeError"
        record.assert_not_called()
        keyboard.maintenance()
        record.assert_called_once()


def test_rejected_chord_releases_its_added_modifier_and_defers_diagnostics() -> None:
    output: list[tuple[int, int]] = []

    def send(vk: int, scancode: int, flags: int, extra: int) -> None:
        output.append((vk, flags))
        if vk == Key.LBRACKET.vk and not flags & inputs.KEYEVENTF_KEYUP:
            raise OSError("Sensitive content must not enter recovery logs")

    with (
        patch("miryoku.win.inputs.cursor_position", return_value=(0, 0)),
        patch("miryoku.win.windows.foreground", return_value=0),
        patch("miryoku.win.inputs.read_key_event", return_value=inputs.KeyEvent(0x32, 0x03, 0, 10, 0)),
        patch("miryoku.win.inputs.send_key", side_effect=send),
        patch("miryoku.win.inputs.scancode_for", return_value=0),
        patch("miryoku.win.WinHost.tell_assistant", return_value=True),
        patch("miryoku.win.inputs.call_next_hook", return_value=7),
        patch("miryoku.win.usage.record") as record,
    ):
        keyboard = Keyboard()
        keyboard.engine.locked = Layer.SYM
        assert keyboard.hook_proc(0, 0x0100, 1) == 7
        assert not keyboard.engine.enabled and not keyboard.host.owned
        assert (0xA0, inputs.KEYEVENTF_KEYUP) in output
        record.assert_not_called()
        keyboard.maintenance()
        record.assert_called_once()
        assert "Sensitive content" not in str(record.call_args)


def test_native_output_ownership_survives_rejection_until_release_is_accepted() -> None:
    host = WinHost()
    with patch("miryoku.win.inputs.scancode_for", return_value=0), patch("miryoku.win.inputs.send_key", side_effect=OSError("Rejected")):
        with unittest.TestCase().assertRaises(OSError):
            host.send(Key.A, True)
        assert host.owned == {Key.A}
        host.release_owned()
        assert host.owned == {Key.A}
    with patch("miryoku.win.inputs.scancode_for", return_value=0), patch("miryoku.win.inputs.send_key"):
        host.release_owned()
        assert not host.owned


def test_recovery_retries_are_bounded_and_enabling_waits_for_accepted_releases() -> None:
    with (
        patch("miryoku.win.inputs.cursor_position", return_value=(0, 0)),
        patch("miryoku.win.inputs.scancode_for", return_value=0),
        patch("miryoku.win.inputs.send_key", side_effect=OSError("Rejected")) as send,
        patch("miryoku.win.WinHost.tell_assistant", return_value=True),
        patch("miryoku.win.system.beep"),
        patch("miryoku.win.usage.record"),
    ):
        keyboard = Keyboard()
        keyboard.host.owned.add(Key.A)
        keyboard.input_failed(OSError("Input rejected"))
        for _ in range(10):
            keyboard.maintenance()
        assert send.call_count == 6  # Immediate cleanup plus five timer attempts.
        assert not keyboard.recovery_ticks and keyboard.fault is None
        keyboard.on_message(WM_TOGGLE_LAYOUT)
        assert not keyboard.engine.enabled
        with patch("miryoku.win.inputs.send_key"):
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


def test_assistant_routes_physical_chords_and_resets_to_the_overlay(tmp_path: Path) -> None:
    shown: list[tuple[frozenset[Scancode], bool]] = []

    def show(pressed: frozenset[Scancode], *, reset: bool = False) -> None:
        shown.append((pressed, reset))

    with menu_app(LayoutState.ON, tmp_path) as app, patch.object(Ui, "show_pressed_keys", side_effect=show):
        app.ui = Ui.__new__(Ui)
        for key, down in ((0x32, 1), (0x10, 1), (0x10, 0), (0, 0)):
            assert app.on_message(1, WM_KEY_STATE, key, down) == 0
    assert shown == [
        (frozenset({Scancode(0x32)}), False),
        (frozenset({Scancode(0x32), Scancode(0x10)}), False),
        (frozenset({Scancode(0x32)}), False),
        (frozenset(), True),
    ]


def test_tools_t_opens_inbox_once_per_press_through_keyboard_and_assistant(tmp_path: Path) -> None:
    # Detect a wrong physical binding, repeated activation, release dispatch or wrong UI action.
    with observed_keyboard() as (keyboard, messages), menu_app(LayoutState.ON, tmp_path) as app:
        app.ui = Ui.__new__(Ui)
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
        with patch.object(Ui, "open_inbox") as open_inbox:
            for tool, down in requests:
                assert app.on_message(1, WM_REQUEST, tool, down) == 0
                open_inbox.assert_called_once_with(app.agent.show)


def test_overlay_handle_accepts_mouse_input_without_taking_keyboard_focus() -> None:
    styles: list[int] = []

    def set_style(hwnd: int, index: int, style: int) -> int:
        assert hwnd == 1 and index == -20
        styles.append(style)
        return 0

    with (
        patch("winapi.windows._GetWindowLongW", return_value=0x28),
        patch("winapi.windows._SetWindowLongW", side_effect=set_style),
        patch("winapi.windows._SetWindowSubclass", return_value=True),
    ):
        windows.make_overlay(1)
        windows.make_overlay(1, click_through=False)
    assert styles == [0x0808_00A8, 0x0808_0088]


def test_overlay_refuses_mouse_activation_but_still_delivers_other_messages() -> None:
    delivered: list[int] = []

    def default_message(hwnd: int, message: int, wparam: int, lparam: int) -> int:
        delivered.append(message)
        return 7

    with patch("winapi.windows._DefSubclassProc", side_effect=default_message), patch("winapi.windows._RemoveWindowSubclass"):
        assert windows.overlay_message(1, 0x0021, 0, 0, 0, 0) == 3  # MA_NOACTIVATE, without discarding the click
        assert windows.overlay_message(1, 0x0201, 0, 0, 0, 0) == 7  # button press
        assert windows.overlay_message(1, 0x0082, 0, 0, 0, 0) == 7  # final destruction
    assert delivered == [0x0201, 0x0082]


def test_layout_output_preserves_snippets_but_assistant_input_resets_them() -> None:
    with patch("miryoku.win.inputs.cursor_position", return_value=(0, 0)), patch("miryoku.win.windows.foreground", return_value=1):
        keyboard = Keyboard()
        keyboard.foreground = 1
        keyboard.engine.typed = ",,t"
        assert not keyboard.swallow(inputs.KeyEvent(0x54, 0, 0, 0, LAYOUT_MAGIC), True)
        assert keyboard.engine.typed == ",,t"
        assert not keyboard.swallow(inputs.KeyEvent(0x48, 0, 0, 0, MAGIC), True)
        assert keyboard.engine.typed == ""


def test_native_arrow_reaches_apps_and_clears_snippets() -> None:
    with patch("miryoku.win.inputs.cursor_position", return_value=(0, 0)), patch("miryoku.win.windows.foreground", return_value=1):
        keyboard = Keyboard()
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
    with patch("winapi.inputs._SendInput", return_value=0):
        try:
            inputs.send_keys([inputs.KeyStroke(0x41, True)], MAGIC)
        except OSError:
            pass
        else:
            raise AssertionError("rejected input must raise")


def test_extra_mouse_buttons_and_horizontal_scroll_preserve_native_flags() -> None:
    events: list[tuple[int, int, int]] = []

    def send(batch: Sequence[inputs.INPUT]) -> int:
        for event in batch:
            mouse = cast(inputs.MOUSEINPUT, cast(inputs.INPUT_UNION, event.u).mi)
            events.append((cast(int, mouse.dwFlags), cast(int, mouse.mouseData), cast(int, mouse.dwExtraInfo)))
        return len(batch)

    with patch("winapi.inputs._send", side_effect=send):
        inputs.mouse_button("x1", True, MAGIC)
        inputs.mouse_button("x1", False, MAGIC)
        inputs.mouse_button("x2", True, MAGIC)
        inputs.mouse_button("x2", False, MAGIC)
        inputs.scroll(2, MAGIC, horizontal=True)
        inputs.scroll(-1, MAGIC)
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
    states: list[int] = []

    def post_message(hwnd: int, message: int, wparam: int, lparam: int) -> bool:
        if message == WM_LAYOUT_STATE:
            states.append(wparam)
        return True

    with (
        patch("miryoku.win.inputs.cursor_position", return_value=(0, 0)),
        patch("miryoku.win.windows.find", return_value=1),
        patch("miryoku.win.system.post_message", side_effect=post_message),
        patch("miryoku.win.system.beep"),
    ):
        keyboard = Keyboard()
        keyboard.on_message(WM_QUERY_LAYOUT_STATE)
        keyboard.on_message(WM_TOGGLE_LAYOUT)
        keyboard.on_message(WM_QUERY_LAYOUT_STATE)
        keyboard.on_message(WM_TOGGLE_LAYOUT)
        assert states == [LayoutState.ON.value, LayoutState.OFF.value, LayoutState.OFF.value, LayoutState.ON.value]
        assert not keyboard.busy


def test_failed_key_release_during_tray_toggle_still_turns_the_layout_off() -> None:
    with (
        patch("miryoku.win.inputs.cursor_position", return_value=(0, 0)),
        patch("miryoku.win.WinHost.send", side_effect=OSError("input was refused")),
        patch("miryoku.win.WinHost.tell_assistant"),
        patch("miryoku.win.system.beep"),
        patch("miryoku.win.traceback.print_exc"),
    ):
        keyboard = Keyboard()
        keyboard.engine.pressed[0] = Key.Q  # an output key held before the tray was opened
        keyboard.on_message(WM_TOGGLE_LAYOUT)
        assert not keyboard.engine.enabled
        assert not keyboard.busy


def test_layout_query_includes_the_current_locked_layer_for_a_new_overlay() -> None:
    layers: list[tuple[int, bool, bool]] = []

    def post_message(hwnd: int, message: int, wparam: int, lparam: int) -> bool:
        if message == WM_INDICATOR:
            layers.append(decode_indicator(wparam))
        return True

    with (
        patch("miryoku.win.inputs.cursor_position", return_value=(0, 0)),
        patch("miryoku.win.windows.find", return_value=1),
        patch("miryoku.win.system.post_message", side_effect=post_message),
    ):
        keyboard = Keyboard()
        keyboard.engine.shown = Indicator(Layer.SYM, True, True)
        keyboard.on_message(WM_QUERY_LAYOUT_STATE)
    assert layers == [(Layer.SYM.value, True, True)]


@contextmanager
def menu_app(state: LayoutState | None, folder: Path) -> Generator[AssistantApp]:
    """Only the state the menu needs; no native windows or microphone are opened."""
    app = AssistantApp.__new__(AssistantApp)
    app.timings = Timings("test startup")
    app.layout = state
    app.overlay = OverlayState(layout_on=state is LayoutState.ON)
    app.window = shell.AppWindow.__new__(shell.AppWindow)
    app.window.handle = 1
    rig = WorkRig(folder)
    app.agent = rig.agent
    app.settings = Settings("", "", "", "", "", "", "")
    app.tiling = GlazeWM()
    app.monitor_layout = MonitorLayout(app.tiling, lambda _: None)
    app.meetings = Meetings(
        app.settings, lambda source: recording.MeetingAudio(), archive=MeetingArchive(Path(__file__).parent / "missing-meeting-fixture"),
    )
    try:
        yield app
    finally:
        rig.close()


def check_layout_toggle(state: LayoutState, folder: Path) -> None:
    requests: list[int] = []

    def choose(window: int, items: Sequence[shell.MenuItem]) -> int:
        item = items[0]
        assert item.text == f"Layout: {state.name.lower()}\tTap §"
        assert item.enabled
        assert item.checked == (state is LayoutState.ON)
        return item.id

    def find(title: str) -> int:
        assert title == LAYOUT_WINDOW
        return 2

    def post_message(hwnd: int, message: int, wparam: int, lparam: int) -> bool:
        assert hwnd == 2
        requests.append(message)
        return True

    with (
        menu_app(state, folder) as app,
        patch.object(shell, "show_menu", side_effect=choose),
        patch("winapi.windows.find", side_effect=find),
        patch("assistant.app.system.post_message", side_effect=post_message),
    ):
        app.menu()
    assert requests == [WM_TOGGLE_LAYOUT]


def test_layout_status_is_the_toggle_and_shows_its_hotkey(tmp_path: Path) -> None:
    for state in (LayoutState.ON, LayoutState.OFF):
        check_layout_toggle(state, tmp_path)


def test_stopped_layout_has_a_start_action_and_no_active_toggle_hotkey(tmp_path: Path) -> None:
    def inspect_menu(window: int, items: Sequence[shell.MenuItem]) -> int:
        assert items[0].text == "Layout: not running"
        assert not items[0].enabled
        assert not items[0].checked
        assert items[1].text == "Start layout"
        assert items[1].enabled
        return 0

    with patch.object(shell, "show_menu", side_effect=inspect_menu):
        for state in (None, LayoutState.QUIT):
            with menu_app(state, tmp_path) as app:
                app.menu()


def test_tray_overlay_toggle_updates_and_remembers_the_preference(tmp_path: Path) -> None:
    saved: list[bool] = []
    shown: list[bool] = []

    def choose(window: int, items: Sequence[shell.MenuItem]) -> int:
        item = next(item for item in items if item.text == "Keyboard overlay")
        assert item.checked == app.overlay.enabled
        return item.id

    def show_overlay(work: Rect) -> None:
        shown.append(app.overlay.visible)

    with (
        menu_app(LayoutState.ON, tmp_path) as app,
        patch.object(shell, "show_menu", side_effect=choose),
        patch("assistant.app.indicator_area", return_value=Rect(0, 0, 1920, 1040)),
        patch("assistant.app.AssistantApp.show_overlay", side_effect=show_overlay),
        patch("assistant.app.save_enabled", side_effect=saved.append),
    ):
        app.menu()
        app.menu()
    assert shown == [False, True]
    assert saved == [False, True]


def test_assistant_queries_a_layout_that_started_before_it(tmp_path: Path) -> None:
    requests: list[int] = []

    def post_message(hwnd: int, message: int, wparam: int, lparam: int) -> bool:
        assert hwnd == 2
        requests.append(message)
        return True

    with (
        menu_app(None, tmp_path) as app,
        patch("winapi.windows.find", return_value=2),
        patch("assistant.app.system.post_message", side_effect=post_message),
        patch("assistant.app.system.run_message_loop"),
        patch("assistant.app.system.set_window_timer", return_value=1),
        patch("assistant.app.keeper.ready"),
        patch.object(Ui, "desktop"),
        patch.object(MeetingWorkflow, "start"),
        patch.object(Communications, "start"),
        patch.object(MonitorLayout, "start") as auto_tiling,
        patch("threading.Thread.start"),
    ):
        app.ui = Ui.__new__(Ui)
        app.followups = MeetingWorkflow.__new__(MeetingWorkflow)
        app.communications = Communications.__new__(Communications)
        app.activity = ActivityTracker(lambda: "unavailable", lambda: False, enabled=False)
        app.worker = threading.Thread()
        app.desktop = WinDesktop.__new__(WinDesktop)
        app.desktop.mic = audio.Microphone.__new__(audio.Microphone)
        app.run()
        auto_tiling.assert_called_once()
    assert requests == [WM_QUERY_LAYOUT_STATE]


def test_meeting_file_handoff_keeps_canonical_path_and_reports_shell_failure(tmp_path: Path) -> None:
    app = AssistantApp.__new__(AssistantApp)
    app.jobs = queue.Queue()
    path = tmp_path / "saved-follow-up.eml"
    opened: list[Path] = []
    problems: list[str] = []

    def unavailable(target: Path) -> None:
        opened.append(target)
        raise OSError("The registered application cannot open this path")

    with patch("assistant.app.os.startfile", side_effect=unavailable), patch.object(AssistantApp, "problem", side_effect=problems.append):
        app.open_meeting_file(path)
        assert not opened and not problems
        job = app.jobs.get_nowait()
        assert job is not None
        job()
    assert opened == [path]
    assert problems == ["Windows could not open this file. You can still review it in Meetings."]
