from win32more._win32 import ComPtr
from win32more.Windows.Foundation.Numerics import Vector2, Vector3
from win32more.Windows.Graphics import IGeometrySource2D
from win32more.Windows.UI import Color

class CompositionPath(ComPtr):
    def __init__(self, source: IGeometrySource2D) -> None: ...

class CompositionPathGeometry(ComPtr):
    Path: CompositionPath

class CompositionRoundedRectangleGeometry(ComPtr):
    Offset: Vector2
    Size: Vector2
    CornerRadius: Vector2

class ICompositionPathGeometry(ComPtr):
    Path: CompositionPath

class ICompositionRoundedRectangleGeometry(ComPtr):
    Offset: Vector2
    Size: Vector2
    CornerRadius: Vector2

class IVisual(ComPtr):
    Size: Vector2
    Offset: Vector3
    Opacity: float

class CompositionClip(ComPtr): ...
class CompositionGeometricClip(ComPtr):
    Geometry: CompositionPathGeometry | CompositionRoundedRectangleGeometry
class CompositionBackdropBrush(ComPtr): ...
class CompositionSurfaceBrush(ComPtr): ...

class CompositionColorBrush(ComPtr):
    Color: Color

class CompositionSpriteShape(ComPtr):
    Geometry: CompositionPathGeometry | CompositionRoundedRectangleGeometry
    FillBrush: CompositionColorBrush

class CompositionShapeCollection(ComPtr):
    def Append(self, shape: CompositionSpriteShape) -> None: ...

class VisualCollection(ComPtr):
    def InsertAtTop(self, visual: ContainerVisual | SpriteVisual | ShapeVisual) -> None: ...

class ContainerVisual(ComPtr):
    Size: Vector2
    Offset: Vector3
    Opacity: float
    @property
    def Clip(self) -> CompositionClip: ...
    @Clip.setter
    def Clip(self, value: CompositionGeometricClip) -> None: ...
    @property
    def Children(self) -> VisualCollection: ...

class SpriteVisual(ComPtr):
    Size: Vector2
    Offset: Vector3
    Brush: CompositionColorBrush | CompositionBackdropBrush | CompositionSurfaceBrush
    Shadow: DropShadow

class ShapeVisual(ComPtr):
    Size: Vector2
    @property
    def Shapes(self) -> CompositionShapeCollection: ...

class CompositionVisualSurface(ComPtr):
    SourceVisual: ShapeVisual
    SourceSize: Vector2

class DropShadow(ComPtr):
    Color: Color
    Opacity: float
    Mask: CompositionSurfaceBrush
    BlurRadius: float
    Offset: Vector3

class Compositor(ComPtr):
    def __init__(self) -> None: ...
    def Close(self) -> None: ...
    def CreateContainerVisual(self) -> ContainerVisual: ...
    def CreateSpriteVisual(self) -> SpriteVisual: ...
    def CreateShapeVisual(self) -> ShapeVisual: ...
    def CreateVisualSurface(self) -> CompositionVisualSurface: ...
    def CreateDropShadow(self) -> DropShadow: ...
    def CreateHostBackdropBrush(self) -> CompositionBackdropBrush: ...
    def CreateColorBrush(self) -> CompositionColorBrush: ...
    def CreateColorBrushWithColor(self, color: Color) -> CompositionColorBrush: ...
    def CreateSurfaceBrushWithSurface(self, surface: CompositionVisualSurface) -> CompositionSurfaceBrush: ...
    def CreateRoundedRectangleGeometry(self) -> CompositionRoundedRectangleGeometry: ...
    def CreatePathGeometryWithPath(self, path: CompositionPath) -> CompositionPathGeometry: ...
    def CreateGeometricClipWithGeometry(
        self, geometry: CompositionPathGeometry | CompositionRoundedRectangleGeometry,
    ) -> CompositionGeometricClip: ...
    def CreateSpriteShapeWithGeometry(self, geometry: CompositionPathGeometry | CompositionRoundedRectangleGeometry) -> CompositionSpriteShape: ...
