"""Assistant ports for desktop tests: concrete adapters, not mocks.

`Commands` records every command the desktop sends and accepts it, like a
connected assistant; `Unreachable` refuses every command, like one that is
restarting.
"""

import threading

from contracts.desktop_link import ToAssistant


class Commands:
    __slots__ = ("_lock", "_sent")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sent: tuple[ToAssistant, ...] = ()

    def send(self, command: ToAssistant) -> bool:
        with self._lock:
            self._sent = (*self._sent, command)
        return True

    @property
    def sent(self) -> tuple[ToAssistant, ...]:
        with self._lock:
            return self._sent


class Unreachable:
    __slots__ = ()

    def send(self, command: ToAssistant) -> bool:
        return False
