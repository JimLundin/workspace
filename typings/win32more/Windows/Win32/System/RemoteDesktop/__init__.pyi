# Consumed session query. The SDK types the returned buffer as a string pointer; Workspace reads it as the
# WTSINFOEXW the session-information class names, then frees it. BOOL results are ints.
import ctypes
from typing import type_check_only

from win32more._win32 import ByReference

NOTIFY_FOR_THIS_SESSION: int
WTS_CURRENT_SESSION: int
WTSSessionInfoEx: int

@type_check_only
class _Level1(ctypes.Structure):
    SessionFlags: int

@type_check_only
class _Level(ctypes.Union):
    WTSInfoExLevel1: _Level1

class WTSINFOEXW(ctypes.Structure):
    Level: int
    Data: _Level

def WTSQuerySessionInformationW(
    server: None, session: int, info_class: int, buffer: ByReference[ctypes.c_wchar_p], size: ByReference[ctypes.c_ulong]
) -> int: ...
def WTSFreeMemory(memory: ctypes.c_wchar_p) -> None: ...
