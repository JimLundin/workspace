from dataclasses import dataclass, field, replace
from datetime import date

from winapi.machine_status import AppUse, Listing, Memory, Power, Speakers, Wifi


@dataclass(frozen=True, slots=True)
class Reading:
    icon: str
    description: str


@dataclass(frozen=True, slots=True)
class History:
    samples: tuple[int | None, ...] = ()
    capacity: int = 60
    """Two minutes of samples two seconds apart."""

    def added(self, sample: int | None) -> History:
        return replace(self, samples=(*self.samples, sample)[-self.capacity :])


@dataclass(frozen=True, slots=True)
class SystemStatus:
    speakers: Speakers = Speakers.UNKNOWN
    wifi: Wifi = Wifi.UNKNOWN
    volume: float | None = None
    cpu: int | None = None
    memory: Memory | None = None
    cpu_history: History = field(default_factory=History)
    """The processor's percentages."""
    memory_history: History = field(default_factory=History)
    """Memory in use, in bytes."""
    networks: Listing = ()
    """The Wi-Fi networks in range, read only while their panel is open."""
    apps: tuple[AppUse, ...] = ()
    """What each app uses: read every two seconds while a panel shows it, every half minute otherwise."""
    processors: int = 1
    """Logical processors: an app busy on all of them uses the whole machine."""


@dataclass(frozen=True, slots=True)
class Ambient:
    clock: str
    power: Power
    today: date | None = field(default=None, kw_only=True)
    """The local date the clock reads; None before the first tick."""
