# Consumed power observations. Structures pass by reference; BOOL results are ints and NTSTATUS is signed.
import ctypes

from win32more._win32 import ByReference

SystemExecutionState: int
ES_DISPLAY_REQUIRED: int

class SYSTEM_POWER_STATUS(ctypes.Structure):
    ACLineStatus: int
    BatteryFlag: int
    BatteryLifePercent: int

def GetSystemPowerStatus(status: SYSTEM_POWER_STATUS) -> int: ...
def CallNtPowerInformation(level: int, input: None, input_length: int, output: ByReference[ctypes.c_ulong], output_length: int) -> int: ...
