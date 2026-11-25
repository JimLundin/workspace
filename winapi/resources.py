import ctypes

lazy from win32more.Windows.Win32.Foundation import FILETIME
lazy from win32more.Windows.Win32.System.SystemInformation import (
    MEMORYSTATUSEX,
    GlobalMemoryStatusEx,
)
lazy from win32more.Windows.Win32.System.Threading import GetSystemTimes

from winapi.machine_status import CpuTimes, Memory


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
