from win32more._win32 import ComPtr
from win32more.Windows.Foundation import IAsyncAction

class DispatcherQueueController(ComPtr):
    def ShutdownQueueAsync(self) -> IAsyncAction: ...
