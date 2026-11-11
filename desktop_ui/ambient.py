"""Validated observations for the toolbar's quiet resting presentation."""

from dataclasses import dataclass, field
from datetime import date

from winapi.machine_status import Memory, Power, Speakers, Wifi


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
    memory: Memory | None = None


@dataclass(frozen=True, slots=True)
class Ambient:
    clock: str
    power: Power
    today: date | None = field(default=None, kw_only=True)
    """The local date the clock reads; None before the first tick."""
