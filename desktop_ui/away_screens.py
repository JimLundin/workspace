"""Dark external screens while nobody is looking at them, so a still image can't burn into an OLED.

The keyboard's backlight (`desktop_ui.keyboard_light`) goes dark and comes back
at the same moments, by the same rules and the same toggle.

A screen goes dark when the session locks or when no keyboard or mouse input has
arrived for the configured delay, and comes back once neither holds. A program
asking Windows to keep the display on, such as a video or a call, or a Workspace
meeting recording, holds off the idle darkening; the lock darkens regardless.

Windows can't change the display topology from a locked session
(SetDisplayConfig returns ERROR_ACCESS_DENIED), so the protected screens are
turned off over DDC/CI instead. Windows keeps driving them: the monitor count
and work areas stay the same and placement doesn't react. Only monitors this
owner turned off are turned back on.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Final

from config import DARK_WHEN_IDLE_MINUTES
from desktop_ui.keyboard_light import KeyboardLight, ViaBacklight
from desktop_ui.window_layout import dark_when_away
from usage import Detail
from winapi import presence, screen, session
from winapi.monitor_power import Applied, Detached, PhysicalMonitors, Power
from winapi.screen import Monitor


def idle_delay(minutes: int) -> int:
    """The settings' idle delay in milliseconds; whole minutes from 1 to 60."""
    if minutes not in range(1, 61):
        raise ValueError(f"DARK_WHEN_IDLE_MINUTES must be a whole number of minutes from 1 to 60, not {minutes!r}")
    return minutes * 60_000


DELAY_MS: Final = idle_delay(DARK_WHEN_IDLE_MINUTES)


class Reason(Enum):
    """Why the protected screens are dark; the lock comes first when both hold."""

    LOCKED = auto()
    IDLE = auto()


@dataclass(frozen=True, slots=True)
class Presence:
    """One reading of the session: input idleness, the lock, and whether something needs the display."""

    idle_ms: int
    locked: bool = field(kw_only=True)
    display_required: bool = field(kw_only=True)
    """A program asks Windows to keep the display on, or Workspace is recording a meeting."""


@dataclass(frozen=True, slots=True)
class Setting:
    """Dark when away as the person set it: the idle delay, and the controls-menu toggle."""

    delay_ms: int
    enabled: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Darken:
    reason: Reason


@dataclass(frozen=True, slots=True)
class Restore:
    reason: Reason
    """The last reason to stop holding."""


def reason(observed: Presence, setting: Setting) -> Reason | None:
    """Why the protected screens should be dark now; None when they should be lit."""
    if not setting.enabled:
        return None
    if observed.locked:
        return Reason.LOCKED
    if observed.idle_ms >= setting.delay_ms and not observed.display_required:
        return Reason.IDLE
    return None


def step(held: Reason | None, observed: Presence, setting: Setting) -> tuple[Reason | None, Darken | Restore | None]:
    """The reason that holds now, and the change to make: only when the first reason begins or the last one ends.

    A refused request isn't retried each poll, which would cost about 65 ms of the
    bar's thread every 100 ms; it is retried at the next edge."""
    current = reason(observed, setting)
    match held, current:
        case None, Reason() as begun:
            return current, Darken(begun)
        case Reason() as ended, None:
            return current, Restore(ended)
        case _:
            return current, None


def dark_after(dark: frozenset[Monitor], applied: Mapping[Monitor, Applied]) -> frozenset[Monitor]:
    """The monitors left dark by this owner: those it turned off, until it turns them on again.

    A refused request changes nothing, so a failed restore is tried again."""
    off = frozenset(monitor for monitor, result in applied.items() if result is Power.OFF)
    on = frozenset(monitor for monitor, result in applied.items() if result is Power.ON)
    return (dark | off) - on


def set_power(sources: Sequence[PhysicalMonitors], monitor: Monitor, wanted: Power) -> tuple[Applied, int]:
    """The first source whose handles carry the request, and its index; the last refusal otherwise."""
    result: Applied = Detached()
    for index, source in enumerate(sources):
        result = source.set_power(monitor, wanted)
        if result is wanted:
            return result, index
    return result, len(sources)


class AwayScreens:
    """Owns the darkened screens across lock, unlock, idleness and input, on the bar's thread.

    Lock and unlock arrive as session messages; idleness is polled on the bar's
    100 ms observation tick, not its frame loop. Each DDC/CI request took about
    65 ms on the home 4K screen, so only a darken or restore edge costs one
    request per protected screen on that thread."""

    __slots__ = ("dark", "held", "kept", "light", "locked", "record", "recording", "setting")

    def __init__(self, record: Callable[[str, Mapping[str, Detail]], None], light: KeyboardLight | None = None) -> None:
        self.record = record
        self.light = light if light is not None else KeyboardLight(ViaBacklight(), record)
        """The keyboard's backlight, dark exactly while the screens are."""
        self.setting = Setting(DELAY_MS, enabled=True)
        self.held: Reason | None = None
        self.recording = False
        self.dark: frozenset[Monitor] = frozenset()
        # Native ownership: handles opened while unlocked, used when opening fails during a lock.
        self.kept = PhysicalMonitors()
        # Started, or restarted after a crash, behind the lock screen.
        self.locked = session.locked() is True
        self.settle()

    def message(self, message: int, wparam: int) -> None:
        if message == session.WM_DISPLAYCHANGE:
            self.kept.close()
            self.kept = PhysicalMonitors()
        match session.change(message, wparam):
            case session.Change.LOCKED:
                self.locked = True
                self.settle()
            case session.Change.UNLOCKED:
                self.locked = False
                self.settle()
            case None:
                pass

    def poll(self, *, recording: bool) -> None:
        self.recording = recording
        self.settle()

    def toggle(self) -> None:
        self.setting = replace(self.setting, enabled=not self.setting.enabled)
        self.record("dark_when_away_toggle", {"enabled": self.setting.enabled})
        self.settle()

    def settle(self) -> None:
        observed = Presence(presence.idle_ms(), locked=self.locked, display_required=self.recording or presence.display_required())
        self.held, change = step(self.held, observed, self.setting)
        idle_seconds = observed.idle_ms // 1000
        match change:
            case Darken(reason=begun):
                protected = dark_when_away(screen.monitors())
                self.apply(protected - self.dark, Power.OFF, {"reason": begun.name.lower(), "idle_seconds": idle_seconds})
                self.light = self.light.darken()
            case Restore(reason=ended):
                self.apply(self.dark, Power.ON, {"reason": ended.name.lower(), "idle_seconds": idle_seconds})
                self.light = self.light.restore()
            case None:
                pass

    def apply(self, monitors: frozenset[Monitor], wanted: Power, cause: Mapping[str, Detail]) -> None:
        if not monitors:
            return
        fresh = PhysicalMonitors()
        try:
            results = frozendict((monitor, set_power((fresh, self.kept), monitor, wanted)) for monitor in monitors)
        finally:
            fresh.close()
        self.dark = dark_after(self.dark, frozendict((monitor, result) for monitor, (result, _) in results.items()))
        kept = sum(1 for _, source in results.values() if source == 1)
        ok = all(result is wanted for result, _ in results.values())
        self.record("dark_when_away", {"power": wanted.name.lower(), **cause, "screens": len(results), "kept_handles": kept, "ok": ok})

    def close(self) -> None:
        """Workspace leaving while away turns the screens back on rather than leaving them dark."""
        self.apply(self.dark, Power.ON, {"reason": "close"})
        self.light = self.light.restore()
        self.kept.close()
