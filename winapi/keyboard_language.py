"""Windows input layouts, selected without changing the user's installed languages."""

import ctypes
import os
import winreg
from ctypes import wintypes
from typing import Protocol

from winapi._core import fn, user32

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


class LanguageDesktop(Protocol):
    def load(self, identity: str) -> int: ...
    def colemak(self) -> str: ...
    def activate(self, layout: int) -> None: ...
    def foreground(self) -> tuple[int, int]: ...
    def request(self, hwnd: int, layout: int) -> None: ...


class NativeLanguageDesktop:
    """Adapt layout handles and foreground observations before language policy runs."""

    __slots__ = ()

    def load(self, identity: str) -> int:
        return int(_LoadKeyboardLayout(identity, 0x82) or 0)

    def colemak(self) -> str:
        return colemak_layout()

    def activate(self, layout: int) -> None:
        if not _ActivateKeyboardLayout(layout, 0):
            raise OSError("Windows refused to activate the requested input keyboard.")

    def foreground(self) -> tuple[int, int]:
        hwnd = int(_GetForegroundWindow() or 0)
        current = int(_GetKeyboardLayout(_GetWindowThreadProcessId(hwnd, None)) or 0) if hwnd else 0
        return hwnd, current

    def request(self, hwnd: int, layout: int) -> None:
        if not _PostMessage(hwnd, 0x0050, 0, layout):
            raise OSError("The foreground application refused the keyboard-language request.")


class KeyboardLanguages:
    """Run on the layout's message-loop timer, never in a keyboard-hook callback."""

    __slots__ = ("active", "colemak", "desktop", "english", "firmware_connected")

    def __init__(self, desktop: LanguageDesktop | None = None) -> None:
        self.desktop = desktop if desktop is not None else NativeLanguageDesktop()
        self.english = self.desktop.load("00000409")
        self.colemak = self.desktop.load(self.desktop.colemak())
        if not self.english or not self.colemak:
            raise OSError("Windows could not load the English and Colemak keyboards.")
        self.active: int | None = None
        self.firmware_connected: bool = False

    def enforce(self, *, enabled: bool, firmware_connected: bool = False) -> None:
        self.firmware_connected = firmware_connected
        target = self.english if enabled or firmware_connected else self.colemak
        if self.active != target:
            self.desktop.activate(target)
            self.active = target
        hwnd, current = self.desktop.foreground()
        if hwnd and current != target:
            self.desktop.request(hwnd, target)

    def close(self) -> None:
        self.enforce(enabled=False, firmware_connected=self.firmware_connected)
