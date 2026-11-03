"""Validated observations for the toolbar's quiet resting presentation."""

from dataclasses import dataclass
from typing import assert_never

from winapi.machine_status import Battery, Power, PowerUnavailable, Speakers, Wifi


@dataclass(frozen=True, slots=True)
class SystemStatus:
    speakers: Speakers = Speakers.UNKNOWN
    wifi: Wifi = Wifi.UNKNOWN

    @property
    def speaker_icon(self) -> str:
        match self.speakers:
            case Speakers.AUDIBLE:
                return "speaker-on"
            case Speakers.MUTED:
                return "speaker-muted"
            case Speakers.UNKNOWN:
                return "speaker-unknown"
            case _:
                assert_never(self.speakers)

    @property
    def speaker_description(self) -> str:
        match self.speakers:
            case Speakers.AUDIBLE:
                return "Speakers unmuted"
            case Speakers.MUTED:
                return "Speakers muted"
            case Speakers.UNKNOWN:
                return "Speaker status unavailable"
            case _:
                assert_never(self.speakers)

    @property
    def wifi_icon(self) -> str:
        match self.wifi:
            case Wifi.CONNECTED:
                return "wifi"
            case Wifi.DISCONNECTED:
                return "wifi-off"
            case Wifi.NO_ADAPTER:
                return "wifi-absent"
            case Wifi.UNKNOWN:
                return "wifi-unknown"
            case _:
                assert_never(self.wifi)

    @property
    def wifi_description(self) -> str:
        match self.wifi:
            case Wifi.CONNECTED:
                return "Wi-Fi connected"
            case Wifi.DISCONNECTED:
                return "Wi-Fi disconnected"
            case Wifi.NO_ADAPTER:
                return "No Wi-Fi adapter"
            case Wifi.UNKNOWN:
                return "Wi-Fi status unavailable"
            case _:
                assert_never(self.wifi)

    @property
    def description(self) -> str:
        return self.speaker_description + ". " + self.wifi_description


@dataclass(frozen=True, slots=True)
class Ambient:
    clock: str
    power: Power

    @property
    def battery_text(self) -> str:
        match self.power:
            case Battery(percent=percent, powered=True) if percent > 95:
                return ""
            case Battery(percent=percent):
                return f"{percent}%"
            case PowerUnavailable.NO_BATTERY:
                return "AC"
            case PowerUnavailable.UNKNOWN:
                return "—"
            case _:
                assert_never(self.power)

    @property
    def text(self) -> str:
        facts = (self.clock, self.battery_text)
        return "  ·  ".join(value for value in facts if value)
