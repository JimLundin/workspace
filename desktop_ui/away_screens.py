from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path

from cell import Cell
from desktop_ui.kept import KeptFile
from desktop_ui.keyboard_light import KeyboardLight, ViaBacklight
from desktop_ui.laptop_panel import LaptopPanel, WmiBrightness
from desktop_ui.window_layout import Setups, dark_when_away
from keyboard.layout import UsbIdentity
from winapi import screen, session
from winapi.monitor_power import Applied, Detached, PhysicalMonitors, Power
from winapi.screen import Monitor


class Change(Enum):
    DARKEN = auto()
    RESTORE = auto()


def step(*, dark: bool, locked: bool, enabled: bool) -> Change | None:
    wanted = locked and enabled
    if wanted and not dark:
        return Change.DARKEN
    if dark and not wanted:
        return Change.RESTORE
    return None


def dark_after(
    dark: frozenset[Monitor], applied: Mapping[Monitor, Applied]
) -> frozenset[Monitor]:
    off = frozenset(
        monitor for monitor, result in applied.items() if result is Power.OFF
    )
    on = frozenset(
        monitor for monitor, result in applied.items() if result is Power.ON
    )
    return (dark | off) - on


def set_power(
    sources: Sequence[PhysicalMonitors], monitor: Monitor, wanted: Power
) -> Applied:
    result: Applied = Detached()
    for source in sources:
        result = source.set_power(monitor, wanted)
        if result is wanted:
            return result
    return result


@dataclass(frozen=True, slots=True)
class _Away:
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
    setups: Setups
    """Which screens each setup darkens while away."""
    _state: Cell[_Away]
    """Replaced whole on the bar's thread."""

    @classmethod
    def start(
        cls, directory: Path, setups: Setups, firmware: UsbIdentity
    ) -> AwayScreens:
        light = KeyboardLight.resume(
            ViaBacklight(firmware), KeptFile(directory / "dark-keyboard-effect")
        )
        panel = LaptopPanel.resume(
            WmiBrightness(), KeptFile(directory / "dark-panel-brightness")
        )
        locked = session.locked() is True
        if not locked:
            light, panel = light.restore(), panel.restore()
        screens = cls(
            setups,
            Cell(_Away(light, panel, PhysicalMonitors.open(), locked=locked)),
        )
        screens.settle()
        return screens

    @property
    def enabled(self) -> bool:
        return self._state.get().enabled

    def message(self, message: int, wparam: int) -> None:
        if message == session.WM_DISPLAYCHANGE:
            away = self._state.get()
            away.kept.close()
            panel = away.panel.restore() if not away.darkened else away.panel
            self._state.set(
                replace(away, kept=PhysicalMonitors.open(), panel=panel)
            )
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
        match step(
            dark=away.darkened, locked=away.locked, enabled=away.enabled
        ):
            case Change.DARKEN:
                self._state.set(replace(away, darkened=True))
                self.apply(
                    dark_when_away(screen.monitors(), self.setups) - away.dark,
                    Power.OFF,
                )
                self._state.update(
                    lambda current: replace(
                        current,
                        light=current.light.darken(),
                        panel=current.panel.darken(),
                    )
                )
            case Change.RESTORE:
                self._state.set(replace(away, darkened=False))
                self.apply(away.dark, Power.ON)
                self._state.update(
                    lambda current: replace(
                        current,
                        light=current.light.restore(),
                        panel=current.panel.restore(),
                    )
                )
            case None:
                pass

    def apply(self, monitors: frozenset[Monitor], wanted: Power) -> None:
        if not monitors:
            return
        fresh = PhysicalMonitors.open()
        try:
            powered = frozendict(
                (
                    monitor,
                    set_power((fresh, self._state.get().kept), monitor, wanted),
                )
                for monitor in monitors
            )
        finally:
            fresh.close()
        self._state.update(
            lambda away: replace(away, dark=dark_after(away.dark, powered))
        )

    def close(self) -> None:
        self.apply(self._state.get().dark, Power.ON)
        away = self._state.update(
            lambda current: replace(
                current,
                light=current.light.restore(),
                panel=current.panel.restore(),
            )
        )
        away.kept.close()
