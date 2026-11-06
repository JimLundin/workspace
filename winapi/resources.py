"""Processor time and memory load, read without side effects."""

import ctypes
from ctypes import wintypes

from winapi._core import fn, kernel32
from winapi.machine_status import CpuTimes


class MemoryStatus(ctypes.Structure):
    """MEMORYSTATUSEX; Windows rejects the call unless `length` is the structure's size."""

    length: int
    load: int
    total: int
    available: int
    _fields_ = (
        ("length", wintypes.DWORD),
        ("load", wintypes.DWORD),
        ("total", ctypes.c_ulonglong),
        ("available", ctypes.c_ulonglong),
        ("total_page_file", ctypes.c_ulonglong),
        ("available_page_file", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong),
        ("available_virtual", ctypes.c_ulonglong),
        ("available_extended_virtual", ctypes.c_ulonglong),
    )


_GetSystemTimes = fn(
    kernel32,
    "GetSystemTimes",
    wintypes.BOOL,
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
)
_GlobalMemoryStatusEx = fn(kernel32, "GlobalMemoryStatusEx", wintypes.BOOL, ctypes.POINTER(MemoryStatus))


def ticks(time: wintypes.FILETIME) -> int:
    return time.dwHighDateTime << 32 | time.dwLowDateTime


def cpu_times() -> CpuTimes | None:
    """Cumulative idle, kernel and user time; compare two samples with `machine_status.cpu_load`."""
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    if not _GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None
    return CpuTimes(ticks(idle), ticks(kernel), ticks(user))


def memory_load() -> int | None:
    """The percent of physical memory in use, as Windows reports it, or None when it can't be read."""
    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    if not _GlobalMemoryStatusEx(ctypes.byref(status)) or not 0 <= status.load <= 100:
        return None
    return int(status.load)
