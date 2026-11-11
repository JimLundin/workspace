"""Plain observations of the machine's speakers, Wi-Fi and its networks, power, processor and memory. No ctypes: importable anywhere."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum, auto
from itertools import groupby


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


@dataclass(frozen=True, slots=True)
class Network:
    """A Wi-Fi network in range: its name, signal from 0 to 100, and the profile Windows saved for it, if any."""

    ssid: str
    signal: int
    secured: bool = field(kw_only=True)
    connected: bool = field(kw_only=True)
    profile: str | None = field(kw_only=True)


LOCATION_OFF = sentinel("LOCATION_OFF")
"""Windows lists Wi-Fi networks to desktop apps only while location services are on for them."""

type Listing = tuple[Network, ...] | LOCATION_OFF


def nearby(heard: Iterable[Network]) -> tuple[Network, ...]:
    """One entry per name, as strong as its strongest sighting and keeping any saved profile:
    the connected network first, then by signal. Hidden networks, without a name, are left out."""

    def merged(ssid: str, sightings: tuple[Network, ...]) -> Network:
        profiles = (each.profile for each in sorted(sightings, key=lambda each: not each.connected) if each.profile is not None)
        return Network(
            ssid,
            max(each.signal for each in sightings),
            secured=any(each.secured for each in sightings),
            connected=any(each.connected for each in sightings),
            profile=next(profiles, None),
        )

    by_name = sorted((each for each in heard if each.ssid), key=lambda each: each.ssid)
    networks = (merged(ssid, tuple(group)) for ssid, group in groupby(by_name, key=lambda each: each.ssid))
    return tuple(sorted(networks, key=lambda each: (not each.connected, -each.signal, each.ssid)))


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
