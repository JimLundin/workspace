"""Validated observations for the toolbar's quiet resting presentation."""

from dataclasses import dataclass

from winapi.machine_status import Power, Speakers, Wifi


@dataclass(frozen=True, slots=True)
class Reading:
    """An observed state's toolbar icon and the words that describe it."""

    icon: str
    description: str


@dataclass(frozen=True, slots=True)
class SystemStatus:
    speakers: Speakers = Speakers.UNKNOWN
    wifi: Wifi = Wifi.UNKNOWN
    volume: float | None = None  # The speakers' master level, from 0 to 1.
    cpu: int | None = None  # Busy processor time since the previous sample, in percent.
    memory: int | None = None  # Physical memory in use, in percent.


@dataclass(frozen=True, slots=True)
class Ambient:
    clock: str
    power: Power
