"""Lease Windows' per-app banner setting while Workspace mirrors Notification Center."""

import winreg
from contextlib import suppress
from dataclasses import dataclass

SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings"
BACKUP = r"Software\Workspace\NotificationBannerLease"
ABSENT = 2


def names(key: winreg.HKEYType) -> tuple[str, ...]:
    return tuple(winreg.EnumKey(key, index) for index in range(min(1024, winreg.QueryInfoKey(key)[0])))


def setting(key: winreg.HKEYType, name: str) -> int:
    try:
        value, kind = winreg.QueryValueEx(key, name)
    except FileNotFoundError:
        return ABSENT
    allowed = (0, 1, ABSENT) if name == "Original" else (0, 1)
    if kind != winreg.REG_DWORD or not isinstance(value, int) or value not in allowed:
        raise OSError("Windows returned an unsupported notification banner setting.")
    return value


@dataclass(frozen=True, slots=True)
class Coverage:
    changed: int
    unavailable: int


class BannerPolicy:
    """Back up before changing banners; retain delivery, sound and center settings.

    The registry journal survives a crash or reload. Restoration touches only a
    value still held at zero by this lease, preserving later external changes.
    """

    __slots__ = ("backup_path", "settings_path")

    def __init__(self, *, settings_path: str = SETTINGS, backup_path: str = BACKUP) -> None:
        self.settings_path, self.backup_path = settings_path, backup_path

    def sync(self) -> Coverage:
        count = unavailable = 0
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.settings_path) as root:
            sources = names(root)
            unavailable = max(0, winreg.QueryInfoKey(root)[0] - len(sources))
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.backup_path) as journal:
            for source in sources:
                try:
                    count += self.suppress(source, journal)
                except OSError:
                    unavailable += 1
        return Coverage(count, unavailable)

    def suppress(self, source: str, journal: winreg.HKEYType) -> int:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.settings_path + "\\" + source, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as app:
            current = setting(app, "ShowBanner")
            if current == 0:
                return 0
            with winreg.CreateKey(journal, source) as saved:
                try:
                    winreg.QueryValueEx(saved, "Original")
                except FileNotFoundError:
                    winreg.SetValueEx(saved, "Original", 0, winreg.REG_DWORD, current)
            winreg.SetValueEx(app, "ShowBanner", 0, winreg.REG_DWORD, 0)
        return 1

    def close(self) -> None:
        try:
            journal = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.backup_path, 0, winreg.KEY_READ | winreg.KEY_WRITE)
        except FileNotFoundError:
            return
        with journal:
            for source in names(journal):
                with winreg.OpenKey(journal, source) as saved:
                    original = setting(saved, "Original")
                with (
                    suppress(FileNotFoundError),
                    winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.settings_path + "\\" + source, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as app,
                ):
                    if setting(app, "ShowBanner") == 0:
                        if original == ABSENT:
                            winreg.DeleteValue(app, "ShowBanner")
                        else:
                            winreg.SetValueEx(app, "ShowBanner", 0, winreg.REG_DWORD, original)
                winreg.DeleteKey(journal, source)
        with suppress(FileNotFoundError):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.backup_path)
