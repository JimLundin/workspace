from collections.abc import Iterable

from win32more._win32 import ComPtr
from win32more.Windows.ApplicationModel import AppInfo

class NotificationKinds:
    Toast: int

class AdaptiveNotificationText(ComPtr):
    @property
    def Text(self) -> str: ...

class NotificationBinding(ComPtr):
    def GetTextElements(self) -> Iterable[AdaptiveNotificationText]: ...

class NotificationVisual(ComPtr):
    def GetBinding(self, template_name: str, /) -> NotificationBinding: ...

class Notification(ComPtr):
    @property
    def Visual(self) -> NotificationVisual: ...

class UserNotification(ComPtr):
    @property
    def Notification(self) -> Notification: ...
    @property
    def AppInfo(self) -> AppInfo: ...
    @property
    def Id(self) -> int: ...
    @property
    def CreationTime(self) -> object: ...
