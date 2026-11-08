"""Observe live Shell_NotifyIcon traffic while forwarding Explorer's shell ownership.

Windows transports NOTIFYICONDATA as a fixed 32-bit wire layout in WM_COPYDATA,
even from 64-bit senders. This small native adapter needs no injected DLL or
cached registry icons. The hidden proxy is removed before Explorer is restored.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Final

from cell import Cell
from winapi import desktop_shell, windows
from winapi._core import ULONG_PTR, AllowSetForegroundWindow, SendMessageTimeoutW, SetWindowPos, fn, user32
from winapi.icon_pixels import Pixels, native_pixels
from winapi.shapes import Point, Rect
from winapi.shell import TASKBAR_CREATED, AppWindow

_SetProp = fn(user32, "SetPropW", wintypes.BOOL, wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE)
_SendNotifyMessage = fn(user32, "SendNotifyMessageW", wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


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


@dataclass(frozen=True, slots=True)
class Messages:
    """The mouse messages a click sends a tray icon, then the select or context message a version 3 icon also gets."""

    mouse: tuple[int, ...]
    selected: tuple[int, ...]


_MESSAGES: Final = frozendict(
    {Click.LEFT: Messages((0x201, 0x202), (0x400,)), Click.RIGHT: Messages((0x204, 0x205), (0x7B,)), Click.DOUBLE: Messages((0x203,), ())}
)


def callbacks(entry: Entry, click: Click, point: Point) -> tuple[Notify, ...]:
    messages = _MESSAGES[click]
    events = (*messages.mouse, *messages.selected) if entry.version >= 3 else messages.mouse
    if entry.version >= 4:
        coordinates = (point.x & 0xFFFF) | ((point.y & 0xFFFF) << 16)
        return tuple(Notify(coordinates, event | ((entry.identity & 0xFFFF) << 16)) for event in events)
    return tuple(Notify(entry.identity, event) for event in events)


@dataclass(frozen=True, slots=True)
class _Hosted:
    entries: tuple[Entry, ...] = ()
    locations: tuple[Located, ...] = ()
    explorer: int = 0
    """Explorer's taskbar, which receives every message the proxy does not answer itself."""
    closed: bool = False


def _proxied(hosted: Cell[_Hosted], message: int, wparam: int, lparam: int) -> int | None:
    """The proxy window's procedure: answer icon positions and registrations, forward the rest to Explorer."""
    # Required Windows WNDPROC ABI; WM_COPYDATA pointers exist only during this callback.
    if hosted.get().closed:
        return None
    if message == 0x4A and lparam:
        copy = CopyData.from_address(lparam)
        if copy.kind == 3 and copy.data and 40 <= copy.size <= 128:
            reply = position_reply(ctypes.string_at(copy.data, copy.size), hosted.get().locations)
            if reply is not None:
                return reply
        if copy.kind == 1 and copy.data and 296 <= copy.size <= 4096:
            observed = registration(ctypes.string_at(copy.data, copy.size))
            if observed is not None:
                pixels = native_pixels(observed.icon) if observed.flags & 2 and observed.operation in (0, 1) else None
                hosted.update(lambda current: replace(current, entries=update(current.entries, observed, pixels)))
    if message == TASKBAR_CREATED:
        return 0
    if message == 0x4A or message >= 0x400:
        if not windows.exists(hosted.get().explorer):
            explorer = next(iter(desktop_shell.taskbars()), 0)
            hosted.update(lambda current: replace(current, explorer=explorer))
        if explorer := hosted.get().explorer:
            result = ULONG_PTR()
            if SendMessageTimeoutW(explorer, message, wparam, lparam, 2, 100, ctypes.byref(result)):
                return ctypes.c_ssize_t(result.value).value
        return 0
    return None


@dataclass(frozen=True, slots=True)
class TrayHost:
    """The Qt-thread effect owner publishes immutable registrations and pixel copies."""

    window: AppWindow
    _hosted: Cell[_Hosted]

    @classmethod
    def start(cls) -> TrayHost:
        hosted = Cell(_Hosted(explorer=next(iter(desktop_shell.taskbars()), 0)))

        def message(_hwnd: int, message: int, wparam: int, lparam: int) -> int | None:
            return _proxied(hosted, message, wparam, lparam)

        window = AppWindow.create("workspace tray proxy", message, class_name="Shell_TrayWnd")
        host = cls(window, hosted)
        _SetProp(window.handle, "workspace tray proxy", 1)
        _SetProp(window.handle, "TaskbandHWND", window.handle)
        host.poll()
        _SendNotifyMessage(0xFFFF, TASKBAR_CREATED, 0, 0)
        return host

    @property
    def entries(self) -> tuple[Entry, ...]:
        return self._hosted.get().entries

    def poll(self) -> tuple[Entry, ...]:
        SetWindowPos(self.window.handle, -1, 0, 0, 0, 0, 0x13)
        hosted = self._hosted.update(
            lambda current: replace(current, entries=tuple(entry for entry in current.entries if windows.exists(entry.window)))
        )
        return tuple(entry for entry in hosted.entries if not entry.hidden and entry.callback)

    def locate(self, locations: tuple[Located, ...]) -> None:
        self._hosted.update(lambda current: replace(current, locations=locations))

    def click(self, entry: Entry, click: Click, point: Point) -> None:
        # The three inputs are the registered owner, action, and native click coordinates.
        if entry in self.entries and windows.exists(entry.window):
            AllowSetForegroundWindow(windows.process_id(entry.window))
            for notify in callbacks(entry, click, point):
                _SendNotifyMessage(entry.window, entry.callback, notify.wparam, notify.lparam)

    def close(self) -> None:
        self._hosted.update(lambda current: replace(current, closed=True))
        self.window.destroy()
        self._hosted.update(lambda current: replace(current, entries=()))
        _SendNotifyMessage(0xFFFF, TASKBAR_CREATED, 0, 0)
