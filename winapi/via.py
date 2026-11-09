"""A VIA keyboard's raw HID channel: the 32-byte messages usevia.app sends, here for its RGB matrix.

QMK's VIA firmware answers each message with one report that starts with the
same command byte. Every read and write has a deadline, so an unplugged or
silent keyboard costs at most that long and never blocks its caller's thread.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Final

lazy from win32more._win32 import Guid
lazy from win32more.Windows.Win32.Devices.DeviceAndDriverInstallation import (
    CM_GET_DEVICE_INTERFACE_LIST_PRESENT,
    CR_BUFFER_SMALL,
    CM_Get_Device_Interface_List_SizeW,
    CM_Get_Device_Interface_ListW,
)
lazy from win32more.Windows.Win32.Devices.HumanInterfaceDevice import (
    HIDP_CAPS,
    HIDP_STATUS_SUCCESS,
    PHIDP_PREPARSED_DATA,
    HidD_FreePreparsedData,
    HidD_GetHidGuid,
    HidD_GetPreparsedData,
    HidP_GetCaps,
)
lazy from win32more.Windows.Win32.Foundation import ERROR_IO_PENDING, GENERIC_READ, GENERIC_WRITE, INVALID_HANDLE_VALUE
lazy from win32more.Windows.Win32.Storage.FileSystem import FILE_FLAG_OVERLAPPED, FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING, CreateFileW
lazy from win32more.Windows.Win32.System.IO import OVERLAPPED, CancelIoEx, GetOverlappedResult, GetOverlappedResultEx

from winapi._core import CloseHandle, CreateEventW, fn, kernel32, last_error

_REPORT: Final = 32
"""VIA's message size; Windows adds a leading report ID byte, always 0."""
_USAGE: Final = (0xFF60, 0x61)
"""QMK's raw HID usage page and usage."""
_DEADLINE_MS: Final = 250

_GET_VALUE, _SET_VALUE, _UNHANDLED = 0x08, 0x07, 0xFF
_RGB_MATRIX, _EFFECT = 3, 2
"""VIA's id_qmk_rgb_matrix_channel and its effect value: 0 turns the matrix off without saving."""

# A transfer that is still pending reports it through the thread's last error, which win32more's bindings don't keep.
_WriteFile = fn(kernel32, "WriteFile", wintypes.BOOL, wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, wintypes.LPDWORD, ctypes.c_void_p)
_ReadFile = fn(kernel32, "ReadFile", wintypes.BOOL, wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.LPDWORD, ctypes.c_void_p)


@dataclass(frozen=True, slots=True)
class Absent:
    """No VIA interface of that keyboard is attached, or it didn't answer in time."""


@dataclass(frozen=True, slots=True)
class Effect:
    """The RGB matrix effect VIA reports: 0 while the matrix is off."""

    value: int


def effect_message(*, read: bool, effect: int = 0) -> bytes:
    """The 32-byte message that reads, or sets without saving, the RGB matrix effect."""
    command = _GET_VALUE if read else _SET_VALUE
    return bytes((command, _RGB_MATRIX, _EFFECT, effect)).ljust(_REPORT, b"\0")


def effect_reply(sent: bytes, reply: bytes) -> Effect | Absent:
    """The effect in the keyboard's answer to `sent`; a refused or unrelated report is Absent."""
    if len(reply) < 4 or reply[0] == _UNHANDLED or reply[:3] != sent[:3]:
        return Absent()
    return Effect(reply[3])


def _paths(vendor: int, product: int) -> tuple[str, ...]:
    """HID interface paths of this keyboard, from Windows' present device list."""
    guid = Guid()
    HidD_GetHidGuid(guid)
    for _ in range(3):
        size = ctypes.c_uint32()
        if CM_Get_Device_Interface_List_SizeW(ctypes.byref(size), guid, None, CM_GET_DEVICE_INTERFACE_LIST_PRESENT) != 0:
            return ()
        buffer = ctypes.create_unicode_buffer(size.value)
        result = CM_Get_Device_Interface_ListW(guid, None, buffer, size.value, CM_GET_DEVICE_INTERFACE_LIST_PRESENT)
        if result == 0:
            identity = f"vid_{vendor:04x}&pid_{product:04x}"
            listed = ctypes.wstring_at(ctypes.addressof(buffer), size.value).split("\0")
            return tuple(path for path in listed if identity in path.lower())
        if result != CR_BUFFER_SMALL:  # a device arrived between the calls
            return ()
    return ()


def _raw_hid(handle: int) -> bool:
    data = PHIDP_PREPARSED_DATA()
    if not HidD_GetPreparsedData(handle, ctypes.byref(data)):
        return False
    try:
        caps = HIDP_CAPS()
        return HidP_GetCaps(data.value, caps) == HIDP_STATUS_SUCCESS and (caps.UsagePage, caps.Usage) == _USAGE
    finally:
        HidD_FreePreparsedData(data.value)


def _wait(handle: int, overlapped: OVERLAPPED, *, started: bool) -> int | None:
    """Bytes moved by the pending transfer, or None after cancelling it at the deadline."""
    if not started and ctypes.get_last_error() != ERROR_IO_PENDING:
        return None
    moved = ctypes.c_uint32()
    if GetOverlappedResultEx(handle, overlapped, ctypes.byref(moved), _DEADLINE_MS, False):
        return moved.value
    CancelIoEx(handle, overlapped)
    # The kernel still owns the buffer until the cancelled transfer completes.
    GetOverlappedResult(handle, overlapped, ctypes.byref(moved), True)
    return None


def _exchange(handle: int, message: bytes) -> bytes | None:
    """Send one message and return the report that answers it; None if the keyboard stays silent."""
    event = CreateEventW(None, True, False, None)
    if not event:
        raise last_error()
    try:
        sent = ctypes.create_string_buffer(b"\0" + message, 1 + _REPORT)
        overlapped = OVERLAPPED(hEvent=event)
        if _wait(handle, overlapped, started=bool(_WriteFile(handle, sent, 1 + _REPORT, None, ctypes.byref(overlapped)))) is None:
            return None
        # A report left by another reader's earlier exchange can precede ours.
        for _ in range(4):
            received = ctypes.create_string_buffer(1 + _REPORT)
            overlapped = OVERLAPPED(hEvent=event)
            moved = _wait(handle, overlapped, started=bool(_ReadFile(handle, received, 1 + _REPORT, None, ctypes.byref(overlapped))))
            if moved is None:
                return None
            reply = received.raw[1:moved]
            if reply[:1] in (message[:1], bytes((_UNHANDLED,))):
                return reply
        return None
    finally:
        CloseHandle(event)


def exchange(vendor: int, product: int, message: bytes) -> bytes | None:
    """Send `message` to the keyboard's VIA interface; None when it isn't attached or doesn't answer."""
    for path in _paths(vendor, product):
        access, share = GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE
        handle = CreateFileW(path, access, share, None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if handle in (None, ctypes.c_void_p(INVALID_HANDLE_VALUE).value):
            continue  # The keyboard and mouse collections refuse to open; only the raw interface matters.
        try:
            if _raw_hid(handle):
                return _exchange(handle, message)
        finally:
            CloseHandle(handle)
    return None
