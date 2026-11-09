"""Real ambient observations, including unavailable devices."""

import unittest

from win32more.Windows.Win32.System.Power import SYSTEM_POWER_STATUS

from desktop_ui.ambient import Ambient
from winapi import ambient, system_status
from winapi.machine_status import Battery, CpuTimes, PowerUnavailable, Wifi, cpu_load


def test_idle_facts_have_time_and_real_battery_or_explicit_unavailability() -> None:
    assert Ambient("09:41", Battery(73, powered=False, charging=False)).text == "09:41  ·  73%"
    assert Ambient("09:41", PowerUnavailable.NO_BATTERY).battery_text == "AC"
    assert Ambient("09:41", PowerUnavailable.UNKNOWN).battery_text == "—"


def test_battery_percentage_remains_visible_when_plugged_in_or_full() -> None:
    # Defect: external power or a full battery hides the requested percentage.
    for percent in (0, 73, 95, 96, 100):
        for powered, charging in ((True, True), (True, False), (False, False)):
            ambient = Ambient("09:41", Battery(percent, powered=powered, charging=charging))
            assert ambient.battery_text == f"{percent}%"
            assert ambient.text == f"09:41  ·  {percent}%"


def test_invalid_battery_is_not_presented_as_a_real_observation() -> None:
    for percent in (-1, 101, 255):
        with unittest.TestCase().assertRaises(ValueError):
            Battery(percent, powered=False, charging=False)


def test_processor_load_is_the_busy_share_of_time_between_two_samples() -> None:
    # Defects: kernel time is counted as busy although it includes idle time, the
    # load comes from cumulative totals instead of the interval, or a first
    # sample, a stalled counter or a counter that went backwards reads as 0%.
    before = CpuTimes(idle=1_000, kernel=5_000, user=3_000)
    assert cpu_load(before, CpuTimes(idle=1_600, kernel=5_800, user=3_200)) == 40
    assert cpu_load(before, CpuTimes(idle=2_000, kernel=6_000, user=3_000)) == 0
    assert cpu_load(before, CpuTimes(idle=1_000, kernel=5_500, user=3_500)) == 100
    assert cpu_load(None, before) is None
    assert cpu_load(before, None) is None
    assert cpu_load(before, before) is None
    assert cpu_load(before, CpuTimes(idle=500, kernel=4_000, user=3_000)) is None
    assert cpu_load(before, CpuTimes(idle=2_000, kernel=5_500, user=3_000)) is None


def test_native_power_validates_missing_and_unknown_batteries() -> None:
    status = SYSTEM_POWER_STATUS()
    status.ACLineStatus, status.BatteryFlag, status.BatteryLifePercent = 1, 8, 73
    assert ambient.power_from_status(status) == Battery(73, powered=True, charging=True)
    status.BatteryFlag = 128
    assert ambient.power_from_status(status) is PowerUnavailable.NO_BATTERY
    status.BatteryFlag = 255
    assert ambient.power_from_status(status) is PowerUnavailable.UNKNOWN
    status.BatteryFlag, status.BatteryLifePercent = 0, 255
    assert ambient.power_from_status(status) is PowerUnavailable.UNKNOWN
    assert ambient.power_from_status(None) is PowerUnavailable.UNKNOWN


def test_wifi_association_uses_all_interfaces_without_claiming_unknown_or_absent_adapters_are_disconnected() -> None:
    assert system_status.wifi_state(()) is Wifi.NO_ADAPTER
    assert system_status.wifi_state((4,)) is Wifi.DISCONNECTED
    assert system_status.wifi_state((0, 5, 7)) is Wifi.DISCONNECTED
    assert system_status.wifi_state((4, 1)) is Wifi.CONNECTED
    assert system_status.wifi_state((2,)) is Wifi.CONNECTED
    assert system_status.wifi_state((99,)) is Wifi.UNKNOWN
