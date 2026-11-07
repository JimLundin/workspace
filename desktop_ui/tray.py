"""Workspace notification-area presentation and native icon lifetimes."""

import threading
from dataclasses import dataclass, field

from contracts.status import State
from desktop_ui.icons import COLOURS, dot
lazy from winapi import shell


@dataclass(frozen=True, slots=True)
class Tray:
    """Own native icon handles and serialize updates/removal across caller threads.

    The native shell mutates icon resources; this owner retains their handles
    until removal. The handle mapping is immutable, and the lock keeps those
    resource lifetimes exclusive while callers publish presentation updates.
    """

    _icons: frozendict[State, shell.Icon]
    _icon: shell.TrayIcon
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def add(cls, window: int, message: int) -> Tray:
        icons = frozendict((state, shell.Icon.draw(32, dot(32, COLOURS[state]))) for state in State)
        return cls(icons, shell.TrayIcon.add(window, message, icons[State.READY], "Workspace"))

    def show(self, state: State) -> None:
        with self._lock:
            self._icon.update(self._icons[state], f"Workspace: {state.name.lower().replace('_', ' ')}")

    def notify(self, title: str, text: str, *, warning: bool = False) -> None:
        with self._lock:
            self._icon.notify(title, text, shell.NIIF_WARNING if warning else shell.NIIF_INFO)

    def remove(self) -> None:
        with self._lock:
            self._icon.remove()
            for icon in self._icons.values():
                icon.destroy()

    def restore(self) -> None:
        with self._lock:
            self._icon.restore()
