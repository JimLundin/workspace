# Consumed device-interface listing. Results are CONFIGRET codes, 0 on success.
import ctypes

from win32more._win32 import ByReference, Guid

CM_GET_DEVICE_INTERFACE_LIST_PRESENT: int
CR_BUFFER_SMALL: int

def CM_Get_Device_Interface_List_SizeW(size: ByReference[ctypes.c_uint32], interface: Guid, device: None, flags: int) -> int: ...
def CM_Get_Device_Interface_ListW(interface: Guid, device: None, buffer: ctypes.Array[ctypes.c_wchar], length: int, flags: int) -> int: ...
