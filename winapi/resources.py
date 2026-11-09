"""Processor time and memory load, read without side effects."""

import ctypes

lazy from win32more.Windows.Win32.Foundation import FILETIME
lazy from win32more.Windows.Win32.System.SystemInformation import MEMORYSTATUSEX, GlobalMemoryStatusEx
lazy from win32more.Windows.Win32.System.Threading import GetSystemTimes

from winapi.machine_status import CpuTimes


def ticks(time: FILETIME) -> int:
    return time.dwHighDateTime << 32 | time.dwLowDateTime


def cpu_times() -> CpuTimes | None:
    """Cumulative idle, kernel and user time; compare two samples with `machine_status.cpu_load`."""
    idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
    if not GetSystemTimes(idle, kernel, user):
        return None
    return CpuTimes(ticks(idle), ticks(kernel), ticks(user))


def memory_load() -> int | None:
    """The percent of physical memory in use, as Windows reports it, or None when it can't be read.

    Windows rejects the call unless `dwLength` is the structure's size."""
    status = MEMORYSTATUSEX(dwLength=ctypes.sizeof(MEMORYSTATUSEX))
    if not GlobalMemoryStatusEx(status) or not 0 <= status.dwMemoryLoad <= 100:
        return None
    return int(status.dwMemoryLoad)
