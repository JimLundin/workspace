"""What the assistant tells the desktop.

The assistant never touches the desktop's windows: it sends `contracts.desktop_link`
messages through a `DesktopPort`. `LinkedDesktop` carries them over the link to
the desktop process; states are kept and replayed when a desktop connects.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from contracts.desktop_link import MicLevel, ToDesktop, state_key, to_desktop
from link.server import Server


class DesktopPort(Protocol):
    def send(self, message: ToDesktop) -> None: ...

    @property
    def connected(self) -> bool:
        """A desktop is listening now; while none is, events are dropped and states kept."""
        ...


@dataclass(frozen=True, slots=True)
class LinkedDesktop:
    """The desktop process, over the link's server end."""

    server: Server

    def send(self, message: ToDesktop) -> None:
        self.server.send(to_desktop(message), state_key(message))

    @property
    def connected(self) -> bool:
        return self.server.connected


@dataclass(frozen=True, slots=True)
class _Levels:
    read: Callable[[], float | None]
    port: DesktopPort
    listening: threading.Event
    stopped: threading.Event


def _feed_levels(levels: _Levels) -> None:
    while not levels.stopped.is_set():
        if not levels.listening.wait(0.2):
            continue
        level = levels.read()
        levels.port.send(MicLevel(None if level is None else min(1.0, max(0.0, level))))
        levels.stopped.wait(0.05)


@dataclass(frozen=True, slots=True)
class LevelFeed:
    """While dictation listens, the microphone's level goes to the desktop's trace every 50 ms."""

    _port: DesktopPort
    _listening: threading.Event
    _stopped: threading.Event
    _thread: threading.Thread

    @classmethod
    def start(cls, read: Callable[[], float | None], port: DesktopPort) -> LevelFeed:
        levels = _Levels(read, port, threading.Event(), threading.Event())
        thread = threading.Thread(target=_feed_levels, args=(levels,), name="microphone level feed", daemon=True)
        thread.start()
        return cls(port, levels.listening, levels.stopped, thread)

    def listen(self, *, enabled: bool) -> None:
        if enabled:
            self._listening.set()
        else:
            self._listening.clear()
            self._port.send(MicLevel(None))

    def close(self) -> None:
        self._stopped.set()
        self._listening.set()
        self._thread.join(timeout=1)
