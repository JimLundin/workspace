from win32more._win32 import ComPtr

class AppDisplayInfo(ComPtr):
    @property
    def DisplayName(self) -> str: ...

class AppInfo(ComPtr):
    @property
    def AppUserModelId(self) -> str: ...
    @property
    def DisplayInfo(self) -> AppDisplayInfo: ...
