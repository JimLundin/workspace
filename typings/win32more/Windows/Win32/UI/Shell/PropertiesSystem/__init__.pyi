# Consumed window property store reads; generated COM methods return integer HRESULTs.
from win32more._win32 import ComPtr, Guid
from win32more.Windows.Win32.Foundation import PROPERTYKEY
from win32more.Windows.Win32.System.Com.StructuredStorage import PROPVARIANT

class IPropertyStore(ComPtr):
    def GetValue(self, key: PROPERTYKEY, value: PROPVARIANT) -> int: ...

def SHGetPropertyStoreForWindow(hwnd: int, interface_id: Guid, result: ComPtr) -> int: ...
