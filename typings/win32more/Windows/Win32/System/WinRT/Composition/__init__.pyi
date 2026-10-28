from win32more._win32 import ComPtr
from win32more.Windows.UI.Composition.Desktop import DesktopWindowTarget

class ICompositorDesktopInterop(ComPtr):
    def CreateDesktopWindowTarget(self, handle: int, is_topmost: bool, target: DesktopWindowTarget) -> int: ...
