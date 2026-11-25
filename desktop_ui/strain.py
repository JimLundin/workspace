"""When the laptop strains: memory running low, or one app holding the processor.

The bar decides from each reading whether to warn, and the tray shows the warning.
Each warning is given once: low memory again only after memory has recovered past
a higher line, so a reading hovering at the line stays quiet; a busy app again only
after it has calmed down.
"""

from dataclasses import dataclass, field, replace
from typing import Final

from desktop_ui.ambient import SystemStatus
from desktop_ui.island_model import StatusSpec, gigabytes
from winapi.machine_status import AppUse

LARGEST: Final = (
    3  # Apps a low-memory warning names: enough to find the one to close.
)


@dataclass(frozen=True, slots=True)
class StrainSpec:
    """When the bar warns: under `low_memory` bytes available, and again only after more than `recovered`;
    and when one app has kept `busy_cores` processors busy for `busy_for` seconds."""

    low_memory: int
    recovered: int
    busy_cores: float
    busy_for: float

    def __post_init__(self) -> None:
        if not 0 < self.low_memory < self.recovered:
            raise ValueError(
                "Memory recovers above the line it runs low under."
            )
        if self.busy_cores <= 0 or self.busy_for <= 0:
            raise ValueError(
                "An app is busy for a while on some of a processor."
            )


@dataclass(frozen=True, slots=True)
class Watch:
    """What the warnings have seen."""

    memory_low: bool = False
    """Low memory was warned of, and memory hasn't recovered since."""
    ranked_at: float | None = None
    """When the apps last judged were read."""
    busy_since: frozendict[str, float] = field(default=frozendict())
    """Each busy app, by when it was first read busy in this stretch."""
    warned: frozenset[str] = frozenset()
    """The busy apps already warned of in this stretch."""


@dataclass(frozen=True, slots=True)
class Notice:
    title: str
    text: str


def _available(system: SystemStatus) -> int | None:
    memory = system.memory
    return memory.total - memory.used if memory is not None else None


def _largest(apps: tuple[AppUse, ...], status: StatusSpec) -> str:
    named = sorted(apps, key=lambda app: app.memory, reverse=True)[:LARGEST]
    return ", ".join(
        f"{app.name} {gigabytes(app.memory, status)}" for app in named
    )


def _memory(
    watch: Watch, system: SystemStatus, spec: StrainSpec, status: StatusSpec
) -> tuple[bool, tuple[Notice, ...]]:
    """Whether memory stays warned of as low, and the warning when it first runs low."""
    available = _available(system)
    if available is None:
        return watch.memory_low, ()
    low = available < spec.low_memory
    warned = (watch.memory_low or low) and available <= spec.recovered
    if not low or watch.memory_low:
        return warned, ()
    return warned, (
        Notice(
            "Memory is low",
            f"{gigabytes(available, status)} free. Largest: {_largest(system.apps, status)}",
        ),
    )


def watched(
    watch: Watch, system: SystemStatus, spec: StrainSpec, status: StatusSpec
) -> tuple[Watch, tuple[Notice, ...]]:
    """What the warnings have seen after `system`, and what to warn of now."""
    memory_low, memory = _memory(watch, system, spec, status)
    now = system.ranked_at
    if now is None or now == watch.ranked_at:
        return replace(watch, memory_low=memory_low), memory
    busy = {
        app.name: app
        for app in system.apps
        if app.cores is not None and app.cores >= spec.busy_cores
    }
    since = frozendict((name, watch.busy_since.get(name, now)) for name in busy)
    due = tuple(
        app
        for name, app in busy.items()
        if now - since[name] >= spec.busy_for and name not in watch.warned
    )
    processors = system.processors
    notices = (
        *memory,
        *(
            Notice(
                f"{app.name} is busy",
                f"It has used {app.cores or 0:.1f} of {processors} processors "
                f"for {round((now - since[app.name]) / 60)} minutes.",
            )
            for app in due
        ),
    )
    warned = frozenset(
        (
            *(name for name in watch.warned if name in busy),
            *(app.name for app in due),
        )
    )
    return Watch(memory_low, now, since, warned), notices
