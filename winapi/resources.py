import ctypes
from collections.abc import Iterator
from ctypes import wintypes
from typing import Final

lazy from win32more.Windows.Win32.Foundation import FILETIME
lazy from win32more.Windows.Win32.System.SystemInformation import (
    MEMORYSTATUSEX,
    GlobalMemoryStatusEx,
)
lazy from win32more.Windows.Win32.System.Threading import GetSystemTimes

from winapi._core import fn, ntdll
from winapi.machine_status import CpuTimes, Memory, ProcessUse

_SYSTEM_PROCESS_INFORMATION: Final = 5
_STATUS_INFO_LENGTH_MISMATCH: Final = -0x3FFF_FFFC
_FIRST_GUESS: Final = 1 << 20

_NtQuerySystemInformation = fn(
    ntdll,
    "NtQuerySystemInformation",
    ctypes.c_long,
    wintypes.ULONG,
    ctypes.c_void_p,
    wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG),
)


class _ProcessEntry(ctypes.Structure):
    next: int
    private: int
    user: int
    kernel: int
    name_bytes: int
    name: int | None
    pid: int | None
    _fields_ = (
        ("next", wintypes.ULONG),
        ("threads", wintypes.ULONG),
        ("private", ctypes.c_longlong),
        ("hard_faults", wintypes.ULONG),
        ("threads_high", wintypes.ULONG),
        ("cycles", ctypes.c_ulonglong),
        ("created", ctypes.c_longlong),
        ("user", ctypes.c_longlong),
        ("kernel", ctypes.c_longlong),
        ("name_bytes", wintypes.USHORT),
        ("name_capacity", wintypes.USHORT),
        ("name", ctypes.c_void_p),
        ("priority", wintypes.LONG),
        ("pid", ctypes.c_void_p),
    )


def ticks(time: FILETIME) -> int:
    return time.dwHighDateTime << 32 | time.dwLowDateTime


def cpu_times() -> CpuTimes | None:
    idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
    if not GetSystemTimes(idle, kernel, user):
        return None
    return CpuTimes(ticks(idle), ticks(kernel), ticks(user))


def memory_use() -> Memory | None:
    status = MEMORYSTATUSEX(dwLength=ctypes.sizeof(MEMORYSTATUSEX))
    if (
        not GlobalMemoryStatusEx(status)
        or not 0 <= status.ullAvailPhys <= status.ullTotalPhys
        or not status.ullTotalPhys
    ):
        return None
    return Memory(
        int(status.ullTotalPhys - status.ullAvailPhys), int(status.ullTotalPhys)
    )


def _process_table() -> ctypes.Array[ctypes.c_char] | None:
    size = _FIRST_GUESS
    while True:
        table = ctypes.create_string_buffer(size)
        needed = wintypes.ULONG()
        status = _NtQuerySystemInformation(
            _SYSTEM_PROCESS_INFORMATION, table, size, ctypes.byref(needed)
        )
        if status == 0:
            return table
        if status != _STATUS_INFO_LENGTH_MISMATCH:
            return None
        size = needed.value + _FIRST_GUESS // 4


def _entries(table: ctypes.Array[ctypes.c_char]) -> Iterator[_ProcessEntry]:
    offset = 0
    while True:
        entry = _ProcessEntry.from_buffer(table, offset)
        yield entry
        if not entry.next:
            return
        offset += entry.next


def process_use() -> tuple[ProcessUse, ...]:
    if (table := _process_table()) is None:
        return ()
    return tuple(
        ProcessUse(
            pid,
            ctypes.wstring_at(name, entry.name_bytes // 2),
            max(0, entry.private),
            max(0, entry.user + entry.kernel),
        )
        for entry in _entries(table)
        if (pid := entry.pid) and (name := entry.name)
    )
