import ctypes

from win32more._win32 import ComPtr
from win32more.Windows.Foundation import IAsyncOperation, TimeSpan

class PositionStatus:
    Disabled: int
    NotAvailable: int

class BasicGeoposition(ctypes.Structure):
    Latitude: float
    Longitude: float
    Altitude: float

class Geopoint(ComPtr):
    @property
    def Position(self) -> BasicGeoposition: ...

class Geocoordinate(ComPtr):
    @property
    def Point(self) -> Geopoint: ...

class Geoposition(ComPtr):
    @property
    def Coordinate(self) -> Geocoordinate: ...

class Geolocator(ComPtr):
    @property
    def LocationStatus(self) -> int: ...
    def GetGeopositionAsyncWithAgeAndTimeout(self, maximumAge: TimeSpan, timeout: TimeSpan) -> IAsyncOperation[Geoposition]: ...
