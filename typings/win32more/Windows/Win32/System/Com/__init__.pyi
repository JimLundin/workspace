# Consumed Win32 COM calls from the pinned SDK. HRESULT is a signed integer;
# the runtime wrapper converts Guid and ComPtr inputs to their native pointers.
import ctypes

from win32more._win32 import ComPtr, Guid

CLSCTX_ALL: int
CLSCTX_INPROC_SERVER: int
COINIT_MULTITHREADED: int
EOAC_NONE: int
RPC_C_AUTHN_LEVEL_CALL: int
RPC_C_IMP_LEVEL_IMPERSONATE: int

def CoInitializeEx(reserved: None, flags: int) -> int: ...
def CoUninitialize() -> None: ...
def CoTaskMemFree(memory: ctypes.c_void_p) -> None: ...
def CoCreateInstance(class_id: Guid, outer: ComPtr | None, context: int, interface_id: Guid, result: ComPtr) -> int: ...
def CoSetProxyBlanket(
    proxy: ComPtr, authentication: int, authorization: int, principal: None, level: int, impersonation: int, identity: None, capabilities: int
) -> int: ...
