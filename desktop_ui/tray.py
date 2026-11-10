"""Workspace notification-area presentation and native icon lifetimes."""

from dataclasses import dataclass
from typing import Final

from contracts.members import every_member
from contracts.status import State
from desktop_ui.colour import Rgb
from desktop_ui.icons import dot
lazy from winapi import shell


@dataclass(frozen=True, slots=True, kw_only=True)
class TraySpec:
    """The notification-area icon: its name, its drawn size in pixels, and its dot's colour for each thing the assistant can be doing."""

    name: str
    size: int
    colours: frozendict[State, Rgb]

    def __post_init__(self) -> None:
        every_member(State, self.colours)


TRAY_ICON: Final = TraySpec(
    name="Workspace",
    size=32,
    colours=frozendict(
        {
            State.READY: Rgb(46, 160, 120),
            State.LAYOUT_OFF: Rgb(140, 140, 140),
            State.LISTENING: Rgb(220, 50, 50),
            State.RECORDING: Rgb(230, 64, 85),
            State.WORKING: Rgb(235, 160, 30),
        }
    ),
)


@dataclass(frozen=True, slots=True)
class Tray:
    """The tray icon and the native icon handles it shows, kept until removal; used only on the Qt thread."""

    _spec: TraySpec
    _icons: frozendict[State, shell.Icon]
    _icon: shell.TrayIcon

    @classmethod
    def add(cls, window: int, message: int, spec: TraySpec) -> Tray:
        icons = frozendict((state, shell.Icon.draw(spec.size, dot(spec.size, spec.colours[state]))) for state in State)
        return cls(spec, icons, shell.TrayIcon.add(window, message, icons[State.READY], spec.name))

    def show(self, state: State) -> None:
        self._icon.update(self._icons[state], f"{self._spec.name}: {state.name.lower().replace('_', ' ')}")

    def notify(self, title: str, text: str, *, warning: bool = False) -> None:
        self._icon.notify(title, text, shell.NIIF_WARNING if warning else shell.NIIF_INFO)

    def remove(self) -> None:
        self._icon.remove()
        for icon in self._icons.values():
            icon.destroy()

    def restore(self) -> None:
        self._icon.restore()
