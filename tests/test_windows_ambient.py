"""Windows power observations distinguish charging, desktops and unknown readings."""

import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows power status")

from winapi import ambient, system_status
from winapi.machine_status import Battery, PowerUnavailable, Wifi


def test_native_power_validates_missing_and_unknown_batteries() -> None:
    status = ambient.PowerStatus()
    status.ac, status.flags, status.percent = 1, 8, 73
    assert ambient.power_from_status(status) == Battery(73, powered=True, charging=True)
    status.flags = 128
    assert ambient.power_from_status(status) is PowerUnavailable.NO_BATTERY
    status.flags = 255
    assert ambient.power_from_status(status) is PowerUnavailable.UNKNOWN
    status.flags, status.percent = 0, 255
    assert ambient.power_from_status(status) is PowerUnavailable.UNKNOWN
    assert ambient.power_from_status(None) is PowerUnavailable.UNKNOWN


def test_wifi_association_uses_all_interfaces_without_claiming_unknown_or_absent_adapters_are_disconnected() -> None:
    assert system_status.wifi_state(()) is Wifi.NO_ADAPTER
    assert system_status.wifi_state((4,)) is Wifi.DISCONNECTED
    assert system_status.wifi_state((0, 5, 7)) is Wifi.DISCONNECTED
    assert system_status.wifi_state((4, 1)) is Wifi.CONNECTED
    assert system_status.wifi_state((2,)) is Wifi.CONNECTED
    assert system_status.wifi_state((99,)) is Wifi.UNKNOWN
