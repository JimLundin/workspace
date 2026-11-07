"""Validated observations for the toolbar's quiet resting presentation."""

from dataclasses import dataclass
from typing import Final, assert_never

from contracts.members import every_member
from winapi.machine_status import Battery, Power, PowerUnavailable, Speakers, Wifi

SPEAKER_ICONS: Final = every_member(Speakers, {Speakers.AUDIBLE: "speaker-on", Speakers.MUTED: "speaker-muted", Speakers.UNKNOWN: "speaker-unknown"})
SPEAKER_DESCRIPTIONS: Final = every_member(
    Speakers,
    {Speakers.AUDIBLE: "Speakers unmuted", Speakers.MUTED: "Speakers muted", Speakers.UNKNOWN: "Speaker status unavailable"},
)
WIFI_ICONS: Final = every_member(
    Wifi, {Wifi.CONNECTED: "wifi", Wifi.DISCONNECTED: "wifi-off", Wifi.NO_ADAPTER: "wifi-absent", Wifi.UNKNOWN: "wifi-unknown"}
)
WIFI_DESCRIPTIONS: Final = every_member(
    Wifi,
    {
        Wifi.CONNECTED: "Wi-Fi connected",
        Wifi.DISCONNECTED: "Wi-Fi disconnected",
        Wifi.NO_ADAPTER: "No Wi-Fi adapter",
        Wifi.UNKNOWN: "Wi-Fi status unavailable",
    },
)


@dataclass(frozen=True, slots=True)
class SystemStatus:
    speakers: Speakers = Speakers.UNKNOWN
    wifi: Wifi = Wifi.UNKNOWN
    volume: float | None = None  # The speakers' master level, from 0 to 1.
    cpu: int | None = None  # Busy processor time since the previous sample, in percent.
    memory: int | None = None  # Physical memory in use, in percent.

    @property
    def speaker_icon(self) -> str:
        return SPEAKER_ICONS[self.speakers]

    @property
    def speaker_description(self) -> str:
        return SPEAKER_DESCRIPTIONS[self.speakers]

    @property
    def wifi_icon(self) -> str:
        return WIFI_ICONS[self.wifi]

    @property
    def wifi_description(self) -> str:
        return WIFI_DESCRIPTIONS[self.wifi]

    @property
    def description(self) -> str:
        return self.speaker_description + ". " + self.wifi_description

    @property
    def resource_description(self) -> str:
        cpu = "CPU unavailable" if self.cpu is None else f"CPU {self.cpu}%"
        memory = "memory unavailable" if self.memory is None else f"memory {self.memory}%"
        return cpu + ", " + memory


@dataclass(frozen=True, slots=True)
class Ambient:
    clock: str
    power: Power

    @property
    def battery_text(self) -> str:
        match self.power:
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
