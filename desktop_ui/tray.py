"""Workspace notification-area presentation and native icon lifetimes."""

import threading

from contracts.status import State
from desktop_ui.icons import dot
lazy from winapi import shell


class Tray:
    """Own native icon handles and serialize updates/removal across caller threads.

    The native shell mutates icon resources; this owner retains their handles
    until removal. The handle mapping is immutable, and the lock keeps those
    resource lifetimes exclusive while callers publish presentation updates.
    """

    __slots__ = ("_icon", "_icons", "_lock")

    def __init__(self, window: int, message: int) -> None:
        self._icons = frozendict((state, shell.Icon(32, dot(32, state.value))) for state in State)
        self._lock = threading.Lock()
        self._icon = shell.TrayIcon(window, message, self._icons[State.READY], "Workspace")

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
