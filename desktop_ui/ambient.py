"""Validated observations for the toolbar's quiet resting presentation."""

from dataclasses import dataclass
from typing import assert_never

from winapi.machine_status import Battery, Power, PowerUnavailable, Speakers, Wifi


@dataclass(frozen=True, slots=True)
class SystemStatus:
    speakers: Speakers = Speakers.UNKNOWN
    wifi: Wifi = Wifi.UNKNOWN

    @property
    def alerts(self) -> tuple[str, ...]:
        return (*(("speaker-on",) if self.speakers is Speakers.AUDIBLE else ()), *(("wifi-off",) if self.wifi is Wifi.DISCONNECTED else ()))

    @property
    def description(self) -> str:
        observations = (
            "Speakers unmuted" if self.speakers is Speakers.AUDIBLE else "",
            "Wi-Fi disconnected" if self.wifi is Wifi.DISCONNECTED else "",
        )
        return ". ".join(value for value in observations if value)


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
