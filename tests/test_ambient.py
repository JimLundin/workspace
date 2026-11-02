"""Real ambient observations, including unavailable devices."""

import unittest

from desktop_ui.ambient import Ambient, SystemStatus
from winapi.machine_status import Battery, PowerUnavailable, Speakers, Wifi


def test_idle_facts_have_time_and_real_battery_or_explicit_unavailability() -> None:
    assert Ambient("09:41", Battery(73, powered=False, charging=False)).text == "09:41  ·  73%"
    assert Ambient("09:41", PowerUnavailable.NO_BATTERY).battery_text == "AC"
    assert Ambient("09:41", PowerUnavailable.UNKNOWN).battery_text == "—"


def test_only_plugged_in_batteries_above_95_hide_the_percentage() -> None:
    # Defects: hiding at 95%, using charging instead of external power, or hiding
    # a full battery after unplugging; empty facts must not leave a separator.
    for percent, powered, charging, expected in ((95, True, True, "95%"), (96, True, True, ""), (100, True, False, ""), (100, False, False, "100%")):
        ambient = Ambient("09:41", Battery(percent, powered=powered, charging=charging))
        assert ambient.battery_text == expected
        assert ambient.text == "09:41" + ("  ·  " + expected if expected else "")


def test_invalid_battery_is_not_presented_as_a_real_observation() -> None:
    for percent in (-1, 101, 255):
        with unittest.TestCase().assertRaises(ValueError):
            Battery(percent, powered=False, charging=False)


def test_only_unmuted_speakers_and_disconnected_wifi_create_status_icons() -> None:
    assert SystemStatus(Speakers.MUTED, Wifi.CONNECTED).alerts == ()
    assert SystemStatus(Speakers.UNKNOWN, Wifi.UNKNOWN).alerts == ()
    assert SystemStatus(Speakers.MUTED, Wifi.NO_ADAPTER).alerts == ()
    status = SystemStatus(Speakers.AUDIBLE, Wifi.DISCONNECTED)
    assert status.alerts == ("speaker-on", "wifi-off")
    assert status.description == "Speakers unmuted. Wi-Fi disconnected"
