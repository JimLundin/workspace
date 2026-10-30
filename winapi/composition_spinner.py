"""A compact native loading surface, animated independently of Qt painting."""

import ctypes
import math

from win32more import FAILED, WinError
from win32more.Windows.Foundation import TimeSpan
from win32more.Windows.Foundation.Numerics import Vector2, Vector3
from win32more.Windows.UI import Color
from win32more.Windows.UI.Composition import AnimationIterationBehavior, Compositor, ContainerVisual
from win32more.Windows.UI.Composition.Desktop import DesktopWindowTarget
from win32more.Windows.Win32.Foundation import GetLastError
from win32more.Windows.Win32.System.LibraryLoader import GetModuleHandleW
from win32more.Windows.Win32.UI.WindowsAndMessaging import CreateWindowExW

from winapi import screen, windows
from winapi.composition import DesktopComposition, borderless
from winapi.shapes import Rect


class CompositionSpinner:
    """Own one popup HWND/target; Windows owns the wheel's frame updates."""

    __slots__ = ("closed", "compositor", "handle", "root", "rotating", "size", "target", "wheel")

    def __init__(self, owner: DesktopComposition) -> None:
        self.closed = False
        self.rotating = False
        # Match the existing desktop glass's nonactivating composition host.
        # NOREDIRECTIONBITMAP gives Windows the whole surface; this is not a
        # Qt child or a per-pixel layered window with a competing backing store.
        self.handle: int = (
            CreateWindowExW(0x0820_00A0, "STATIC", "Workspace · Opening canvas", 0x8000_0000, 0, 0, 1, 1, None, None, GetModuleHandleW(None), None)
            or 0
        )
        if not self.handle:
            raise ctypes.WinError(GetLastError())
        self.target: DesktopWindowTarget = DesktopWindowTarget(own=True)
        try:
            result = owner.interop.CreateDesktopWindowTarget(self.handle, True, self.target)
            if FAILED(result):
                raise WinError(result)
            try:
                borderless(self.handle)
                self.compositor: Compositor = owner.compositor
                compositor = self.compositor
                scale = windows.scale(self.handle)
                self.size: int = round(80 * scale)
                self.root: ContainerVisual = compositor.CreateContainerVisual()
                self.root.Size = Vector2(self.size, self.size)
                background = compositor.CreateRoundedRectangleGeometry()
                background.Size = Vector2(self.size, self.size)
                background.CornerRadius = Vector2(20 * scale, 20 * scale)
                shape = compositor.CreateSpriteShapeWithGeometry(background)
                shape.FillBrush = compositor.CreateColorBrushWithColor(Color(255, 37, 33, 47))
                surface = compositor.CreateShapeVisual()
                surface.Size = Vector2(self.size, self.size)
                surface.Shapes.Append(shape)
                self.root.Children.InsertAtTop(surface)
                self.wheel: ContainerVisual = compositor.CreateContainerVisual()
                self.wheel.Size = Vector2(40 * scale, 40 * scale)
                self.wheel.Offset = Vector3(20 * scale, 20 * scale, 0)
                self.wheel.CenterPoint = Vector3(20 * scale, 20 * scale, 0)
                for index in range(8):
                    angle = index * math.tau / 8
                    geometry = compositor.CreateRoundedRectangleGeometry()
                    geometry.Offset = Vector2((18 + 15 * math.cos(angle)) * scale, (18 + 15 * math.sin(angle)) * scale)
                    geometry.Size = Vector2(4 * scale, 4 * scale)
                    geometry.CornerRadius = Vector2(2 * scale, 2 * scale)
                    dot_shape = compositor.CreateSpriteShapeWithGeometry(geometry)
                    dot_shape.FillBrush = compositor.CreateColorBrushWithColor(Color(round(255 * (index + 1) / 8), 217, 200, 243))
                    dot = compositor.CreateShapeVisual()
                    dot.Size = Vector2(40 * scale, 40 * scale)
                    dot.Shapes.Append(dot_shape)
                    self.wheel.Children.InsertAtTop(dot)
                self.root.Children.InsertAtTop(self.wheel)
                self.target.Root = self.root
            except BaseException:
                self.target.Close()
                raise
        except BaseException:
            windows.destroy(self.handle)
            raise

    def show(self, *, animate: bool) -> None:
        if self.closed:
            return
        area = screen.monitor_of(self.handle).work
        left = area.left + (area.width - self.size) // 2
        top = area.top + (area.height - self.size) // 2
        windows.move(self.handle, Rect(left, top, left + self.size, top + self.size))
        if animate:
            animation = self.compositor.CreateScalarKeyFrameAnimation()
            animation.InsertKeyFrame(0, 0)
            animation.InsertKeyFrameWithEasingFunction(1, 360, self.compositor.CreateLinearEasingFunction())
            animation.Duration = TimeSpan(12_000_000)
            animation.IterationBehavior = AnimationIterationBehavior.Forever
            self.wheel.StartAnimation("RotationAngleInDegrees", animation)
            self.rotating = True
        self.compositor.RequestCommitAsync()
        windows.show_quietly(self.handle, visible=True)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.wheel.StopAnimation("RotationAngleInDegrees")
        self.rotating = False
        self.target.Root = None
        self.target.Close()
        windows.destroy(self.handle)
