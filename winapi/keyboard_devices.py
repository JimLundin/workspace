"""Observe attached keyboards without installing a hook or consuming their input."""

import ctypes
from ctypes import wintypes
from typing import Final

from winapi._core import fn, last_error, user32

WM_INPUT: Final = 0x00FF
_KEYBOARD_USAGE: Final = (0x01, 0x06)  # HID generic desktop page, keyboard
_RIDEV_REMOVE, _RIDEV_INPUTSINK = 0x0001, 0x0100


class RawInputDevice(ctypes.Structure):
    handle: int
    kind: int
    _fields_ = (("handle", wintypes.HANDLE), ("kind", wintypes.DWORD))


class RawInputRegistration(ctypes.Structure):
    """RAWINPUTDEVICE."""

    _fields_ = (("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT), ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND))


_RegisterRawInputDevices = fn(user32, "RegisterRawInputDevices", wintypes.BOOL, ctypes.POINTER(RawInputRegistration), wintypes.UINT, wintypes.UINT)
_GetRawInputDeviceList = fn(
    user32, "GetRawInputDeviceList", wintypes.UINT, ctypes.POINTER(RawInputDevice), ctypes.POINTER(wintypes.UINT), wintypes.UINT
)
_GetRawInputDeviceInfo = fn(
    user32, "GetRawInputDeviceInfoW", wintypes.UINT, wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID, ctypes.POINTER(wintypes.UINT)
)


def names() -> tuple[str, ...]:
    """Publish a keyboard snapshot; Win32 owns the bounded writable ABI buffers.

    Device arrival can grow the list between calls, so retry that observation.
    A device disappearing during name lookup is absent from this snapshot.
    """
    for _ in range(3):
        count = wintypes.UINT()
        if _GetRawInputDeviceList(None, ctypes.byref(count), ctypes.sizeof(RawInputDevice)) == 0xFFFFFFFF:
            raise last_error()
        devices = (RawInputDevice * count.value)()
        received = _GetRawInputDeviceList(devices, ctypes.byref(count), ctypes.sizeof(RawInputDevice))
        if received != 0xFFFFFFFF:
            return tuple(name for device in devices[:received] if device.kind == 1 for name in (_name(device.handle),) if name)
        if ctypes.get_last_error() != 122:  # ERROR_INSUFFICIENT_BUFFER
            raise last_error()
    raise OSError("The connected keyboard list kept changing.")


def _name(handle: int) -> str:
    size = wintypes.UINT()
    if _GetRawInputDeviceInfo(handle, 0x20000007, None, ctypes.byref(size)) == 0xFFFFFFFF:  # RIDI_DEVICENAME
        return ""
    buffer = ctypes.create_unicode_buffer(size.value + 1)
    size.value += 1
    if _GetRawInputDeviceInfo(handle, 0x20000007, buffer, ctypes.byref(size)) == 0xFFFFFFFF:
        return ""
    return str(buffer.value)


def watch_input(hwnd: int) -> None:
    """Post WM_INPUT to `hwnd` for every keyboard event, even in the background.

    Raw input arrives whether or not a keyboard hook still runs. The window is
    never foreground, so each message is RIM_INPUTSINK and needs no cleanup.
    """
    if not _register(_RIDEV_INPUTSINK, hwnd):
        raise last_error()


def stop_watching_input() -> None:
    _register(_RIDEV_REMOVE, None)


def _register(flags: int, hwnd: int | None) -> bool:
    page, usage = _KEYBOARD_USAGE
    device = RawInputRegistration(page, usage, flags, hwnd)
    return bool(_RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(RawInputRegistration)))
