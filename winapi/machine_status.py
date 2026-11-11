"""Plain observations of the machine's speakers, Wi-Fi, power, processor and memory. No ctypes: importable anywhere."""

from dataclasses import dataclass, field
from enum import Enum, auto


class Speakers(Enum):
    UNKNOWN = auto()
    AUDIBLE = auto()
    MUTED = auto()


@dataclass(frozen=True, slots=True)
class Audio:
    """The default speakers: their mute state and master level from 0 to 1, None when Windows reports none."""

    speakers: Speakers
    volume: float | None


class Wifi(Enum):
    UNKNOWN = auto()
    CONNECTED = auto()
    DISCONNECTED = auto()
    NO_ADAPTER = auto()


class PowerUnavailable(Enum):
    UNKNOWN = auto()
    NO_BATTERY = auto()


@dataclass(frozen=True, slots=True)
class Battery:
    percent: int
    powered: bool = field(kw_only=True)
    charging: bool = field(kw_only=True)

    def __post_init__(self) -> None:
        if not 0 <= self.percent <= 100:
            raise ValueError("Battery percentage must be between 0 and 100.")


type Power = Battery | PowerUnavailable


@dataclass(frozen=True, slots=True)
class CpuTimes:
    """Cumulative processor time across all cores, in 100 ns units. Kernel time includes idle time."""

    idle: int
    kernel: int
    user: int


@dataclass(frozen=True, slots=True)
class Memory:
    """Physical memory in use and installed, in bytes."""

    used: int
    total: int

    def __post_init__(self) -> None:
        if not 0 <= self.used <= self.total or self.total <= 0:
            raise ValueError("Memory in use must be between none and all of it.")


def cpu_load(before: CpuTimes | None, after: CpuTimes | None) -> int | None:
    """The busy share of processor time between two samples, as a whole percent; None without a valid interval."""
    if before is None or after is None:
        return None
    idle = after.idle - before.idle
    total = (after.kernel - before.kernel) + (after.user - before.user)
    if total <= 0 or not 0 <= idle <= total:
        return None
    return round(100 * (total - idle) / total)
