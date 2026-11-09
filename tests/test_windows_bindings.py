"""Window messages and styles the layout and overlay rely on, on real hidden windows."""

import ctypes
import sys
import unittest
import uuid
from ctypes import wintypes

if sys.platform != "win32":
    raise unittest.SkipTest("Windows bindings")


from winapi import shell, system, windows
from winapi._core import LRESULT, fn, user32

_SendMessage = fn(user32, "SendMessageW", LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


_GetWindowLong = fn(user32, "GetWindowLongW", wintypes.LONG, wintypes.HWND, ctypes.c_int)


_SetWindowLong = fn(user32, "SetWindowLongW", wintypes.LONG, wintypes.HWND, ctypes.c_int, wintypes.LONG)


def test_capture_watchdog_timer_is_delivered_to_its_hidden_window() -> None:
    hwnd = windows.create_hidden("Workspace watchdog fixture")
    timer = system.set_window_timer(hwnd, 20)
    try:
        message = next(system.messages())
        while message.message != system.WindowMessage.TIMER:
            message = next(system.messages())
        assert message.hwnd == hwnd and message.wparam == timer
    finally:
        windows.destroy(hwnd)  # which kills its timer


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
