import ctypes

from win32more._win32 import ByReference
from win32more.Windows.Win32.System.Com import SAFEARRAY

CF_UNICODETEXT: int

# Each reports a signed HRESULT.
def SafeArrayGetUBound(
    array: ctypes._Pointer[SAFEARRAY],
    dimension: int,
    upper: ByReference[ctypes.c_int32],
) -> int: ...
def SafeArrayAccessData(
    array: ctypes._Pointer[SAFEARRAY], data: ByReference[ctypes.c_void_p]
) -> int: ...
def SafeArrayUnaccessData(array: ctypes._Pointer[SAFEARRAY]) -> int: ...
def SafeArrayDestroy(array: ctypes._Pointer[SAFEARRAY]) -> int: ...
