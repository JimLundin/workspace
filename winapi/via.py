"""A VIA keyboard's raw HID channel: the 32-byte messages usevia.app sends, here for its RGB matrix.

QMK's VIA firmware answers each message with one report that starts with the
same command byte. Every read and write has a deadline, so an unplugged or
silent keyboard costs at most that long and never blocks its caller's thread.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Final

from winapi._core import GUID, ULONG_PTR, CloseHandle, CreateEventW, fn, kernel32, last_error

_cfgmgr32 = ctypes.WinDLL("cfgmgr32", use_last_error=True)
_hid = ctypes.WinDLL("hid", use_last_error=True)

_REPORT: Final = 32
"""VIA's message size; Windows adds a leading report ID byte, always 0."""
_USAGE: Final = (0xFF60, 0x61)
"""QMK's raw HID usage page and usage."""
_DEADLINE_MS: Final = 250

_GET_VALUE, _SET_VALUE, _UNHANDLED = 0x08, 0x07, 0xFF
_RGB_MATRIX, _EFFECT = 3, 2
"""VIA's id_qmk_rgb_matrix_channel and its effect value: 0 turns the matrix off without saving."""


class Overlapped(ctypes.Structure):
    _fields_ = (
        ("Internal", ULONG_PTR),
        ("InternalHigh", ULONG_PTR),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    )


class HidCaps(ctypes.Structure):
    """HIDP_CAPS."""

    Usage: int
    UsagePage: int
    _fields_ = (
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("Counts", wintypes.USHORT * 10),
    )


_HidD_GetHidGuid = fn(_hid, "HidD_GetHidGuid", None, ctypes.POINTER(GUID))
_HidD_GetPreparsedData = fn(_hid, "HidD_GetPreparsedData", wintypes.BOOLEAN, wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p))
_HidD_FreePreparsedData = fn(_hid, "HidD_FreePreparsedData", wintypes.BOOLEAN, ctypes.c_void_p)
_HidP_GetCaps = fn(_hid, "HidP_GetCaps", wintypes.LONG, ctypes.c_void_p, ctypes.POINTER(HidCaps))
_CM_Get_Device_Interface_List_SizeW = fn(
    _cfgmgr32,
    "CM_Get_Device_Interface_List_SizeW",
    wintypes.DWORD,
    ctypes.POINTER(wintypes.ULONG),
    ctypes.POINTER(GUID),
    wintypes.LPCWSTR,
    wintypes.ULONG,
)
_CM_Get_Device_Interface_ListW = fn(
    _cfgmgr32,
    "CM_Get_Device_Interface_ListW",
    wintypes.DWORD,
    ctypes.POINTER(GUID),
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    wintypes.ULONG,
    wintypes.ULONG,
)
_CreateFileW = fn(
    kernel32,
    "CreateFileW",
    wintypes.HANDLE,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
)
_WriteFile = fn(kernel32, "WriteFile", wintypes.BOOL, wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, wintypes.LPDWORD, ctypes.POINTER(Overlapped))
_ReadFile = fn(kernel32, "ReadFile", wintypes.BOOL, wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.LPDWORD, ctypes.POINTER(Overlapped))
_GetOverlappedResultEx = fn(
    kernel32, "GetOverlappedResultEx", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(Overlapped), wintypes.LPDWORD, wintypes.DWORD, wintypes.BOOL
)
_GetOverlappedResult = fn(
    kernel32, "GetOverlappedResult", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(Overlapped), wintypes.LPDWORD, wintypes.BOOL
)
_CancelIoEx = fn(kernel32, "CancelIoEx", wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(Overlapped))

_GENERIC_READ_WRITE: Final = 0x8000_0000 | 0x4000_0000
_SHARE_READ_WRITE: Final = 0x1 | 0x2
_OPEN_EXISTING, _FILE_FLAG_OVERLAPPED = 3, 0x4000_0000
_INVALID_HANDLE: Final = ctypes.c_void_p(-1).value
_ERROR_IO_PENDING: Final = 997
_HIDP_STATUS_SUCCESS: Final = 0x0011_0000


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
    guid = GUID()
    _HidD_GetHidGuid(ctypes.byref(guid))
    for _ in range(3):
        size = wintypes.ULONG()
        if _CM_Get_Device_Interface_List_SizeW(ctypes.byref(size), ctypes.byref(guid), None, 0) != 0:
            return ()
        buffer = ctypes.create_unicode_buffer(size.value)
        result = _CM_Get_Device_Interface_ListW(ctypes.byref(guid), None, buffer, size.value, 0)
        if result == 0:
            identity = f"vid_{vendor:04x}&pid_{product:04x}"
            listed = ctypes.wstring_at(ctypes.addressof(buffer), size.value).split("\0")
            return tuple(path for path in listed if identity in path.lower())
        if result != 0x1A:  # CR_BUFFER_SMALL: a device arrived between the calls
            return ()
    return ()


def _raw_hid(handle: int) -> bool:
    data = ctypes.c_void_p()
    if not _HidD_GetPreparsedData(handle, ctypes.byref(data)):
        return False
    try:
        caps = HidCaps()
        return _HidP_GetCaps(data, ctypes.byref(caps)) == _HIDP_STATUS_SUCCESS and (caps.UsagePage, caps.Usage) == _USAGE
    finally:
        _HidD_FreePreparsedData(data)


def _wait(handle: int, overlapped: Overlapped, *, started: bool) -> int | None:
    """Bytes moved by the pending transfer, or None after cancelling it at the deadline."""
    if not started and ctypes.get_last_error() != _ERROR_IO_PENDING:
        return None
    moved = wintypes.DWORD()
    if _GetOverlappedResultEx(handle, ctypes.byref(overlapped), ctypes.byref(moved), _DEADLINE_MS, False):
        return moved.value
    _CancelIoEx(handle, ctypes.byref(overlapped))
    # The kernel still owns the buffer until the cancelled transfer completes.
    _GetOverlappedResult(handle, ctypes.byref(overlapped), ctypes.byref(moved), True)
    return None


def _exchange(handle: int, message: bytes) -> bytes | None:
    """Send one message and return the report that answers it; None if the keyboard stays silent."""
    event = CreateEventW(None, True, False, None)
    if not event:
        raise last_error()
    try:
        sent = ctypes.create_string_buffer(b"\0" + message, 1 + _REPORT)
        overlapped = Overlapped(hEvent=event)
        if _wait(handle, overlapped, started=bool(_WriteFile(handle, sent, 1 + _REPORT, None, ctypes.byref(overlapped)))) is None:
            return None
        # A report left by another reader's earlier exchange can precede ours.
        for _ in range(4):
            received = ctypes.create_string_buffer(1 + _REPORT)
            overlapped = Overlapped(hEvent=event)
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
        handle = _CreateFileW(path, _GENERIC_READ_WRITE, _SHARE_READ_WRITE, None, _OPEN_EXISTING, _FILE_FLAG_OVERLAPPED, None)
        if handle in (None, _INVALID_HANDLE):
            continue  # The keyboard and mouse collections refuse to open; only the raw interface matters.
        try:
            if _raw_hid(handle):
                return _exchange(handle, message)
        finally:
            CloseHandle(handle)
    return None
