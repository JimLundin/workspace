"""Rounded desktop glass and shadows, owned by the assistant's UI thread.

Windows composes a host backdrop through a rounded geometry. A separate,
nonactivating window places it immediately behind the per-pixel Qt foreground;
neither desktop captures nor color keys participate in rendering. `Glass` gives
one card its own window; `GlassScene` composes several panes in one window, so
panes move without moving any window.
"""

import ctypes
import time
from collections.abc import Callable
from dataclasses import dataclass

from win32more import FAILED, WinError
from win32more.Windows.Foundation import IAsyncInfo
from win32more.Windows.Foundation.Numerics import Vector2, Vector3
from win32more.Windows.System import DispatcherQueueController
from win32more.Windows.UI import Color
from win32more.Windows.UI.Composition import (
    CompositionColorBrush,
    CompositionLinearGradientBrush,
    CompositionPropertySet,
    Compositor,
    ContainerVisual,
    DropShadow,
    ICompositionRoundedRectangleGeometry,
    IVisual,
)
from win32more.Windows.UI.Composition.Desktop import DesktopWindowTarget
from win32more.Windows.Win32.Foundation import GetLastError
from win32more.Windows.Win32.Graphics.Dwm import DwmSetWindowAttribute
from win32more.Windows.Win32.System.LibraryLoader import GetModuleHandleW
from win32more.Windows.Win32.System.WinRT import (
    RO_INIT_SINGLETHREADED,
    CreateDispatcherQueueController,
    DispatcherQueueOptions,
    RoInitialize,
    RoUninitialize,
)
from win32more.Windows.Win32.System.WinRT.Composition import ICompositorDesktopInterop
from win32more.Windows.Win32.UI.WindowsAndMessaging import CreateWindowExW, GetWindow, SetWindowPos

from winapi import windows
from winapi._core import NativeFunction
from winapi.shapes import Pane, Rect


def _check(result: object) -> None:
    match result:
        case int() as value:
            if FAILED(value):
                raise WinError(value)
        case _:
            raise TypeError("Windows returned an invalid HRESULT.")


def _color(value: str, opacity: float) -> Color:
    return Color(round(max(0, min(1, opacity)) * 255), int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


def borderless(handle: int) -> None:
    """The vector silhouette supplies the edge; suppress Windows 11's rectangular frame."""
    none = ctypes.c_uint32(0xFFFF_FFFE)  # DWMWA_COLOR_NONE; older Windows can ignore this attribute.
    DwmSetWindowAttribute(handle, 34, ctypes.byref(none), ctypes.sizeof(none))


def stack_behind(handle: int, foreground: int) -> None:
    """Place native glass below its foreground without activation or movement."""
    SetWindowPos(handle, foreground, 0, 0, 0, 0, 0x0013)


@dataclass(frozen=True, slots=True)
class VisualBindings:
    """Immutable identities for one Glass-owned native scene.

    These five facets are one scene: root, clipped group, shadow sibling,
    rounded geometry and its size-bearing visuals. Their native contents must
    change on Glass's UI/dispatcher thread; only their identities are stored
    here. Querying them together preserves that single ownership/lifetime.
    """

    root: IVisual
    group: IVisual
    shadow: IVisual
    rounded: ICompositionRoundedRectangleGeometry
    sized: tuple[IVisual, ...]


class DesktopComposition:
    __slots__ = ("closed", "compositor", "interop", "queue")

    def __init__(self) -> None:
        _check(RoInitialize(RO_INIT_SINGLETHREADED))
        self.closed = False
        self.queue: DispatcherQueueController = DispatcherQueueController(own=True)
        try:
            _check(CreateDispatcherQueueController(DispatcherQueueOptions(ctypes.sizeof(DispatcherQueueOptions), 2, 2), self.queue))
            self.compositor: Compositor = Compositor()
            self.interop: ICompositorDesktopInterop = self.compositor.as_(ICompositorDesktopInterop)
        except BaseException:
            RoUninitialize()
            raise

    def glass(self) -> Glass:
        return Glass(self)

    def scene(self, title: str) -> GlassScene:
        return GlassScene(self, title)

    def close(self, pump: Callable[[], None]) -> None:
        """Drain the native dispatcher before its owning UI thread can exit."""
        if self.closed:
            return
        self.closed = True
        self.compositor.Close()
        shutdown = self.queue.ShutdownQueueAsync().as_(IAsyncInfo)
        deadline = time.monotonic() + 2
        while shutdown.Status == 0:
            pump()
            if time.monotonic() >= deadline:
                raise RuntimeError("The desktop composition dispatcher did not finish shutting down.")
            time.sleep(0.001)
        if shutdown.Status != 1:
            raise OSError("The desktop composition dispatcher could not shut down cleanly.")
        RoUninitialize()


class Glass:
    __slots__ = (
        "backdrop",
        "bindings",
        "bounds",
        "clip",
        "closed",
        "compositor",
        "geometry",
        "group",
        "handle",
        "mask",
        "mask_surface",
        "mask_visual",
        "opacity",
        "root",
        "shadow",
        "shadow_visual",
        "size",
        "stack",
        "target",
        "tint",
        "tint_brush",
        "visible",
    )

    def __init__(
        self,
        owner: DesktopComposition,
        *,
        stack: Callable[[int, int], None] = stack_behind,
    ) -> None:
        self.stack = stack
        # NOREDIRECTIONBITMAP lets composition supply the entire surface. It is
        # intentionally not a layered/color-keyed window.
        self.handle = (
            CreateWindowExW(0x0820_00A0, "STATIC", "Workspace · Glass", 0x8000_0000, 0, 0, 1, 1, None, None, GetModuleHandleW(None), None) or 0
        )
        if not self.handle:
            raise ctypes.WinError(GetLastError())
        self.closed = self.visible = False
        self.bounds: Rect | None = None
        self.size: tuple[int, int, float] | None = None
        self.opacity = 1.0
        try:
            enabled = ctypes.c_int(1)
            _check(DwmSetWindowAttribute(self.handle, 17, ctypes.byref(enabled), ctypes.sizeof(enabled)))
            self.target: DesktopWindowTarget = DesktopWindowTarget(own=True)
            _check(owner.interop.CreateDesktopWindowTarget(self.handle, False, self.target))
            self.compositor = compositor = owner.compositor
            borderless(self.handle)
            self.root = compositor.CreateContainerVisual()
            self.target.Root = self.root
            # Geometry and clip identities belong to this native owner; shape
            # setters update their contents without rebuilding the graph.
            self.geometry = compositor.CreateRoundedRectangleGeometry()
            self.group = compositor.CreateContainerVisual()
            self.clip = compositor.CreateGeometricClipWithGeometry(self.geometry)
            self.group.Clip = self.clip

            # The shadow uses the same rounded silhouette as the glass. Its
            # source visual is offscreen; the compositor retains the mask.
            mask_shape = compositor.CreateSpriteShapeWithGeometry(self.geometry)
            mask_shape.FillBrush = compositor.CreateColorBrushWithColor(_color("#ffffff", 1))
            self.mask_visual = compositor.CreateShapeVisual()
            self.mask_visual.Shapes.Append(mask_shape)
            self.mask_surface = compositor.CreateVisualSurface()
            self.mask_surface.SourceVisual = self.mask_visual
            self.mask = compositor.CreateSurfaceBrushWithSurface(self.mask_surface)
            self.shadow = compositor.CreateDropShadow()
            self.shadow.Color = _color("#000000", 1)
            self.shadow.Opacity = 0.28
            self.shadow.Mask = self.mask
            self.shadow_visual = compositor.CreateSpriteVisual()
            self.shadow_visual.Shadow = self.shadow
            self.root.Children.InsertAtTop(self.shadow_visual)
            self.root.Children.InsertAtTop(self.group)
            self.backdrop = compositor.CreateSpriteVisual()
            self.backdrop.Brush = compositor.CreateHostBackdropBrush()
            self.group.Children.InsertAtTop(self.backdrop)
            self.tint_brush = compositor.CreateColorBrush()
            self.tint = compositor.CreateSpriteVisual()
            self.tint.Brush = self.tint_brush
            self.group.Children.InsertAtTop(self.tint)
            self.bindings: VisualBindings = self.bind_visuals()
        except BaseException:
            windows.destroy(self.handle)
            raise

    def color(self, tint: str, opacity: float = 0.22) -> None:
        self.tint_brush.Color = _color(tint, opacity)

    def bind_visuals(self) -> VisualBindings:
        # SDK convenience setters resolve annotations and QueryInterface on
        # every call: size publication measured 0.50 ms through that route,
        # versus 0.13 ms through the regular native interface. Retain native
        # bindings inside this scene's owning UI thread/dispatcher lifetime.
        group, shadow = self.group.as_(IVisual), self.shadow_visual.as_(IVisual)
        return VisualBindings(
            self.root.as_(IVisual),
            group,
            shadow,
            self.geometry.as_(ICompositionRoundedRectangleGeometry),
            (group, self.backdrop.as_(IVisual), self.tint.as_(IVisual), self.mask_visual.as_(IVisual), shadow),
        )

    def position(self, bounds: Rect, scale: float, opacity: float) -> None:
        padding = round(28 * scale)
        outer = Rect(bounds.left - padding, bounds.top - padding, bounds.right + padding, bounds.bottom + padding)
        if self.bounds != outer:
            self.bounds = outer
            windows.move(self.handle, outer)
        if self.size != (bounds.width, bounds.height, scale):
            self.size = (bounds.width, bounds.height, scale)
            radius = min(26 * scale, bounds.height / 2, bounds.width / 2)
            size = Vector2(bounds.width, bounds.height)
            self.bindings.rounded.Size = size
            self.bindings.rounded.CornerRadius = Vector2(radius, radius)
            self.bindings.root.Size = Vector2(outer.width, outer.height)
            for visual in self.bindings.sized:
                visual.Size = size
            self.bindings.group.Offset = self.bindings.shadow.Offset = Vector3(padding, padding, 0)
            self.mask_surface.SourceSize = size
            self.shadow.BlurRadius = 24 * scale
            self.shadow.Offset = Vector3(0, 8 * scale, 0)
        opacity = max(0, min(1, opacity))
        if self.opacity != opacity:
            self.bindings.root.Opacity = opacity
            self.opacity = opacity

    def show(self, foreground: int) -> None:
        if not self.visible:
            windows.show_quietly(self.handle, visible=True)
            self.visible = True
        # Keep the native blur below the corresponding text, including after a
        # new bubble or a context menu changes the topmost window order.
        # Observe actual ordering: cached state would miss intervening windows.
        if GetWindow(foreground, 2) != self.handle:  # GW_HWNDNEXT
            self.stack(self.handle, foreground)

    def hide(self) -> None:
        if self.visible:
            windows.show_quietly(self.handle, visible=False)
            self.visible = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.target.Root = None
        self.target.Close()
        windows.destroy(self.handle)


class Float2(ctypes.Structure):
    _fields_ = (("x", ctypes.c_float), ("y", ctypes.c_float))


class Float3(ctypes.Structure):
    _fields_ = (("x", ctypes.c_float), ("y", ctypes.c_float), ("z", ctypes.c_float))


# Windows.UI.Composition.IVisual's ABI slots, after IUnknown's three and IInspectable's three.
_PUT_OFFSET, _PUT_OPACITY, _PUT_SIZE = 21, 23, 36


def _slot(this: ctypes.c_void_p, index: int, value: type[ctypes.Structure | ctypes.c_float]) -> NativeFunction[int]:
    vtable = ctypes.cast(this, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, value)
    return prototype(vtable[index])


@dataclass(frozen=True, slots=True)
class VisualWriter:
    """A visual's three per-frame property writes, straight through its COM slots.

    win32more's generic WinRT dispatch binds and converts arguments on every call:
    measured 44 µs per write, against 2.2 µs through the slot. The writer holds only
    the interface pointer; its PaneGroup owns the visual's reference and lifetime.
    """

    this: ctypes.c_void_p
    offset: NativeFunction[int]
    opacity: NativeFunction[int]
    size: NativeFunction[int]

    @classmethod
    def of(cls, visual: IVisual) -> VisualWriter:
        this = ctypes.c_void_p(visual.value)
        return cls(this, _slot(this, _PUT_OFFSET, Float3), _slot(this, _PUT_OPACITY, ctypes.c_float), _slot(this, _PUT_SIZE, Float2))

    def place(self, x: float, y: float) -> None:
        _check(self.offset(self.this, Float3(x, y, 0)))

    def resize(self, width: float, height: float) -> None:
        _check(self.size(self.this, Float2(width, height)))

    def fade(self, opacity: float) -> None:
        _check(self.opacity(self.this, ctypes.c_float(opacity)))


class PaneGroup:
    """One pane's retained native visuals, reused each time its key reappears.

    Expression animations derive the clip geometry, corner radius, rim, shadow
    and its mask from the group's own size, offset and opacity, so publishing
    a frame writes only those three properties. Native ownership requires the
    published state to live with the visuals it describes.
    """

    __slots__ = ("compositor", "group", "properties", "published", "rim", "shadow", "tint", "visual", "writer")

    def __init__(self, compositor: Compositor, root: ContainerVisual) -> None:
        self.compositor = compositor
        self.group = compositor.CreateContainerVisual()
        geometry = compositor.CreateRoundedRectangleGeometry()
        self.group.Clip = compositor.CreateGeometricClipWithGeometry(geometry)
        backdrop = compositor.CreateSpriteVisual()
        backdrop.Brush = compositor.CreateHostBackdropBrush()
        self.tint: CompositionColorBrush = compositor.CreateColorBrush()
        tint = compositor.CreateSpriteVisual()
        tint.Brush = self.tint
        self.rim: CompositionLinearGradientBrush = compositor.CreateLinearGradientBrush()
        self.rim.StartPoint, self.rim.EndPoint = Vector2(0.3, 0), Vector2(0.7, 1)
        stroke = compositor.CreateSpriteShapeWithGeometry(geometry)
        stroke.StrokeBrush = self.rim
        stroke.StrokeThickness = 2  # Half lies outside the clip: one pixel of rim inside the edge.
        rim = compositor.CreateShapeVisual()
        rim.Shapes.Append(stroke)
        for child in (backdrop, tint, rim):
            child.RelativeSizeAdjustment = Vector2(1, 1)
            self.group.Children.InsertAtTop(child)
        fill = compositor.CreateSpriteShapeWithGeometry(geometry)
        fill.FillBrush = compositor.CreateColorBrushWithColor(_color("#ffffff", 1))
        mask = compositor.CreateShapeVisual()
        mask.Shapes.Append(fill)
        surface = compositor.CreateVisualSurface()
        surface.SourceVisual = mask
        self.shadow: DropShadow = compositor.CreateDropShadow()
        self.shadow.Color = _color("#000000", 1)
        self.shadow.Mask = compositor.CreateSurfaceBrushWithSurface(surface)
        shadow = compositor.CreateSpriteVisual()
        shadow.Shadow = self.shadow
        root.Children.InsertAtTop(shadow)
        root.Children.InsertAtTop(self.group)
        self.properties: CompositionPropertySet = compositor.CreatePropertySet()
        self.properties.InsertScalar("radius", 0)
        for target, name, expression in (
            (geometry, "Size", "g.Size"),
            (geometry, "CornerRadius", "Vector2(Min(g.Size.Y / 2, p.radius), Min(g.Size.Y / 2, p.radius))"),
            (mask, "Size", "g.Size"),
            (surface, "SourceSize", "g.Size"),
            (shadow, "Offset", "g.Offset"),
            (shadow, "Size", "g.Size"),
            (shadow, "Opacity", "g.Opacity"),
        ):
            animation = compositor.CreateExpressionAnimationWithExpression(expression)
            animation.SetReferenceParameter("g", self.group)
            animation.SetReferenceParameter("p", self.properties)
            target.StartAnimation(name, animation)
        self.visual: IVisual = self.group.as_(IVisual)
        self.writer = VisualWriter.of(self.visual)
        self.writer.fade(0)
        self.published: Pane | None = None

    def publish(self, pane: Pane) -> None:
        last = self.published
        self.published = pane
        if last is None or (last.bounds.left, last.bounds.top) != (pane.bounds.left, pane.bounds.top):
            self.writer.place(pane.bounds.left, pane.bounds.top)
        if last is None or (last.bounds.width, last.bounds.height) != (pane.bounds.width, pane.bounds.height):
            self.writer.resize(pane.bounds.width, pane.bounds.height)
        if last is None or last.radius != pane.radius:
            self.properties.InsertScalar("radius", pane.radius)
        if last is None or last.opacity != pane.opacity:
            self.writer.fade(max(0, min(1, pane.opacity)))
        if last is None or last.veil != pane.veil:
            self.tint.Color = _color(pane.veil.tint, pane.veil.opacity)
            self.shadow.Opacity = pane.veil.shadow
            stops = self.rim.ColorStops
            stops.Clear()
            for stop in pane.veil.rim:
                stops.Append(self.compositor.CreateColorGradientStopWithOffsetAndColor(stop.offset, _color(stop.color, stop.opacity)))

    def release(self) -> None:
        if self.published is not None:
            self.writer.fade(0)
            self.published = None


class GlassScene:
    """Several glass panes composed in one nonactivating window behind their Qt foreground.

    Pane groups are pooled by key for the scene's lifetime: a capsule that leaves
    and returns reuses its native visuals instead of allocating new ones.
    """

    __slots__ = ("bounds", "closed", "compositor", "groups", "handle", "root", "scale", "stack", "target", "visible")

    def __init__(self, owner: DesktopComposition, title: str, *, stack: Callable[[int, int], None] = stack_behind) -> None:
        self.stack = stack
        self.handle = CreateWindowExW(0x0820_00A0, "STATIC", title, 0x8000_0000, 0, 0, 1, 1, None, None, GetModuleHandleW(None), None) or 0
        if not self.handle:
            raise ctypes.WinError(GetLastError())
        self.closed = self.visible = False
        self.bounds: Rect | None = None
        self.scale = 0.0
        self.groups: frozendict[str, PaneGroup] = frozendict()
        try:
            enabled = ctypes.c_int(1)
            _check(DwmSetWindowAttribute(self.handle, 17, ctypes.byref(enabled), ctypes.sizeof(enabled)))
            self.target: DesktopWindowTarget = DesktopWindowTarget(own=True)
            _check(owner.interop.CreateDesktopWindowTarget(self.handle, False, self.target))
            self.compositor: Compositor = owner.compositor
            borderless(self.handle)
            self.root = self.compositor.CreateContainerVisual()
            self.target.Root = self.root
        except BaseException:
            windows.destroy(self.handle)
            raise

    def place(self, bounds: Rect, scale: float) -> None:
        """Cover the screen area the panes can reach, in device pixels."""
        if self.bounds != bounds:
            self.bounds = bounds
            windows.move(self.handle, bounds)
            self.root.as_(IVisual).Size = Vector2(bounds.width, bounds.height)
        if self.scale != scale:
            self.scale = scale
            for group in self.groups.values():
                group.shadow.BlurRadius = 24 * scale
                group.shadow.Offset = Vector3(0, 8 * scale, 0)

    def publish(self, panes: tuple[Pane, ...]) -> None:
        """Show exactly these panes; any other pooled pane hides until its key returns."""
        keys = frozenset(pane.key for pane in panes)
        for pane in panes:
            group = self.groups.get(pane.key)
            if group is None:
                group = PaneGroup(self.compositor, self.root)
                group.shadow.BlurRadius = 24 * self.scale
                group.shadow.Offset = Vector3(0, 8 * self.scale, 0)
                self.groups = frozendict(self.groups | {pane.key: group})
            if group.published != pane:
                group.publish(pane)
        for key, group in self.groups.items():
            if key not in keys:
                group.release()

    def published(self) -> tuple[Pane, ...]:
        return tuple(group.published for group in self.groups.values() if group.published is not None)

    def show(self, foreground: int) -> None:
        if not self.visible:
            windows.show_quietly(self.handle, visible=True)
            self.visible = True
        if GetWindow(foreground, 2) != self.handle:  # GW_HWNDNEXT
            self.stack(self.handle, foreground)

    def hide(self) -> None:
        if self.visible:
            windows.show_quietly(self.handle, visible=False)
            self.visible = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.groups = frozendict()
        self.target.Root = None
        self.target.Close()
        windows.destroy(self.handle)
