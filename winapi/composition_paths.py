"""Vector path interop for Windows composition; no raster capture or extra runtime."""

import ctypes
from typing import Protocol, assert_never

from win32more import FAILED, ComClass, WinError
from win32more.Windows.Graphics import IGeometrySource2D
from win32more.Windows.UI.Composition import CompositionPath
from win32more.Windows.Win32.Graphics.Direct2D import D2D1CreateFactory, ID2D1Factory, ID2D1Geometry, ID2D1GeometrySink, ID2D1PathGeometry
from win32more.Windows.Win32.Graphics.Direct2D.Common import D2D1_BEZIER_SEGMENT, D2D_POINT_2F
from win32more.Windows.Win32.System.WinRT.Graphics.Direct2D import IGeometrySource2DInterop

from winapi.contours import Contour, Curve, End, Line, Move


def check(result: object) -> None:
    match result:
        case int() as value:
            if FAILED(value):
                raise WinError(value)
        case _:
            raise TypeError("Windows returned an invalid HRESULT.")


class GeometryOutput(Protocol):
    """The native callback only writes a COM pointer to its output slot."""

    def __setitem__(self, index: int, geometry: ID2D1Geometry, /) -> None: ...


class GeometrySource(ComClass, IGeometrySource2D, IGeometrySource2DInterop):
    """Author the SDK's COM descriptors with callbacks, inside the native boundary."""
    def __init__(self, geometry: ID2D1Geometry) -> None:
        super().__init__()
        self.geometry: ID2D1Geometry = geometry

    def GetGeometry(self, value: GeometryOutput) -> int:  # noqa: N802 -- Required native callback.
        self.geometry.AddRef()
        value[0] = self.geometry
        return 0

    def TryGetGeometryUsingFactory(self, factory: ID2D1Factory, value: GeometryOutput) -> int:  # noqa: N802 -- Required native callback.
        value[0] = ID2D1Geometry()
        return 0  # Let the compositor use GetGeometry for its own factory.


def composition_path(contour: Contour, scale: float) -> CompositionPath:
    factory = ID2D1Factory(own=True)
    check(D2D1CreateFactory(0, ctypes.byref(ID2D1Factory._iid_), None, ctypes.byref(factory)))
    geometry = ID2D1PathGeometry(own=True)
    check(factory.CreatePathGeometry(geometry))
    sink = ID2D1GeometrySink(own=True)
    check(geometry.Open(sink))
    for node in contour:
        match node:
            case Move(x, y):
                sink.BeginFigure(D2D_POINT_2F(x * scale, y * scale), 0)
            case Line(x, y):
                sink.AddLine(D2D_POINT_2F(x * scale, y * scale))
            case Curve(ax, ay, bx, by, x, y):
                sink.AddBezier(D2D1_BEZIER_SEGMENT(D2D_POINT_2F(ax * scale, ay * scale),
                                                 D2D_POINT_2F(bx * scale, by * scale), D2D_POINT_2F(x * scale, y * scale)))
            case End.CLOSE:
                sink.EndFigure(1)
            case _:
                assert_never(node)
    check(sink.Close())
    return CompositionPath(GeometrySource(geometry.as_(ID2D1Geometry)).as_(IGeometrySource2D))
