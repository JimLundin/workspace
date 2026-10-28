"""Observe the inherited test desktop without initializing the native SDK."""

import ctypes
from ctypes import wintypes


def current_name() -> str:
    # The child only needs three handle observations to verify its inherited
    # desktop. Loading the complete native SDK here makes Hypothesis inspect
    # those dependency sources before its pure generated cases can run.
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    thread = kernel.GetCurrentThreadId
    thread.argtypes, thread.restype = (), wintypes.DWORD
    desktop = user.GetThreadDesktop
    desktop.argtypes, desktop.restype = (wintypes.DWORD,), wintypes.HANDLE
    name = user.GetUserObjectInformationW
    name.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p)
    name.restype = wintypes.BOOL
    identity: object = thread()
    match identity:
        case int() as thread_id:
            pass
        case _:
            raise ValueError("Windows returned an invalid test thread identity")
    observed: object = desktop(thread_id)
    match observed:
        case int() as handle:
            pass
        case None:
            raise ctypes.WinError(ctypes.get_last_error())
        case _:
            raise ValueError("Windows returned an invalid test desktop handle")
    buffer = ctypes.create_unicode_buffer(256)
    result: object = name(handle, 2, ctypes.addressof(buffer), ctypes.sizeof(buffer), None)
    match result:
        case int() as status if status:
            pass
        case int():
            raise ctypes.WinError(ctypes.get_last_error())
        case _:
            raise ValueError("Windows returned an invalid desktop name status")
    return buffer.value
