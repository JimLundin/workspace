"""Rounded desktop glass and shadows, owned by the assistant's UI thread.

Windows composes a host backdrop through a rounded geometry. A separate,
nonactivating window places it immediately behind the per-pixel Qt foreground;
neither desktop captures nor color keys participate in rendering.
"""

import ctypes
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from win32more import FAILED, WinError
from win32more.Windows.Foundation import IAsyncInfo
from win32more.Windows.Foundation.Numerics import Vector2, Vector3
from win32more.Windows.System import DispatcherQueueController
from win32more.Windows.UI import Color
from win32more.Windows.UI.Composition import (
    CompositionPath,
    CompositionPathGeometry,
    CompositionRoundedRectangleGeometry,
    Compositor,
    ICompositionPathGeometry,
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
from winapi.composition_paths import composition_path
from winapi.contours import Contour
from winapi.shapes import Rect


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


class CachedPaths(Protocol):
    """Consume the standard cache's call and release contracts at its owner."""

    def __call__(self, contour: Contour, scale: float, /) -> CompositionPath: ...
    def cache_clear(self) -> None: ...


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
            time.sleep(.001)
        if shutdown.Status != 1:
            raise OSError("The desktop composition dispatcher could not shut down cleanly.")
        RoUninitialize()


class Glass:
    __slots__ = (
        "backdrop", "bindings", "bounds", "clip", "closed", "compositor", "geometry", "group", "handle", "mask", "mask_shape", "mask_surface", "mask_visual",
        "opacity", "path_geometry", "paths", "root", "rounded_geometry", "shadow", "shadow_visual", "size", "stack", "target", "tint", "tint_brush", "visible",
    )

    def __init__(self, owner: DesktopComposition, *, create_path: Callable[[Contour, float], CompositionPath] = composition_path,
                 stack: Callable[[int, int], None] = stack_behind) -> None:
        # Native paths contain COM-owned callback bindings. Retain at most eight
        # recent shape/scale variants per glass owner to avoid rebuilding those
        # bindings on common toolbar reversals. The standard library owns cache
        # mechanics; this owner clears its native references on close. No path
        # crosses composition/dispatcher lifetimes or UI threads.
        self.paths: CachedPaths = lru_cache(maxsize=8)(create_path)
        self.stack = stack
        # NOREDIRECTIONBITMAP lets composition supply the entire surface. It is
        # intentionally not a layered/color-keyed window.
        self.handle = CreateWindowExW(0x0820_00A0, "STATIC", "Workspace · Glass", 0x8000_0000,
                                     0, 0, 1, 1, None, None, GetModuleHandleW(None), None) or 0
        if not self.handle:
            raise ctypes.WinError(GetLastError())
        self.closed = self.visible = False
        self.bounds: Rect | None = None
        self.size: tuple[int, int, float, bool, Contour | None] | None = None
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
            # Geometry and clip identities belong to this native owner. Shape
            # setters update their contents; rebuilding the graph on each join
            # change repeats native allocations and SDK interface resolution.
            self.rounded_geometry = compositor.CreateRoundedRectangleGeometry()
            self.path_geometry: CompositionPathGeometry | None = None
            self.geometry: CompositionPathGeometry | CompositionRoundedRectangleGeometry = self.rounded_geometry
            self.group = compositor.CreateContainerVisual()
            self.clip = compositor.CreateGeometricClipWithGeometry(self.geometry)
            self.group.Clip = self.clip

            # The shadow uses the same rounded silhouette as the glass. Its
            # source visual is offscreen; the compositor retains the mask.
            self.mask_shape = compositor.CreateSpriteShapeWithGeometry(self.geometry)
            self.mask_shape.FillBrush = compositor.CreateColorBrushWithColor(_color("#ffffff", 1))
            self.mask_visual = compositor.CreateShapeVisual()
            self.mask_visual.Shapes.Append(self.mask_shape)
            self.mask_surface = compositor.CreateVisualSurface()
            self.mask_surface.SourceVisual = self.mask_visual
            self.mask = compositor.CreateSurfaceBrushWithSurface(self.mask_surface)
            self.shadow = compositor.CreateDropShadow()
            self.shadow.Color = _color("#000000", 1)
            self.shadow.Opacity = .28
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

    def color(self, tint: str, opacity: float = .22) -> None:
        self.tint_brush.Color = _color(tint, opacity)

    def bind_visuals(self) -> VisualBindings:
        # SDK convenience setters resolve annotations and QueryInterface on
        # every call: size publication measured 0.50 ms through that route,
        # versus 0.13 ms through the regular native interface. Retain native
        # bindings inside this scene's owning UI thread/dispatcher lifetime.
        group, shadow = self.group.as_(IVisual), self.shadow_visual.as_(IVisual)
        return VisualBindings(self.root.as_(IVisual), group, shadow,
                              self.rounded_geometry.as_(ICompositionRoundedRectangleGeometry),
                              (group, self.backdrop.as_(IVisual), self.tint.as_(IVisual), self.mask_visual.as_(IVisual), shadow))

    def position(self, bounds: Rect, scale: float, opacity: float, *, attached: bool = False, contour: Contour | None = None) -> None:
        padding = round(28 * scale)
        outer = Rect(bounds.left - padding, bounds.top - padding, bounds.right + padding, bounds.bottom + padding)
        if self.bounds != outer:
            self.bounds = outer
            windows.move(self.handle, outer)
        if self.size != (bounds.width, bounds.height, scale, attached, contour):
            previous = self.size
            resized = previous is None or (previous[0], previous[1], previous[2]) != (bounds.width, bounds.height, scale)
            geometry = self.geometry
            self.size = (bounds.width, bounds.height, scale, attached, contour)
            if contour is not None:
                path = self.paths(contour, scale)
                if self.path_geometry is None:
                    self.path_geometry = self.compositor.CreatePathGeometryWithPath(path)
                else:
                    self.path_geometry.as_(ICompositionPathGeometry).Path = path
                self.geometry = self.path_geometry
            else:
                rounded = self.rounded_geometry
                self.geometry = rounded
                radius = min(26 * scale, bounds.height / 2, bounds.width / 2)
                self.bindings.rounded.Offset = Vector2(0, -radius if attached else 0)
                self.bindings.rounded.Size = Vector2(bounds.width, bounds.height + radius if attached else bounds.height)
                self.bindings.rounded.CornerRadius = Vector2(radius, radius)
            if self.geometry is not geometry:
                self.clip.Geometry = self.geometry
                self.mask_shape.Geometry = self.geometry
            # Join changes update the retained path; visual dimensions and
            # shadow parameters only need publication after size/DPI changes.
            if resized:
                size = Vector2(bounds.width, bounds.height)
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
            windows.show_quietly(self.handle, True)
            self.visible = True
        # Keep the native blur below the corresponding text, including after a
        # new bubble or a context menu changes the topmost window order.
        # Observe actual ordering: cached state would miss intervening windows.
        if GetWindow(foreground, 2) != self.handle:  # GW_HWNDNEXT
            self.stack(self.handle, foreground)

    def hide(self) -> None:
        if self.visible:
            windows.show_quietly(self.handle, False)
            self.visible = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.paths.cache_clear()
        self.target.Root = None
        self.target.Close()
        windows.destroy(self.handle)
