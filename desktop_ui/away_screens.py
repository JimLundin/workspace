"""Dark external screens while the session is locked, so a still image can't burn into an OLED.

The keyboard's backlight (`desktop_ui.keyboard_light`) and the laptop's own
panel (`desktop_ui.laptop_panel`, dimmed to brightness 0) go dark and come back
at the same moments and by the same toggle. Everything follows the session's
lock and unlock messages; nothing is polled. Walking away is covered by
Windows locking the session after its own inactivity timeout.

Windows can't change the display topology from a locked session
(SetDisplayConfig returns ERROR_ACCESS_DENIED), so the protected screens are
turned off over DDC/CI instead. Windows keeps driving them: the monitor count
and work areas stay the same and placement doesn't react. Only monitors this
owner turned off are turned back on.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path

from cell import Cell
from contracts.keyboard.layout import UsbIdentity
from desktop_ui.kept import KeptFile
from desktop_ui.keyboard_light import KeyboardLight, ViaBacklight
from desktop_ui.laptop_panel import LaptopPanel, WmiBrightness
from desktop_ui.window_layout import Setups, dark_when_away
from winapi import screen, session
from winapi.monitor_power import Applied, Detached, PhysicalMonitors, Power
from winapi.screen import Monitor


class Change(Enum):
    """What the screens should do as the lock begins or ends."""

    DARKEN = auto()
    RESTORE = auto()


def step(*, dark: bool, locked: bool, enabled: bool) -> Change | None:
    """The change to make: darken as a lock begins while the setting is on, restore once either ends.

    A refused request isn't retried until the next change, which would otherwise
    cost about 65 ms of the bar's thread per protected screen each time."""
    wanted = locked and enabled
    if wanted and not dark:
        return Change.DARKEN
    if dark and not wanted:
        return Change.RESTORE
    return None


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
    enabled: bool = True
    """Dark when away, as the controls menu's toggle sets it."""
    darkened: bool = False
    """Whether this owner has darkened everything for the current lock."""
    dark: frozenset[Monitor] = frozenset()


@dataclass(frozen=True, slots=True)
class AwayScreens:
    """Owns the darkened screens across lock and unlock, on the bar's thread.

    Each DDC/CI request took about 65 ms on the home 4K screen, so only a lock
    or unlock costs one request per protected screen on that thread."""

    setups: Setups
    """Which screens each setup darkens while away."""
    _state: Cell[_Away]
    """Replaced whole on the bar's thread."""

    @classmethod
    def start(cls, directory: Path, setups: Setups, firmware: UsbIdentity) -> AwayScreens:
        """Started, or restarted, behind the lock screen as well as in front of it.

        A previous Workspace may have left the light and the panel dark; what they
        should go back to is kept on disk in `directory`, and they go back now unless still locked."""
        light = KeyboardLight.resume(ViaBacklight(firmware), KeptFile(directory / "dark-keyboard-effect"))
        panel = LaptopPanel.resume(WmiBrightness(), KeptFile(directory / "dark-panel-brightness"))
        locked = session.locked() is True
        if not locked:
            light, panel = light.restore(), panel.restore()
        screens = cls(setups, Cell(_Away(light, panel, PhysicalMonitors.open(), locked=locked)))
        screens.settle()
        return screens

    @property
    def enabled(self) -> bool:
        return self._state.get().enabled

    def message(self, message: int, wparam: int) -> None:
        if message == session.WM_DISPLAYCHANGE:
            away = self._state.get()
            away.kept.close()
            # A panel that refused while the lid was closed is back.
            panel = away.panel.restore() if not away.darkened else away.panel
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

    def toggle(self) -> None:
        self._state.update(lambda away: replace(away, enabled=not away.enabled))
        self.settle()

    def settle(self) -> None:
        away = self._state.get()
        match step(dark=away.darkened, locked=away.locked, enabled=away.enabled):
            case Change.DARKEN:
                self._state.set(replace(away, darkened=True))
                self.apply(dark_when_away(screen.monitors(), self.setups) - away.dark, Power.OFF)
                self._state.update(lambda current: replace(current, light=current.light.darken(), panel=current.panel.darken()))
            case Change.RESTORE:
                self._state.set(replace(away, darkened=False))
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
