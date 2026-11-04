"""Real ambient observations, including unavailable devices."""

import unittest

from desktop_ui.ambient import Ambient
from winapi.machine_status import Battery, PowerUnavailable


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
