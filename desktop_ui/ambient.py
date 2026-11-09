"""Validated observations for the toolbar's quiet resting presentation."""

from dataclasses import dataclass
from typing import Final, assert_never

from contracts.members import every_member
from winapi.machine_status import Battery, Power, PowerUnavailable, Speakers, Wifi


@dataclass(frozen=True, slots=True)
class Reading:
    """An observed state's toolbar icon and the words that describe it."""

    icon: str
    description: str


SPEAKERS: Final = every_member(
    Speakers,
    {
        Speakers.AUDIBLE: Reading("speaker-on", "Speakers unmuted"),
        Speakers.MUTED: Reading("speaker-muted", "Speakers muted"),
        Speakers.UNKNOWN: Reading("speaker-unknown", "Speaker status unavailable"),
    },
)
WIFI: Final = every_member(
    Wifi,
    {
        Wifi.CONNECTED: Reading("wifi", "Wi-Fi connected"),
        Wifi.DISCONNECTED: Reading("wifi-off", "Wi-Fi disconnected"),
        Wifi.NO_ADAPTER: Reading("wifi-absent", "No Wi-Fi adapter"),
        Wifi.UNKNOWN: Reading("wifi-unknown", "Wi-Fi status unavailable"),
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
