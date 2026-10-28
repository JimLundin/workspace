from win32more._win32 import ComPtr
from win32more.Windows.UI.Composition import ContainerVisual

class DesktopWindowTarget(ComPtr):
    Root: ContainerVisual | None
    def Close(self) -> None: ...
