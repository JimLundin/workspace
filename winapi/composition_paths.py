"""Vector path interop for Windows composition; no raster capture or extra runtime."""
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false

import ctypes
from typing import Any, assert_never

from win32more import FAILED, ComClass, WinError
from win32more.Windows.Graphics import IGeometrySource2D
from win32more.Windows.UI.Composition import CompositionPath
from win32more.Windows.Win32.Graphics.Direct2D import D2D1CreateFactory, ID2D1Factory, ID2D1Geometry, ID2D1GeometrySink, ID2D1PathGeometry
from win32more.Windows.Win32.Graphics.Direct2D.Common import D2D1_BEZIER_SEGMENT, D2D_POINT_2F
from win32more.Windows.Win32.System.WinRT.Graphics.Direct2D import IGeometrySource2DInterop

from .contours import Contour, Curve, End, Line, Move


def check(result: object) -> None:
    if not isinstance(result, int):
        raise TypeError("Windows returned an invalid HRESULT.")
    if FAILED(result):
        raise WinError(result)


class GeometrySource(ComClass, IGeometrySource2D, IGeometrySource2DInterop):  # type: ignore[misc, no-any-unimported]  # pyright: ignore[reportIncompatibleVariableOverride]
    """Author the SDK's COM descriptors with callbacks, inside the native boundary."""
    def __init__(self, geometry: object) -> None:
        super().__init__()
        self.geometry: Any = geometry

    def GetGeometry(self, value: object) -> int:  # noqa: N802  # pyright: ignore[reportIncompatibleVariableOverride]
        destination: Any = value
        self.geometry.AddRef()
        destination[0] = self.geometry
        return 0

    def TryGetGeometryUsingFactory(self, factory: object, value: object) -> int:  # noqa: N802  # pyright: ignore[reportIncompatibleVariableOverride]
        destination: Any = value
        destination[0] = ID2D1Geometry()
        return 0  # Let the compositor use GetGeometry for its own factory.


def composition_path(contour: Contour, scale: float) -> object:
    factory: Any = ID2D1Factory(own=True)
    check(D2D1CreateFactory(0, ctypes.byref(ID2D1Factory._iid_), None, ctypes.byref(factory)))  # pyright: ignore[reportPrivateUsage]
    geometry: Any = ID2D1PathGeometry(own=True)
    check(factory.CreatePathGeometry(geometry))
    sink: Any = ID2D1GeometrySink(own=True)
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
    return CompositionPath(GeometrySource(geometry).as_(IGeometrySource2D))
