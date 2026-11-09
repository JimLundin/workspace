# Consumed HID capability reads. Preparsed data is an opaque pointer-sized integer;
# BOOLEAN results are ints and HidP_GetCaps returns an NTSTATUS.
import ctypes

from win32more._win32 import ByReference, Guid

HIDP_STATUS_SUCCESS: int

class PHIDP_PREPARSED_DATA(ctypes.c_ssize_t): ...

class HIDP_CAPS(ctypes.Structure):
    Usage: int
    UsagePage: int

def HidD_GetHidGuid(guid: Guid) -> None: ...
def HidD_GetPreparsedData(device: int, data: ByReference[PHIDP_PREPARSED_DATA]) -> int: ...
def HidD_FreePreparsedData(data: int) -> int: ...
def HidP_GetCaps(data: int, capabilities: HIDP_CAPS) -> int: ...
