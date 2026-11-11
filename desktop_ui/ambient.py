"""Validated observations for the toolbar's quiet resting presentation."""

from dataclasses import dataclass, field, replace
from datetime import date

from winapi.machine_status import Listing, Memory, Power, Speakers, Wifi


@dataclass(frozen=True, slots=True)
class Reading:
    """An observed state's toolbar icon and the words that describe it."""

    icon: str
    description: str


@dataclass(frozen=True, slots=True)
class History:
    """A reading's latest samples, oldest first; None where one couldn't be read."""

    samples: tuple[int | None, ...] = ()
    capacity: int = 60
    """Two minutes of samples two seconds apart."""

    def added(self, sample: int | None) -> History:
        """The history with `sample` the newest, the oldest dropped past capacity."""
        return replace(self, samples=(*self.samples, sample)[-self.capacity :])


@dataclass(frozen=True, slots=True)
class SystemStatus:
    speakers: Speakers = Speakers.UNKNOWN
    wifi: Wifi = Wifi.UNKNOWN
    volume: float | None = None  # The speakers' master level, from 0 to 1.
    cpu: int | None = None  # Busy processor time since the previous sample, in percent.
    memory: Memory | None = None
    cpu_history: History = field(default_factory=History)
    """The processor's percentages."""
    memory_history: History = field(default_factory=History)
    """Memory in use, in bytes."""
    networks: Listing = ()
    """The Wi-Fi networks in range, read only while their panel is open."""


@dataclass(frozen=True, slots=True)
class Ambient:
    clock: str
    power: Power
    today: date | None = field(default=None, kw_only=True)
    """The local date the clock reads; None before the first tick."""
