"""Windows input layouts, selected without changing the user's installed languages."""

import ctypes
import os
import winreg
from ctypes import wintypes

from ._core import fn, user32

_LoadKeyboardLayout = fn(user32, "LoadKeyboardLayoutW", wintypes.HANDLE, wintypes.LPCWSTR, wintypes.UINT)
_ActivateKeyboardLayout = fn(user32, "ActivateKeyboardLayout", wintypes.HANDLE, wintypes.HANDLE, wintypes.UINT)
_GetKeyboardLayout = fn(user32, "GetKeyboardLayout", wintypes.HANDLE, wintypes.DWORD)
_GetForegroundWindow = fn(user32, "GetForegroundWindow", wintypes.HWND)
_GetWindowThreadProcessId = fn(user32, "GetWindowThreadProcessId", wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
_PostMessage = fn(user32, "PostMessageW", wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


def _values(path: str) -> tuple[str, ...]:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
        return tuple(str(winreg.EnumValue(key, index)[1]) for index in range(winreg.QueryInfoKey(key)[1]))


def colemak_layout() -> str:
    """Prefer the configured Colemak variant, including Windows substitute IDs."""
    override = os.environ.get("WORKSPACE_COLEMAK_LAYOUT")
    candidates = (override,) if override else _values(r"Keyboard Layout\Preload")
    for candidate in candidates:
        identity = candidate
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Keyboard Layout\Substitutes") as key:
                identity = str(winreg.QueryValueEx(key, candidate)[0])
        except FileNotFoundError:
            pass
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "SYSTEM\\CurrentControlSet\\Control\\Keyboard Layouts\\" + identity) as key:
                name = str(winreg.QueryValueEx(key, "Layout Text")[0])
            if "colemak" in name.casefold():
                return candidate
        except FileNotFoundError:
            continue
    raise OSError("No configured Colemak keyboard was found. Set WORKSPACE_COLEMAK_LAYOUT to its installed Windows layout ID.")


class KeyboardLanguages:
    """Run on the layout's message-loop timer, never in a keyboard-hook callback."""

    __slots__ = ("colemak", "enabled", "english")

    def __init__(self) -> None:
        self.english = int(_LoadKeyboardLayout("00000409", 0x82) or 0)
        self.colemak = int(_LoadKeyboardLayout(colemak_layout(), 0x82) or 0)
        if not self.english or not self.colemak:
            raise OSError("Windows could not load the English and Colemak keyboards.")
        self.enabled: bool | None = None

    def enforce(self, enabled: bool) -> None:
        target = self.english if enabled else self.colemak
        if self.enabled != enabled:
            if not _ActivateKeyboardLayout(target, 0):
                raise OSError("Windows refused to activate the requested input keyboard.")
            self.enabled = enabled
        hwnd = _GetForegroundWindow()
        if hwnd:
            thread = _GetWindowThreadProcessId(hwnd, None)
            if int(_GetKeyboardLayout(thread) or 0) != target and not _PostMessage(hwnd, 0x0050, 0, target):
                raise OSError("The foreground application refused the keyboard-language request.")

    def close(self) -> None:
        self.enforce(False)
