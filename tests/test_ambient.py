"""Real ambient observations, including unavailable devices and weather."""

import unittest

from assistant.ambient import Ambient, Battery, PowerUnavailable, Speakers, SystemStatus, Weather, Wifi
from assistant.bar_weather import weather_response


def test_idle_facts_have_time_and_real_battery_or_explicit_unavailability() -> None:
    assert Ambient("09:41", Battery(73, False, False)).text == "09:41  ·  73%"
    assert Ambient("09:41", PowerUnavailable.NO_BATTERY).battery_text == "AC"
    assert Ambient("09:41", PowerUnavailable.UNKNOWN).battery_text == "—"
    assert Ambient("09:41", Battery(100, True, False), Weather(-3.2, 71, True)).text == "09:41  ·  100%  ·  -3°"


def test_weather_uses_current_temperature_and_day_or_night_conditions() -> None:
    weather = weather_response({"current": {"temperature_2m": 12.4, "weather_code": 0, "is_day": 0}})
    assert weather.text == "12°" and weather.icon == "moon"
    assert Weather(12, 0, True).icon == "sun"
    assert Weather(12, 3, True).icon == "cloud"
    assert Weather(12, 61, True).icon == "rain"
    assert Weather(12, 95, True).icon == "storm"


def test_invalid_weather_and_battery_are_not_presented_as_real_observations() -> None:
    invalid: tuple[object, ...] = (None, [], {}, {"current": {}},
                                {"current": {"temperature_2m": True, "weather_code": 0, "is_day": 1}},
                                {"current": {"temperature_2m": float("nan"), "weather_code": 0, "is_day": 1}},
                                {"current": {"temperature_2m": 12, "weather_code": 0, "is_day": 2}})
    for raw in invalid:
        with unittest.TestCase().assertRaises(ValueError):
            weather_response(raw)
    for percent in (-1, 101, 255):
        with unittest.TestCase().assertRaises(ValueError):
            Battery(percent, False, False)


def test_only_unmuted_speakers_and_disconnected_wifi_create_status_icons() -> None:
    assert SystemStatus(Speakers.MUTED, Wifi.CONNECTED).alerts == ()
    assert SystemStatus(Speakers.UNKNOWN, Wifi.UNKNOWN).alerts == ()
    assert SystemStatus(Speakers.MUTED, Wifi.NO_ADAPTER).alerts == ()
    status = SystemStatus(Speakers.AUDIBLE, Wifi.DISCONNECTED)
    assert status.alerts == ("speaker-on", "wifi-off")
    assert status.description == "Speakers unmuted. Wi-Fi disconnected"
