import ctypes

def GetCurrentThreadId() -> int: ...
def GetCurrentProcess() -> int: ...
def ResumeThread(thread: int) -> int: ...

class STARTUPINFOW(ctypes.Structure):
    def __init__(self, *, cb: int, lpDesktop: str, dwFlags: int, hStdInput: int | None, hStdOutput: int | None, hStdError: int | None) -> None: ...

class PROCESS_INFORMATION(ctypes.Structure):
    hProcess: int
    hThread: int
    dwProcessId: int
    dwThreadId: int

def CreateProcessW(
    application: str,
    command: ctypes.Array[ctypes.c_wchar],
    process_security: None,
    thread_security: None,
    inherit: int,
    flags: int,
    environment: None,
    directory: None,
    startup: STARTUPINFOW,
    info: PROCESS_INFORMATION,
) -> int: ...
