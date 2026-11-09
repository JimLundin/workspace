"""Workspace notification-area presentation and native icon lifetimes."""

from dataclasses import dataclass

from contracts.status import State
from desktop_ui.icons import COLOURS, dot
lazy from winapi import shell


@dataclass(frozen=True, slots=True)
class Tray:
    """The tray icon and the native icon handles it shows, kept until removal; used only on the Qt thread."""

    _icons: frozendict[State, shell.Icon]
    _icon: shell.TrayIcon

    @classmethod
    def add(cls, window: int, message: int) -> Tray:
        icons = frozendict((state, shell.Icon.draw(32, dot(32, COLOURS[state]))) for state in State)
        return cls(icons, shell.TrayIcon.add(window, message, icons[State.READY], "Workspace"))

    def show(self, state: State) -> None:
        self._icon.update(self._icons[state], f"Workspace: {state.name.lower().replace('_', ' ')}")

    def notify(self, title: str, text: str, *, warning: bool = False) -> None:
        self._icon.notify(title, text, shell.NIIF_WARNING if warning else shell.NIIF_INFO)

    def remove(self) -> None:
        self._icon.remove()
        for icon in self._icons.values():
            icon.destroy()

    def restore(self) -> None:
        self._icon.restore()
