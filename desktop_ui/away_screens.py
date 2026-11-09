"""Dark external screens while nobody is looking at them, so a still image can't burn into an OLED.

The keyboard's backlight (`desktop_ui.keyboard_light`) and the laptop's own
panel (`desktop_ui.laptop_panel`, dimmed to brightness 0) go dark and come back
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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Final

from cell import Cell
from config import DARK_WHEN_IDLE_MINUTES
from desktop_ui.keyboard_light import KeyboardLight, ViaBacklight
from desktop_ui.laptop_panel import LaptopPanel, WmiBrightness
from desktop_ui.window_layout import dark_when_away
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


class Change(Enum):
    """What the screens should do as the first reason begins or the last one ends."""

    DARKEN = auto()
    RESTORE = auto()


def reason(observed: Presence, setting: Setting) -> Reason | None:
    """Why the protected screens should be dark now; None when they should be lit."""
    if not setting.enabled:
        return None
    if observed.locked:
        return Reason.LOCKED
    if observed.idle_ms >= setting.delay_ms and not observed.display_required:
        return Reason.IDLE
    return None


def step(held: Reason | None, observed: Presence, setting: Setting) -> tuple[Reason | None, Change | None]:
    """The reason that holds now, and the change to make: only when the first reason begins or the last one ends.

    A refused request isn't retried each poll, which would cost about 65 ms of the
    bar's thread every 100 ms; it is retried at the next edge."""
    current = reason(observed, setting)
    match held, current:
        case None, Reason():
            return current, Change.DARKEN
        case Reason(), None:
            return current, Change.RESTORE
        case _:
            return current, None


def dark_after(dark: frozenset[Monitor], applied: Mapping[Monitor, Applied]) -> frozenset[Monitor]:
    """The monitors left dark by this owner: those it turned off, until it turns them on again.

    A refused request changes nothing, so a failed restore is tried again."""
    off = frozenset(monitor for monitor, result in applied.items() if result is Power.OFF)
    on = frozenset(monitor for monitor, result in applied.items() if result is Power.ON)
    return (dark | off) - on


def set_power(sources: Sequence[PhysicalMonitors], monitor: Monitor, wanted: Power) -> Applied:
    """The first source whose handles carry the request; the last refusal otherwise."""
    result: Applied = Detached()
    for source in sources:
        result = source.set_power(monitor, wanted)
        if result is wanted:
            return result
    return result


@dataclass(frozen=True, slots=True)
class _Away:
    """What the screens, the keyboard's light and the laptop's panel are doing, and why."""

    light: KeyboardLight
    """The keyboard's backlight, dark exactly while the screens are."""
    panel: LaptopPanel
    """The laptop's own panel, at brightness 0 exactly while the screens are dark."""
    kept: PhysicalMonitors
    """Handles opened while unlocked, used when opening fails during a lock."""
    locked: bool
    setting: Setting = Setting(DELAY_MS, enabled=True)
    held: Reason | None = None
    recording: bool = False
    dark: frozenset[Monitor] = frozenset()


@dataclass(frozen=True, slots=True)
class AwayScreens:
    """Owns the darkened screens across lock, unlock, idleness and input, on the bar's thread.

    Lock and unlock arrive as session messages; idleness is polled on the bar's
    100 ms observation tick, not its frame loop. Each DDC/CI request took about
    65 ms on the home 4K screen, so only a darken or restore edge costs one
    request per protected screen on that thread."""

    _state: Cell[_Away]
    """Replaced whole on the bar's thread."""

    @classmethod
    def start(cls) -> AwayScreens:
        """Started, or restarted after a crash, behind the lock screen as well as in front of it."""
        away = _Away(
            KeyboardLight(ViaBacklight()),
            LaptopPanel(WmiBrightness()),
            PhysicalMonitors.open(),
            locked=session.locked() is True,
        )
        screens = cls(Cell(away))
        screens.settle()
        return screens

    @property
    def setting(self) -> Setting:
        return self._state.get().setting

    def message(self, message: int, wparam: int) -> None:
        if message == session.WM_DISPLAYCHANGE:
            away = self._state.get()
            away.kept.close()
            # A panel that refused while the lid was closed is back.
            panel = away.panel.restore() if away.held is None else away.panel
            self._state.set(replace(away, kept=PhysicalMonitors.open(), panel=panel))
        match session.change(message, wparam):
            case session.Change.LOCKED:
                self._state.update(lambda away: replace(away, locked=True))
                self.settle()
            case session.Change.UNLOCKED:
                self._state.update(lambda away: replace(away, locked=False))
                self.settle()
            case None:
                pass

    def poll(self, *, recording: bool) -> None:
        self._state.update(lambda away: replace(away, recording=recording))
        self.settle()

    def toggle(self) -> None:
        self._state.update(lambda away: replace(away, setting=replace(away.setting, enabled=not away.setting.enabled)))
        self.settle()

    def settle(self) -> None:
        away = self._state.get()
        observed = Presence(presence.idle_ms(), locked=away.locked, display_required=away.recording or presence.display_required())
        held, change = step(away.held, observed, away.setting)
        self._state.set(replace(away, held=held))
        match change:
            case Change.DARKEN:
                protected = dark_when_away(screen.monitors())
                self.apply(protected - away.dark, Power.OFF)
                self._state.update(lambda current: replace(current, light=current.light.darken(), panel=current.panel.darken()))
            case Change.RESTORE:
                self.apply(away.dark, Power.ON)
                self._state.update(lambda current: replace(current, light=current.light.restore(), panel=current.panel.restore()))
            case None:
                pass

    def apply(self, monitors: frozenset[Monitor], wanted: Power) -> None:
        if not monitors:
            return
        fresh = PhysicalMonitors.open()
        try:
            powered = frozendict((monitor, set_power((fresh, self._state.get().kept), monitor, wanted)) for monitor in monitors)
        finally:
            fresh.close()
        self._state.update(lambda away: replace(away, dark=dark_after(away.dark, powered)))

    def close(self) -> None:
        """Workspace leaving while away turns the screens back on rather than leaving them dark."""
        self.apply(self._state.get().dark, Power.ON)
        away = self._state.update(lambda current: replace(current, light=current.light.restore(), panel=current.panel.restore()))
        away.kept.close()
