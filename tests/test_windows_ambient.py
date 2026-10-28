"""Windows power observations distinguish charging, desktops and unknown readings."""

import ctypes
import sys
import unittest
from typing import cast
from unittest.mock import patch

if sys.platform != "win32":
    raise unittest.SkipTest("Windows power status")

from assistant.ambient import Battery, PowerUnavailable, Wifi
from winapi import ambient, system_status


def test_native_power_validates_missing_and_unknown_batteries() -> None:
    status = ambient.SYSTEM_POWER_STATUS()
    def observe(output: object) -> bool:
        ctypes.memmove(cast("ctypes.c_void_p", output), ctypes.byref(status), ctypes.sizeof(status))
        return True
    with patch.object(ambient, "_GetSystemPowerStatus", side_effect=observe):
        status.ac, status.flags, status.percent = 1, 8, 73
        assert ambient.power() == Battery(73, True, True)
        status.flags = 128
        assert ambient.power() is PowerUnavailable.NO_BATTERY
        status.flags = 255
        assert ambient.power() is PowerUnavailable.UNKNOWN
        status.flags, status.percent = 0, 255
        assert ambient.power() is PowerUnavailable.UNKNOWN
    with patch.object(ambient, "_GetSystemPowerStatus", return_value=False):
        assert ambient.power() is PowerUnavailable.UNKNOWN


def test_wifi_association_uses_all_interfaces_without_claiming_unknown_or_absent_adapters_are_disconnected() -> None:
    assert system_status.wifi_state(()) is Wifi.NO_ADAPTER
    assert system_status.wifi_state((4,)) is Wifi.DISCONNECTED
    assert system_status.wifi_state((0, 5, 7)) is Wifi.DISCONNECTED
    assert system_status.wifi_state((4, 1)) is Wifi.CONNECTED
    assert system_status.wifi_state((2,)) is Wifi.CONNECTED
    assert system_status.wifi_state((99,)) is Wifi.UNKNOWN
