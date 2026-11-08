"""Foreground changes, Alt+Tab switches and mouse captures, observed through
out-of-context WinEvent hooks on a thread of their own.

Out-of-context events are delivered to the hooking thread while it waits for
messages, so the hooks need a thread that does nothing but wait. Workspace's own
windows are skipped, and nothing about a window is read except its handle.
"""

import ctypes
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Final

from winapi import system
from winapi._core import GetAsyncKeyState, fn, user32

_EVENT_SYSTEM_FOREGROUND: Final = 0x0003
_EVENT_SYSTEM_CAPTURESTART: Final = 0x0008
_EVENT_SYSTEM_SWITCHSTART, _EVENT_SYSTEM_SWITCHEND = 0x0014, 0x0015
_WINEVENT_OUTOFCONTEXT, _WINEVENT_SKIPOWNPROCESS = 0x0000, 0x0002
_OBJID_WINDOW: Final = 0
_WM_QUIT: Final = 0x0012
_VK_LBUTTON, _VK_RBUTTON, _VK_MBUTTON = 0x01, 0x02, 0x04

_WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
_SetWinEventHook = fn(
    user32,
    "SetWinEventHook",
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HMODULE,
    _WINEVENTPROC,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
)
_UnhookWinEvent = fn(user32, "UnhookWinEvent", wintypes.BOOL, wintypes.HANDLE)


@dataclass(frozen=True, slots=True)
class Foreground:
    """Another program's window came to the front."""

    window: int
    at: float
    """`time.monotonic()` when the event was delivered."""
    held: bool = field(kw_only=True)
    """A mouse button was down when it was delivered."""


@dataclass(frozen=True, slots=True)
class CaptureStart:
    """A window captured the mouse, as most do while a button is pressed on them."""

    at: float


@dataclass(frozen=True, slots=True)
class SwitchStart:
    """The Alt+Tab switcher opened."""

    at: float


@dataclass(frozen=True, slots=True)
class SwitchEnd:
    """The Alt+Tab switcher closed."""

    at: float


type WinEvent = Foreground | CaptureStart | SwitchStart | SwitchEnd


def _button_held() -> bool:
    return any(GetAsyncKeyState(key) & 0x8000 for key in (_VK_LBUTTON, _VK_RBUTTON, _VK_MBUTTON))


def _event(kind: int, window: int, object_id: int) -> WinEvent | None:
    at = time.monotonic()
    if kind == _EVENT_SYSTEM_FOREGROUND:
        return Foreground(window, at, held=_button_held()) if window and object_id == _OBJID_WINDOW else None
    if kind == _EVENT_SYSTEM_CAPTURESTART:
        return CaptureStart(at)
    if kind == _EVENT_SYSTEM_SWITCHSTART:
        return SwitchStart(at)
    return SwitchEnd(at) if kind == _EVENT_SYSTEM_SWITCHEND else None


@dataclass(frozen=True, slots=True)
class WinEvents:
    """Delivers each event to `deliver` on its own thread until closed; `deliver` must only hand it on."""

    proc: object
    """The ctypes callback, kept alive while the hooks are installed."""
    _thread_id: Future[int] = field(default_factory=Future[int], init=False, repr=False)
    """The hook thread's id, once its hooks are installed."""
    """The hook thread, once it has installed the hooks."""
    _finished: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    @classmethod
    def start(cls, deliver: Callable[[WinEvent], None]) -> WinEvents:
        def callback(_hook: int, kind: int, window: int | None, object_id: int, _child: int, _thread: int, _time: int) -> None:
            if (event := _event(kind, int(window or 0), object_id)) is not None:
                deliver(event)

        events = cls(_WINEVENTPROC(callback))
        ready = threading.Event()
        threading.Thread(target=events._run, args=(ready,), name="foreground events", daemon=True).start()
        ready.wait(timeout=5)
        return events

    def _run(self, ready: threading.Event) -> None:
        try:
            self._hook(ready)
        finally:
            self._finished.set()

    def _hook(self, ready: threading.Event) -> None:
        flags = _WINEVENT_OUTOFCONTEXT | _WINEVENT_SKIPOWNPROCESS
        ranges = (
            (_EVENT_SYSTEM_FOREGROUND, _EVENT_SYSTEM_FOREGROUND),
            (_EVENT_SYSTEM_CAPTURESTART, _EVENT_SYSTEM_CAPTURESTART),
            (_EVENT_SYSTEM_SWITCHSTART, _EVENT_SYSTEM_SWITCHEND),
        )
        hooks = tuple(hook for low, high in ranges if (hook := _SetWinEventHook(low, high, None, self.proc, 0, 0, flags)))
        self._thread_id.set_result(system.thread_id())
        ready.set()
        try:
            for _ in system.messages():
                pass
        finally:
            for hook in hooks:
                _UnhookWinEvent(hook)

    def close(self) -> None:
        if self._thread_id.done() and (thread_id := self._thread_id.result()):
            system.post_thread_message(thread_id, _WM_QUIT, 0, 0)
        self._finished.wait(timeout=5)
