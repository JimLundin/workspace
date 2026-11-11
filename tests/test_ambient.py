"""Real ambient observations, including unavailable devices."""

import unittest
from dataclasses import replace

from win32more.Windows.Win32.System.Power import SYSTEM_POWER_STATUS

from desktop_ui.ambient import Ambient
from desktop_ui.island_model import Reading, battery_text, tip
from tests import test_island_model
from winapi import ambient, system_status
from winapi.machine_status import Battery, CpuTimes, Network, PowerUnavailable, Wifi, cpu_load, nearby


def test_battery_percentage_remains_visible_when_plugged_in_or_full() -> None:
    # Defect: external power or a full battery hides the requested percentage.
    for percent in (0, 73, 95, 96, 100):
        for powered, charging in ((True, True), (True, False), (False, False)):
            observed = Ambient("09:41", Battery(percent, powered=powered, charging=charging))
            shown = battery_text(observed, test_island_model.SPEC.status)
            said = tip(Reading.BATTERY, replace(test_island_model.RESTING, ambient=observed), test_island_model.SPEC)
            assert str(percent) in shown and shown in said


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
    status.ACLineStatus, status.BatteryFlag, status.BatteryLifePercent, status.BatteryLifeTime = 1, 8, 73, 5_000
    assert ambient.power_from_status(status) == Battery(73, powered=True, charging=True)
    # Defects: Windows' all-ones "unknown" estimate reads as 136 years left, or a real one is dropped.
    status.ACLineStatus, status.BatteryFlag = 0, 0
    assert ambient.power_from_status(status) == Battery(73, powered=False, charging=False, remaining=5_000)
    status.BatteryLifeTime = 0xFFFFFFFF
    assert ambient.power_from_status(status) == Battery(73, powered=False, charging=False)
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


def test_networks_merge_by_name_keep_a_saved_profile_and_list_the_connected_one_first() -> None:
    # Defects: a network heard on two bands, or once with its profile and once without,
    # lists twice; the merge loses the profile or the connection; or a hidden network
    # shows as a nameless line.
    heard = (
        Network("Cafe", 90, secured=False, connected=False, profile=None),
        Network("Home", 40, secured=True, connected=False, profile=None),
        Network("Home", 60, secured=True, connected=True, profile="Home"),
        Network("", 99, secured=True, connected=False, profile=None),
        Network("Office", 70, secured=True, connected=False, profile="Office"),
    )
    listed = nearby(heard)
    assert [each.ssid for each in listed] == ["Home", "Cafe", "Office"]
    home, *_ = listed
    assert home == Network("Home", 60, secured=True, connected=True, profile="Home")
