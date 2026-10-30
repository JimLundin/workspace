def CreateWindowExW(
    extended_style: int,
    class_name: str,
    title: str,
    style: int,
    x: int,
    y: int,
    width: int,
    height: int,
    parent: int | None,
    menu: int | None,
    instance: int | None,
    parameter: None,
) -> int | None: ...
def SetWindowPos(hwnd: int, after: int, x: int, y: int, width: int, height: int, flags: int) -> int: ...
def GetWindow(hwnd: int, command: int) -> int | None: ...
def GetWindowThreadProcessId(hwnd: int, process_id: None) -> int: ...
