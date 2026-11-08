"""Windows input layouts, selected without changing the user's installed languages."""

import os
import winreg
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Protocol

from cell import Cell
from winapi._core import GetForegroundWindow, GetWindowThreadProcessId, PostMessageW, fn, user32

_LoadKeyboardLayout = fn(user32, "LoadKeyboardLayoutW", wintypes.HANDLE, wintypes.LPCWSTR, wintypes.UINT)
_ActivateKeyboardLayout = fn(user32, "ActivateKeyboardLayout", wintypes.HANDLE, wintypes.HANDLE, wintypes.UINT)
_GetKeyboardLayout = fn(user32, "GetKeyboardLayout", wintypes.HANDLE, wintypes.DWORD)


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


@dataclass(frozen=True, slots=True)
class Foreground:
    """The foreground window, 0 when there is none, and the keyboard layout its thread uses."""

    window: int
    layout: int


class LanguageDesktop(Protocol):
    def load(self, identity: str) -> int: ...
    def colemak(self) -> str: ...
    def activate(self, layout: int) -> None: ...
    def foreground(self) -> Foreground: ...
    def request(self, hwnd: int, layout: int) -> None: ...


@dataclass(frozen=True, slots=True)
class NativeLanguageDesktop:
    """Adapt layout handles and foreground observations before language policy runs."""

    def load(self, identity: str) -> int:
        return int(_LoadKeyboardLayout(identity, 0x82) or 0)

    def colemak(self) -> str:
        return colemak_layout()

    def activate(self, layout: int) -> None:
        if not _ActivateKeyboardLayout(layout, 0):
            raise OSError("Windows refused to activate the requested input keyboard.")

    def foreground(self) -> Foreground:
        hwnd = int(GetForegroundWindow() or 0)
        return Foreground(hwnd, int(_GetKeyboardLayout(GetWindowThreadProcessId(hwnd, None)) or 0) if hwnd else 0)

    def request(self, hwnd: int, layout: int) -> None:
        if not PostMessageW(hwnd, 0x0050, 0, layout):
            raise OSError("The foreground application refused the keyboard-language request.")


@dataclass(frozen=True, slots=True)
class _Enforced:
    active: int | None = None
    firmware_connected: bool = field(default=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class KeyboardLanguages:
    """Run on the layout's message-loop timer, never in a keyboard-hook callback."""

    desktop: LanguageDesktop
    english: int
    colemak: int
    _enforced: Cell[_Enforced] = field(default_factory=lambda: Cell(_Enforced()), init=False, repr=False)

    @classmethod
    def load(cls, desktop: LanguageDesktop | None = None) -> KeyboardLanguages:
        desktop = desktop if desktop is not None else NativeLanguageDesktop()
        english, colemak = desktop.load("00000409"), desktop.load(desktop.colemak())
        if not english or not colemak:
            raise OSError("Windows could not load the English and Colemak keyboards.")
        return cls(desktop, english, colemak)

    @property
    def active(self) -> int | None:
        return self._enforced.get().active

    def enforce(self, *, enabled: bool, firmware_connected: bool = False) -> None:
        target = self.english if enabled or firmware_connected else self.colemak
        if self.active != target:
            self.desktop.activate(target)
        self._enforced.set(_Enforced(target, firmware_connected=firmware_connected))
        foreground = self.desktop.foreground()
        if foreground.window and foreground.layout != target:
            self.desktop.request(foreground.window, target)

    def close(self) -> None:
        self.enforce(enabled=False, firmware_connected=self._enforced.get().firmware_connected)
