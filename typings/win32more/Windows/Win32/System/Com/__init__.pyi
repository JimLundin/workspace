# Consumed Win32 COM calls from the pinned SDK. HRESULT is a signed integer;
# the runtime wrapper converts Guid and ComPtr inputs to their native pointers.
from win32more._win32 import ComPtr, Guid

CLSCTX_ALL: int
COINIT_MULTITHREADED: int

def CoInitializeEx(reserved: None, flags: int) -> int: ...
def CoUninitialize() -> None: ...
def CoCreateInstance(class_id: Guid, outer: ComPtr | None, context: int, interface_id: Guid, result: ComPtr) -> int: ...
