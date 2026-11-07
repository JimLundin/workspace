"""Observe live Shell_NotifyIcon traffic while forwarding Explorer's shell ownership.

Windows transports NOTIFYICONDATA as a fixed 32-bit wire layout in WM_COPYDATA,
even from 64-bit senders. This small native adapter needs no injected DLL or
cached registry icons. The hidden proxy is removed before Explorer is restored.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field, replace
from enum import Enum

from winapi import desktop_shell, windows
from winapi._core import LRESULT, ULONG_PTR, fn, user32
from winapi.icon_pixels import Pixels, native_pixels
from winapi.shapes import Point, Rect
from winapi.shell import TASKBAR_CREATED, AppWindow

_SetProp = fn(user32, "SetPropW", wintypes.BOOL, wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE)
_SetWindowPos = fn(
    user32, "SetWindowPos", wintypes.BOOL, wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT
)
_SendNotifyMessage = fn(user32, "SendNotifyMessageW", wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_SendMessageTimeout = fn(
    user32,
    "SendMessageTimeoutW",
    LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ULONG_PTR),
)
_AllowSetForegroundWindow = fn(user32, "AllowSetForegroundWindow", wintypes.BOOL, wintypes.DWORD)


class CopyData(ctypes.Structure):
    kind: int
    size: int
    data: int | None
    _fields_ = (("kind", ULONG_PTR), ("size", wintypes.DWORD), ("data", ctypes.c_void_p))


@dataclass(frozen=True, slots=True)
class Registration:
    operation: int
    window: int
    identity: int
    flags: int
    callback: int
    icon: int
    tip: str
    state: int
    mask: int
    version: int
    guid: bytes


@dataclass(frozen=True, slots=True)
class Entry:
    window: int
    identity: int
    guid: bytes
    callback: int
    image: Pixels | None
    tip: str
    version: int = 0
    hidden: bool = field(default=False, kw_only=True)


class Click(Enum):
    LEFT = "left"
    RIGHT = "right"
    DOUBLE = "double"


@dataclass(frozen=True, slots=True)
class Located:
    entry: Entry
    bounds: Rect


def position_reply(data: bytes, locations: tuple[Located, ...]) -> int | None:
    """Shell_NotifyIconGetRect asks separately for the origin and extent."""
    if len(data) < 40:
        return None
    operation = int.from_bytes(data[4:8], "little")
    window, identity = (int.from_bytes(data[offset : offset + 4], "little") for offset in (16, 20))
    guid = data[24:40]
    located = next(
        (
            location
            for location in locations
            if (location.entry.guid == guid if any(guid) else (location.entry.window, location.entry.identity) == (window, identity))
        ),
        None,
    )
    if located is None or operation not in (1, 2):
        return None
    bounds = located.bounds
    x, y = (bounds.left, bounds.top) if operation == 1 else (bounds.width, bounds.height)
    return (x & 0xFFFF) | ((y & 0xFFFF) << 16)


def registration(data: bytes) -> Registration | None:
    if len(data) < 296:
        return None
    magic, operation, size, window, identity, flags, callback, icon = (
        int.from_bytes(data[offset : offset + 4], "little") for offset in range(0, 32, 4)
    )
    if magic != 0x34753423 or operation not in (0, 1, 2, 4) or size < 288 or size > len(data) - 8 or not window:
        return None
    tip = data[32:288].decode("utf-16-le", errors="replace").split("\0", 1)[0]
    state, mask = (int.from_bytes(data[offset : offset + 4], "little") for offset in (288, 292))
    version = int.from_bytes(data[808:812], "little") if len(data) >= 812 else 0
    guid = data[944:960] if flags & 0x20 and len(data) >= 960 else b""
    if flags & 0x20 and len(guid) != 16:
        return None
    return Registration(operation, window, identity, flags, callback, icon, tip, state, mask, version, guid)


def update(entries: tuple[Entry, ...], observed: Registration, image: Pixels | None) -> tuple[Entry, ...]:
    previous = next(
        (
            entry
            for entry in entries
            if (entry.guid == observed.guid if observed.guid else (entry.window, entry.identity) == (observed.window, observed.identity))
        ),
        None,
    )
    if observed.operation == 2:
        return tuple(entry for entry in entries if entry is not previous)
    if previous is None:
        if observed.operation != 0 or len(entries) >= 128:
            return entries
        previous = Entry(observed.window, observed.identity, observed.guid, 0, None, "")
        entries = (*entries, previous)
    changed = replace(
        previous,
        window=observed.window,
        identity=observed.identity,
        callback=observed.callback if observed.flags & 1 else previous.callback,
        image=image if observed.flags & 2 else previous.image,
        tip=observed.tip if observed.flags & 4 else previous.tip,
        hidden=bool(observed.state & 1) if observed.flags & 8 and observed.mask & 1 else previous.hidden,
        version=0 if observed.operation == 0 else previous.version,
    )
    if observed.operation == 4:
        changed = replace(previous, version=observed.version)
    return tuple(changed if entry is previous else entry for entry in entries)


@dataclass(frozen=True, slots=True)
class Notify:
    """One callback message's parameters, as the icon's owner expects them."""

    wparam: int
    lparam: int


def callbacks(entry: Entry, click: Click, point: Point) -> tuple[Notify, ...]:
    events = {Click.LEFT: (0x201, 0x202), Click.RIGHT: (0x204, 0x205), Click.DOUBLE: (0x203,)}[click]
    if entry.version >= 3:
        events = (*events, 0x400 if click is Click.LEFT else 0x7B) if click is not Click.DOUBLE else events
    if entry.version >= 4:
        coordinates = (point.x & 0xFFFF) | ((point.y & 0xFFFF) << 16)
        return tuple(Notify(coordinates, event | ((entry.identity & 0xFFFF) << 16)) for event in events)
    return tuple(Notify(entry.identity, event) for event in events)


class TrayHost:
    """The Qt-thread effect owner publishes immutable registrations and pixel copies."""

    __slots__ = ("closed", "created", "entries", "explorer", "locations", "window")

    def __init__(self) -> None:
        self.entries: tuple[Entry, ...] = ()
        self.locations: tuple[Located, ...] = ()
        self.closed = False
        self.explorer = next(iter(desktop_shell.taskbars()), 0)
        self.created = TASKBAR_CREATED
        self.window = AppWindow.create("workspace tray proxy", self.message, class_name="Shell_TrayWnd")
        _SetProp(self.window.handle, "workspace tray proxy", 1)
        _SetProp(self.window.handle, "TaskbandHWND", self.window.handle)
        self.poll()
        _SendNotifyMessage(0xFFFF, self.created, 0, 0)

    def poll(self) -> tuple[Entry, ...]:
        _SetWindowPos(self.window.handle, -1, 0, 0, 0, 0, 0x13)
        self.entries = tuple(entry for entry in self.entries if windows.exists(entry.window))
        return tuple(entry for entry in self.entries if not entry.hidden and entry.callback)

    def locate(self, locations: tuple[Located, ...]) -> None:
        self.locations = locations

    def message(self, hwnd: int, message: int, wparam: int, lparam: int) -> int | None:
        # Required Windows WNDPROC ABI; WM_COPYDATA pointers exist only during this callback.
        if self.closed:
            return None
        if message == 0x4A and lparam:
            copy = CopyData.from_address(lparam)
            if copy.kind == 3 and copy.data and 40 <= copy.size <= 128:
                reply = position_reply(ctypes.string_at(copy.data, copy.size), self.locations)
                if reply is not None:
                    return reply
            if copy.kind == 1 and copy.data and 296 <= copy.size <= 4096:
                observed = registration(ctypes.string_at(copy.data, copy.size))
                if observed is not None:
                    self.entries = update(
                        self.entries, observed, native_pixels(observed.icon) if observed.flags & 2 and observed.operation in (0, 1) else None
                    )
        if message == self.created:
            return 0
        if message == 0x4A or message >= 0x400:
            if not windows.exists(self.explorer):
                self.explorer = next(iter(desktop_shell.taskbars()), 0)
            if self.explorer:
                result = ULONG_PTR()
                if _SendMessageTimeout(self.explorer, message, wparam, lparam, 2, 100, ctypes.byref(result)):
                    return ctypes.c_ssize_t(result.value).value
            return 0
        return None

    def click(self, entry: Entry, click: Click, point: Point) -> None:
        # The three inputs are the registered owner, action, and native click coordinates.
        if entry in self.entries and windows.exists(entry.window):
            _AllowSetForegroundWindow(windows.process_id(entry.window))
            for notify in callbacks(entry, click, point):
                _SendNotifyMessage(entry.window, entry.callback, notify.wparam, notify.lparam)

    def close(self) -> None:
        self.closed = True
        self.window.destroy()
        self.entries = ()
        _SendNotifyMessage(0xFFFF, self.created, 0, 0)
