"""Plain observations of the machine's speakers, Wi-Fi and its networks, power, processor and memory. No ctypes: importable anywhere."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum, auto
from itertools import groupby
from typing import Final

_TICKS_PER_SECOND: Final = (
    10_000_000  # Windows counts processor time in 100 ns units.
)


class Speakers(Enum):
    UNKNOWN = auto()
    AUDIBLE = auto()
    MUTED = auto()


@dataclass(frozen=True, slots=True)
class Audio:
    speakers: Speakers
    volume: float | None


class Wifi(Enum):
    UNKNOWN = auto()
    CONNECTED = auto()
    DISCONNECTED = auto()
    NO_ADAPTER = auto()


@dataclass(frozen=True, slots=True)
class Network:
    ssid: str
    signal: int
    secured: bool = field(kw_only=True)
    connected: bool = field(kw_only=True)
    profile: str | None = field(kw_only=True)


LOCATION_OFF = sentinel("LOCATION_OFF")
"""Windows lists Wi-Fi networks to desktop apps only while location services are on for them."""

type Listing = tuple[Network, ...] | LOCATION_OFF


def nearby(heard: Iterable[Network]) -> tuple[Network, ...]:

    def merged(ssid: str, sightings: tuple[Network, ...]) -> Network:
        profiles = (
            each.profile
            for each in sorted(sightings, key=lambda each: not each.connected)
            if each.profile is not None
        )
        return Network(
            ssid,
            max(each.signal for each in sightings),
            secured=any(each.secured for each in sightings),
            connected=any(each.connected for each in sightings),
            profile=next(profiles, None),
        )

    by_name = sorted(
        (each for each in heard if each.ssid), key=lambda each: each.ssid
    )
    networks = (
        merged(ssid, tuple(group))
        for ssid, group in groupby(by_name, key=lambda each: each.ssid)
    )
    return tuple(
        sorted(
            networks,
            key=lambda each: (not each.connected, -each.signal, each.ssid),
        )
    )


class PowerUnavailable(Enum):
    UNKNOWN = auto()
    NO_BATTERY = auto()


@dataclass(frozen=True, slots=True)
class Battery:
    percent: int
    powered: bool = field(kw_only=True)
    charging: bool = field(kw_only=True)
    remaining: int | None = field(default=None, kw_only=True)
    """Seconds of charge left on its own power, as Windows estimates them; None on mains or before an estimate."""

    def __post_init__(self) -> None:
        if not 0 <= self.percent <= 100:
            raise ValueError("Battery percentage must be between 0 and 100.")


type Power = Battery | PowerUnavailable


@dataclass(frozen=True, slots=True)
class CpuTimes:
    idle: int
    kernel: int
    user: int


@dataclass(frozen=True, slots=True)
class Memory:
    used: int
    total: int

    def __post_init__(self) -> None:
        if not 0 <= self.used <= self.total or self.total <= 0:
            raise ValueError(
                "Memory in use must be between none and all of it."
            )


def cpu_load(before: CpuTimes | None, after: CpuTimes | None) -> int | None:
    if before is None or after is None:
        return None
    idle = after.idle - before.idle
    total = (after.kernel - before.kernel) + (after.user - before.user)
    if total <= 0 or not 0 <= idle <= total:
        return None
    return round(100 * (total - idle) / total)


@dataclass(frozen=True, slots=True)
class ProcessUse:
    """A running process: its image name, private memory in bytes and cumulative processor time in 100 ns units."""

    pid: int
    name: str
    memory: int
    cpu: int


@dataclass(frozen=True, slots=True)
class ProcessSample:
    """Every running process at one moment, `taken` in seconds on a monotonic clock."""

    taken: float
    processes: tuple[ProcessUse, ...]


@dataclass(frozen=True, slots=True)
class AppUse:
    """An app's processes together: their private memory in bytes, and how many cores they kept busy since
    the previous sample, None without one."""

    name: str
    memory: int
    cores: float | None


def app_name(image: str) -> str:
    """The image's name without its `.exe`, as Task Manager's details read it."""
    return image[: -len(".exe")] if image.lower().endswith(".exe") else image


def apps(
    before: ProcessSample | None, after: ProcessSample
) -> Iterator[AppUse]:
    """`after`'s processes grouped by image name.

    A process keyed by its id and name, so one that ended and gave its id to another program, counts from
    nothing: whatever processor time it has, it spent since `before`, or since it started."""
    elapsed = after.taken - before.taken if before is not None else 0.0
    earlier = (
        frozendict(
            ((process.pid, process.name), process.cpu)
            for process in before.processes
        )
        if before is not None and elapsed > 0
        else None
    )
    named = sorted(after.processes, key=lambda process: process.name)
    for name, group in groupby(named, key=lambda process: process.name):
        members = tuple(group)
        yield AppUse(
            app_name(name),
            sum(process.memory for process in members),
            None
            if earlier is None
            else sum(
                max(
                    0, process.cpu - earlier.get((process.pid, process.name), 0)
                )
                for process in members
            )
            / _TICKS_PER_SECOND
            / elapsed,
        )
