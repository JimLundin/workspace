"""Rounded desktop glass and shadows, owned by the assistant's UI thread.

Windows composes a host backdrop through a rounded geometry. A separate,
nonactivating window places it immediately behind the per-pixel Qt foreground;
neither desktop captures nor color keys participate in rendering. `GlassScene`
composes several panes in one window, so panes move without moving any window.
"""

import ctypes
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Final

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
from win32more.Windows.Win32.UI.WindowsAndMessaging import (
    LWA_ALPHA,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_NOREDIRECTIONBITMAP,
    WS_EX_TOOLWINDOW,
    WS_EX_TRANSPARENT,
    WS_POPUP,
    CreateWindowExW,
    GetWindow,
    SetLayeredWindowAttributes,
    SetWindowPos,
)

from cell import Cell
from winapi import windows
from winapi._core import NativeFunction, com_method
from winapi.shapes import Lighting, Pane, Rect


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


_GLASS_HOST: Final = WS_EX_NOACTIVATE | WS_EX_NOREDIRECTIONBITMAP | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT | WS_EX_LAYERED


def glass_host(title: str) -> int:
    """Composition owns the pixels; Windows skips this layered host for input."""
    handle = CreateWindowExW(_GLASS_HOST, "STATIC", title, WS_POPUP, 0, 0, 1, 1, None, None, GetModuleHandleW(None), None) or 0
    if not handle:
        raise ctypes.WinError(GetLastError())
    if not SetLayeredWindowAttributes(handle, 0, 255, LWA_ALPHA):
        error = GetLastError()
        windows.destroy(handle)
        raise ctypes.WinError(error)
    return handle


@dataclass(frozen=True, slots=True)
class DesktopComposition:
    queue: DispatcherQueueController
    compositor: Compositor
    interop: ICompositorDesktopInterop
    _closed: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    @classmethod
    def start(cls) -> DesktopComposition:
        _check(RoInitialize(RO_INIT_SINGLETHREADED))
        queue = DispatcherQueueController(own=True)
        try:
            _check(CreateDispatcherQueueController(DispatcherQueueOptions(ctypes.sizeof(DispatcherQueueOptions), 2, 2), queue))
            compositor = Compositor()
            return cls(queue, compositor, compositor.as_(ICompositorDesktopInterop))
        except BaseException:
            RoUninitialize()
            raise

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def scene(self, title: str, lighting: Lighting) -> GlassScene:
        return GlassScene.create(self, title, lighting)

    def close(self, pump: Callable[[], None]) -> None:
        """Drain the native dispatcher before its owning UI thread can exit."""
        if self.closed:
            return
        self._closed.set()
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


class Float2(ctypes.Structure):
    _fields_ = (("x", ctypes.c_float), ("y", ctypes.c_float))


class Float3(ctypes.Structure):
    _fields_ = (("x", ctypes.c_float), ("y", ctypes.c_float), ("z", ctypes.c_float))


# Windows.UI.Composition.IVisual's ABI slots, after IUnknown's three and IInspectable's three.
_PUT_OFFSET, _PUT_OPACITY, _PUT_SIZE = 21, 23, 36


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
        return cls(
            this,
            com_method("The composition visual", this, _PUT_OFFSET, Float3),
            com_method("The composition visual", this, _PUT_OPACITY, ctypes.c_float),
            com_method("The composition visual", this, _PUT_SIZE, Float2),
        )

    def place(self, x: float, y: float) -> None:
        _check(self.offset(self.this, Float3(x, y, 0)))

    def resize(self, width: float, height: float) -> None:
        _check(self.size(self.this, Float2(width, height)))

    def fade(self, opacity: float) -> None:
        _check(self.opacity(self.this, ctypes.c_float(opacity)))


@dataclass(frozen=True, slots=True)
class PaneGroup:
    """One pane's retained native visuals, reused each time its key reappears.

    Expression animations derive the clip geometry, corner radius, rim, shadow
    and its mask from the group's own size, offset and opacity, so publishing
    a frame writes only those three properties. Native ownership requires the
    published state to live with the visuals it describes.
    """

    compositor: Compositor
    tint: CompositionColorBrush
    rim: CompositionLinearGradientBrush
    shadow: DropShadow
    properties: CompositionPropertySet
    visual: IVisual
    writer: VisualWriter
    _retained: tuple[object, ...]
    """The rest of the native graph, kept alive with the pane."""
    _published: Cell[Pane | None] = field(default_factory=lambda: Cell[Pane | None](None), init=False, repr=False)

    @classmethod
    def create(cls, compositor: Compositor, root: ContainerVisual, lighting: Lighting) -> PaneGroup:
        group = compositor.CreateContainerVisual()
        geometry = compositor.CreateRoundedRectangleGeometry()
        group.Clip = compositor.CreateGeometricClipWithGeometry(geometry)
        backdrop = compositor.CreateSpriteVisual()
        backdrop.Brush = compositor.CreateHostBackdropBrush()
        tint_brush: CompositionColorBrush = compositor.CreateColorBrush()
        tint = compositor.CreateSpriteVisual()
        tint.Brush = tint_brush
        rim_brush: CompositionLinearGradientBrush = compositor.CreateLinearGradientBrush()
        # The gradient runs along the rim's angle, from one edge of the pane's unit square to the opposite one.
        direction = math.radians(lighting.rim_angle)
        dx, dy = math.sin(direction), -math.cos(direction)
        reach = 0.5 / max(abs(dx), abs(dy))
        rim_brush.StartPoint, rim_brush.EndPoint = Vector2(0.5 - dx * reach, 0.5 - dy * reach), Vector2(0.5 + dx * reach, 0.5 + dy * reach)
        stroke = compositor.CreateSpriteShapeWithGeometry(geometry)
        stroke.StrokeBrush = rim_brush
        stroke.StrokeThickness = lighting.rim_stroke
        rim = compositor.CreateShapeVisual()
        rim.Shapes.Append(stroke)
        for child in (backdrop, tint, rim):
            child.RelativeSizeAdjustment = Vector2(1, 1)
            group.Children.InsertAtTop(child)
        fill = compositor.CreateSpriteShapeWithGeometry(geometry)
        fill.FillBrush = compositor.CreateColorBrushWithColor(_color("#ffffff", 1))
        mask = compositor.CreateShapeVisual()
        mask.Shapes.Append(fill)
        surface = compositor.CreateVisualSurface()
        surface.SourceVisual = mask
        drop: DropShadow = compositor.CreateDropShadow()
        drop.Color = _color(lighting.shadow_color, 1)
        drop.Mask = compositor.CreateSurfaceBrushWithSurface(surface)
        shadow = compositor.CreateSpriteVisual()
        shadow.Shadow = drop
        root.Children.InsertAtTop(shadow)
        root.Children.InsertAtTop(group)
        properties: CompositionPropertySet = compositor.CreatePropertySet()
        properties.InsertScalar("radius", 0)
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
            animation.SetReferenceParameter("g", group)
            animation.SetReferenceParameter("p", properties)
            target.StartAnimation(name, animation)
        visual: IVisual = group.as_(IVisual)
        writer = VisualWriter.of(visual)
        writer.fade(0)
        retained = (group, geometry, backdrop, tint, stroke, rim, fill, mask, surface, shadow)
        return cls(compositor, tint_brush, rim_brush, drop, properties, visual, writer, retained)

    @property
    def published(self) -> Pane | None:
        return self._published.get()

    def publish(self, pane: Pane) -> None:
        last = self._published.get()
        self._published.set(pane)
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
        if self._published.get() is not None:
            self.writer.fade(0)
            self._published.set(None)


@dataclass(frozen=True, slots=True)
class _Composed:
    bounds: Rect | None = None
    scale: float = 0.0
    groups: frozendict[str, PaneGroup] = frozendict()
    """Pane groups pooled by key for the scene's lifetime."""
    visible: bool = False
    closed: bool = False


@dataclass(frozen=True, slots=True)
class GlassScene:
    """Several glass panes composed in one nonactivating window behind their Qt foreground.

    Pane groups are pooled by key for the scene's lifetime: a capsule that leaves
    and returns reuses its native visuals instead of allocating new ones.
    """

    stack: Callable[[int, int], None]
    handle: int
    target: DesktopWindowTarget
    compositor: Compositor
    root: ContainerVisual
    lighting: Lighting
    _composed: Cell[_Composed] = field(default_factory=lambda: Cell(_Composed()), init=False, repr=False)

    @classmethod
    def create(cls, owner: DesktopComposition, title: str, lighting: Lighting, *, stack: Callable[[int, int], None] = stack_behind) -> GlassScene:
        handle = glass_host(title)
        try:
            enabled = ctypes.c_int(1)
            _check(DwmSetWindowAttribute(handle, 17, ctypes.byref(enabled), ctypes.sizeof(enabled)))
            target = DesktopWindowTarget(own=True)
            _check(owner.interop.CreateDesktopWindowTarget(handle, False, target))
            compositor: Compositor = owner.compositor
            borderless(handle)
            root = compositor.CreateContainerVisual()
            target.Root = root
        except BaseException:
            windows.destroy(handle)
            raise
        return cls(stack, handle, target, compositor, root, lighting)

    @property
    def bounds(self) -> Rect | None:
        return self._composed.get().bounds

    @property
    def groups(self) -> frozendict[str, PaneGroup]:
        return self._composed.get().groups

    def place(self, bounds: Rect, scale: float) -> None:
        """Cover the screen area the panes can reach, in device pixels."""
        composed = self._composed.get()
        if composed.bounds != bounds:
            windows.move(self.handle, bounds)
            self.root.as_(IVisual).Size = Vector2(bounds.width, bounds.height)
        if composed.scale != scale:
            for group in composed.groups.values():
                self.cast(group, scale)
        self._composed.set(replace(composed, bounds=bounds, scale=scale))

    def cast(self, group: PaneGroup, scale: float) -> None:
        """The group's shadow at the scene's scale."""
        group.shadow.BlurRadius = self.lighting.shadow_blur * scale
        group.shadow.Offset = Vector3(0, self.lighting.shadow_drop * scale, 0)

    def publish(self, panes: tuple[Pane, ...]) -> None:
        """Show exactly these panes; any other pooled pane hides until its key returns."""
        keys = frozenset(pane.key for pane in panes)
        for pane in panes:
            composed = self._composed.get()
            group = composed.groups.get(pane.key)
            if group is None:
                group = PaneGroup.create(self.compositor, self.root, self.lighting)
                self.cast(group, composed.scale)
                self._composed.set(replace(composed, groups=frozendict(composed.groups | {pane.key: group})))
            if group.published != pane:
                group.publish(pane)
        for key, group in self.groups.items():
            if key not in keys:
                group.release()

    def published(self) -> tuple[Pane, ...]:
        return tuple(published for group in self.groups.values() if (published := group.published))

    def show(self, foreground: int) -> None:
        if not self._composed.get().visible:
            windows.show_quietly(self.handle, visible=True)
            self._composed.update(lambda composed: replace(composed, visible=True))
        # Keep the native blur below the corresponding text, including after a
        # new bubble or a context menu changes the topmost window order.
        # Observe actual ordering: cached state would miss intervening windows.
        if GetWindow(foreground, 2) != self.handle:  # GW_HWNDNEXT
            self.stack(self.handle, foreground)

    def hide(self) -> None:
        if self._composed.get().visible:
            windows.show_quietly(self.handle, visible=False)
            self._composed.update(lambda composed: replace(composed, visible=False))

    def close(self) -> None:
        if self._composed.get().closed:
            return
        self._composed.update(lambda composed: replace(composed, closed=True, groups=frozendict()))
        self.target.Root = None
        self.target.Close()
        windows.destroy(self.handle)
