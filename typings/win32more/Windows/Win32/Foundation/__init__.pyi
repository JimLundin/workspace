import ctypes

def GetLastError() -> int: ...
def CloseHandle(handle: int) -> int: ...
def DuplicateHandle(
    source_process: int, source: int, target_process: int, target: ctypes.c_void_p, access: int, inherit: int, options: int
) -> int: ...

class PROPERTYKEY(ctypes.Structure): ...

class FILETIME(ctypes.Structure):
    dwLowDateTime: int
    dwHighDateTime: int

def GlobalFree(memory: int) -> int | None: ...

ERROR_INSUFFICIENT_BUFFER: int
ERROR_IO_PENDING: int
GENERIC_READ: int
GENERIC_WRITE: int
INVALID_HANDLE_VALUE: int

class RECT(ctypes.Structure):
    left: int
    top: int
    right: int
    bottom: int
