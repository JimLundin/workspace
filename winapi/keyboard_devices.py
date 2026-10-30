"""Observe attached keyboards without installing a hook or consuming their input."""

import ctypes
from ctypes import wintypes

from winapi._core import fn, last_error, user32


class RawInputDevice(ctypes.Structure):
    handle: int
    kind: int
    _fields_ = (("handle", wintypes.HANDLE), ("kind", wintypes.DWORD))


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
