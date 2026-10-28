"""Exercise Windows registry ownership without altering a user's notification settings."""

import sys
import unittest
import uuid

if sys.platform != "win32":
    raise unittest.SkipTest("Native notification banner settings")

import winreg

from winapi.notification_banners import ABSENT, BannerPolicy, names, setting


def remove(path: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            children = names(key)
    except FileNotFoundError:
        return
    for child in children:
        remove(path + "\\" + child)
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)


def test_banner_lease_preserves_delivery_restores_defaults_and_recovers_after_a_restart() -> None:
    base = r"Software\Workspace\Tests\NotificationBanners-" + uuid.uuid4().hex
    policy = BannerPolicy(settings_path=base + r"\Settings", backup_path=base + r"\Lease")
    try:
        for source, banner in (("Default", ABSENT), ("Enabled", 1), ("AlreadyQuiet", 0)):
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, policy.settings_path + "\\" + source) as app:
                winreg.SetValueEx(app, "Enabled", 0, winreg.REG_DWORD, 1)
                winreg.SetValueEx(app, "ShowInActionCenter", 0, winreg.REG_DWORD, 1)
                if banner != ABSENT:
                    winreg.SetValueEx(app, "ShowBanner", 0, winreg.REG_DWORD, banner)
        coverage = policy.sync()
        assert coverage.changed == 2 and coverage.unavailable == 0
        for source in ("Default", "Enabled", "AlreadyQuiet"):
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, policy.settings_path + "\\" + source) as app:
                assert setting(app, "ShowBanner") == 0
                assert setting(app, "Enabled") == 1 and setting(app, "ShowInActionCenter") == 1
        # A fresh observer inherits the original lease, including an absent value.
        restarted = BannerPolicy(settings_path=policy.settings_path, backup_path=policy.backup_path)
        assert restarted.sync().changed == 0
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, policy.settings_path + r"\NewSource"):
            pass
        assert restarted.sync().changed == 1
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, policy.settings_path + r"\Enabled", 0, winreg.KEY_SET_VALUE) as app:
            winreg.SetValueEx(app, "ShowBanner", 0, winreg.REG_DWORD, 1)  # Preserve a later external change on exit.
        restarted.close()
        for source, expected in (("Default", ABSENT), ("Enabled", 1), ("AlreadyQuiet", 0), ("NewSource", ABSENT)):
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, policy.settings_path + "\\" + source) as app:
                assert setting(app, "ShowBanner") == expected
        restarted.close()
    finally:
        remove(base)
