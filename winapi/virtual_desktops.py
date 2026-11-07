"""Windows' virtual desktops, the ones Task View shows: list, create and switch them,
and read or move any program's window between them.

Reading a window's desktop uses the documented IVirtualDesktopManager. Moving
another process's window, creating and switching desktops need the shell's
undocumented IVirtualDesktopManagerInternal and IApplicationViewCollection. Their
interface IDs and method order here are Windows 11 24H2's (build 26100), as pyvda
0.6.0 records them; another build that changed them fails to connect rather than
calling the wrong method. The calling thread must already be in a COM apartment,
and an Explorer restart disconnects the interfaces: connect again after an error.
"""

import ctypes
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from typing import Final

from winapi._core import NativeFunction, fn, user32

_ole32 = ctypes.WinDLL("ole32", use_last_error=True)
_CoCreateInstance = fn(_ole32, "CoCreateInstance", ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p)
_AllowSetForegroundWindow = fn(user32, "AllowSetForegroundWindow", wintypes.BOOL, wintypes.DWORD)

type GuidBuffer = ctypes.Array[ctypes.c_char]


def _guid(value: str) -> GuidBuffer:
    return ctypes.create_string_buffer(uuid.UUID(value).bytes_le, 16)


_CLSCTX_INPROC_SERVER, _CLSCTX_LOCAL_SERVER = 0x1, 0x4
_ASFW_ANY: Final = 0xFFFF_FFFF
_IMMERSIVE_SHELL = _guid("C2F03A33-21F5-47FA-B4BB-156362A2F239")
_IID_SERVICE_PROVIDER = _guid("6D5140C1-7436-11CE-8034-00AA006009FA")
_DESKTOP_MANAGER = _guid("AA509086-5CA9-4C25-8F95-589D3C07B48A")
_IID_DESKTOP_MANAGER = _guid("A5CD92FF-29BE-454C-8D04-D82879FB3F1B")
_SERVICE_DESKTOP_MANAGER_INTERNAL = _guid("C5E0CDCA-7B6E-41B2-9FC4-D93975CC467B")
_IID_DESKTOP_MANAGER_INTERNAL = _guid("53F5CA0B-158F-4124-900C-057158060B27")
_IID_VIEW_COLLECTION = _guid("1841C6D7-4F9D-42C0-AF41-8747538F10E5")
_IID_DESKTOP = _guid("3F07F4BE-B107-441A-AF0F-39D82529072C")

# Method slots, after IUnknown's QueryInterface, AddRef and Release.
_RELEASE = 2
_QUERY_SERVICE = 3
_ARRAY_COUNT, _ARRAY_AT = 3, 4
_WINDOW_DESKTOP_ID = 4
_VIEW_FOR_WINDOW = 6
_DESKTOP_ID = 4
_MOVE_VIEW, _CURRENT, _DESKTOPS, _SWITCH, _CREATE, _FIND = 4, 6, 7, 9, 11, 14


def _method(pointer: ctypes.c_void_p, index: int, *arguments: type[object]) -> NativeFunction[int]:
    """The method at `index` in a COM object's table: the object's first pointer is its table."""
    table = ctypes.c_void_p.from_address(pointer.value).value if pointer.value else None
    address = ctypes.c_void_p.from_address(table + index * ctypes.sizeof(ctypes.c_void_p)).value if table else None
    if address is None:
        raise OSError("A virtual desktop interface has no method table.")
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *arguments)(address)


def _check(result: int, action: str) -> None:
    if result < 0:
        raise OSError(f"Windows could not {action} (0x{result & 0xFFFF_FFFF:08X}).")


def _release(pointer: ctypes.c_void_p) -> None:
    if pointer.value:
        _method(pointer, _RELEASE)(pointer)
        pointer.value = None


def _desktop_id(desktop: ctypes.c_void_p) -> uuid.UUID:
    value = ctypes.create_string_buffer(16)
    _check(_method(desktop, _DESKTOP_ID, ctypes.c_void_p)(desktop, value), "read a desktop's ID")
    return uuid.UUID(bytes_le=value.raw)


@dataclass(frozen=True, slots=True)
class Desktops:
    """The desktops in Task View's order, and the one on screen."""

    ids: tuple[uuid.UUID, ...]
    current: uuid.UUID


@dataclass(frozen=True, slots=True)
class VirtualDesktops:
    """The shell's desktop interfaces, owned by the thread that connected them."""

    manager: ctypes.c_void_p
    internal: ctypes.c_void_p
    views: ctypes.c_void_p

    @classmethod
    def connect(cls) -> VirtualDesktops:
        desktops = cls(ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p())
        shell = ctypes.c_void_p()
        try:
            context = _CLSCTX_INPROC_SERVER | _CLSCTX_LOCAL_SERVER
            _check(
                _CoCreateInstance(_DESKTOP_MANAGER, None, context, _IID_DESKTOP_MANAGER, ctypes.byref(desktops.manager)), "open the desktop manager"
            )
            _check(_CoCreateInstance(_IMMERSIVE_SHELL, None, _CLSCTX_LOCAL_SERVER, _IID_SERVICE_PROVIDER, ctypes.byref(shell)), "reach the shell")
            query = _method(shell, _QUERY_SERVICE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
            _check(query(shell, _SERVICE_DESKTOP_MANAGER_INTERNAL, _IID_DESKTOP_MANAGER_INTERNAL, ctypes.byref(desktops.internal)), "manage desktops")
            _check(query(shell, _IID_VIEW_COLLECTION, _IID_VIEW_COLLECTION, ctypes.byref(desktops.views)), "read application views")
        except OSError:
            desktops.close()
            raise
        finally:
            _release(shell)
        return desktops

    def close(self) -> None:
        for pointer in (self.views, self.internal, self.manager):
            _release(pointer)

    def observe(self) -> Desktops:
        current = ctypes.c_void_p()
        _check(_method(self.internal, _CURRENT, ctypes.c_void_p)(self.internal, ctypes.byref(current)), "read the current desktop")
        try:
            on_screen = _desktop_id(current)
        finally:
            _release(current)
        return Desktops(self.ids(), on_screen)

    def ids(self) -> tuple[uuid.UUID, ...]:
        array = ctypes.c_void_p()
        _check(_method(self.internal, _DESKTOPS, ctypes.c_void_p)(self.internal, ctypes.byref(array)), "list desktops")
        try:
            count = ctypes.c_uint32()
            _check(_method(array, _ARRAY_COUNT, ctypes.c_void_p)(array, ctypes.byref(count)), "count desktops")
            return tuple(self._at(array, index) for index in range(count.value))
        finally:
            _release(array)

    def _at(self, array: ctypes.c_void_p, index: int) -> uuid.UUID:
        desktop = ctypes.c_void_p()
        _check(
            _method(array, _ARRAY_AT, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p)(array, index, _IID_DESKTOP, ctypes.byref(desktop)),
            "read a desktop",
        )
        try:
            return _desktop_id(desktop)
        finally:
            _release(desktop)

    def create(self) -> uuid.UUID:
        """A new desktop after the existing ones."""
        desktop = ctypes.c_void_p()
        _check(_method(self.internal, _CREATE, ctypes.c_void_p)(self.internal, ctypes.byref(desktop)), "create a desktop")
        try:
            return _desktop_id(desktop)
        finally:
            _release(desktop)

    def window_desktop(self, hwnd: int) -> uuid.UUID | None:
        """The desktop a top-level window is on; None for windows on none, such as the shell's hidden hosts."""
        value = ctypes.create_string_buffer(16)
        if _method(self.manager, _WINDOW_DESKTOP_ID, wintypes.HWND, ctypes.c_void_p)(self.manager, hwnd, value) < 0:
            return None
        found = uuid.UUID(bytes_le=value.raw)
        return None if found.int == 0 else found

    def move(self, hwnd: int, desktop: uuid.UUID) -> None:
        """Move any program's window to `desktop`, without switching to it."""
        view, target = ctypes.c_void_p(), ctypes.c_void_p()
        try:
            _check(
                _method(self.views, _VIEW_FOR_WINDOW, wintypes.HWND, ctypes.c_void_p)(self.views, hwnd, ctypes.byref(view)), "find the window's view"
            )
            self._find(desktop, target)
            _check(_method(self.internal, _MOVE_VIEW, ctypes.c_void_p, ctypes.c_void_p)(self.internal, view, target), "move the window")
        finally:
            _release(target)
            _release(view)

    def switch(self, desktop: uuid.UUID) -> None:
        """Show `desktop`; the window activated next takes the keyboard."""
        target = ctypes.c_void_p()
        try:
            self._find(desktop, target)
            _AllowSetForegroundWindow(_ASFW_ANY)
            _check(_method(self.internal, _SWITCH, ctypes.c_void_p)(self.internal, target), "switch desktops")
        finally:
            _release(target)

    def _find(self, desktop: uuid.UUID, into: ctypes.c_void_p) -> None:
        wanted = ctypes.create_string_buffer(desktop.bytes_le, 16)
        _check(_method(self.internal, _FIND, ctypes.c_void_p, ctypes.c_void_p)(self.internal, wanted, ctypes.byref(into)), "find the desktop")
