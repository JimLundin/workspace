from ctypes import _Pointer

from win32more._win32 import ComPtr
from win32more.Windows.Win32.Graphics.Direct2D import ID2D1Factory, ID2D1Geometry

class IGeometrySource2DInterop(ComPtr):
    def GetGeometry(self, value: _Pointer[ID2D1Geometry]) -> int: ...
    def TryGetGeometryUsingFactory(self, factory: ID2D1Factory, value: _Pointer[ID2D1Geometry]) -> int: ...
