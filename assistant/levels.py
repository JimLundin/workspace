"""While dictation listens, the microphone's level goes to the desktop's trace."""

import threading
from collections.abc import Callable
from dataclasses import dataclass

from contracts.desktop_link import MicLevel, ToDesktop

type Publish = Callable[[ToDesktop], None]
"""How the assistant tells the desktop: it never touches the desktop's windows."""


@dataclass(frozen=True, slots=True)
class _Levels:
    read: Callable[[], float | None]
    publish: Publish
    listening: threading.Event
    stopped: threading.Event


def _feed_levels(levels: _Levels) -> None:
    while not levels.stopped.is_set():
        if not levels.listening.wait(0.2):
            continue
        level = levels.read()
        levels.publish(MicLevel(None if level is None else min(1.0, max(0.0, level))))
        levels.stopped.wait(0.05)


@dataclass(frozen=True, slots=True)
class LevelFeed:
    """While dictation listens, the microphone's level goes to the desktop's trace every 50 ms."""

    _publish: Publish
    _listening: threading.Event
    _stopped: threading.Event
    _thread: threading.Thread

    @classmethod
    def start(cls, read: Callable[[], float | None], publish: Publish) -> LevelFeed:
        levels = _Levels(read, publish, threading.Event(), threading.Event())
        thread = threading.Thread(target=_feed_levels, args=(levels,), name="microphone level feed", daemon=True)
        thread.start()
        return cls(publish, levels.listening, levels.stopped, thread)

    def listen(self, *, enabled: bool) -> None:
        if enabled:
            self._listening.set()
        else:
            self._listening.clear()
            self._publish(MicLevel(None))

    def close(self) -> None:
        self._stopped.set()
        self._listening.set()
        self._thread.join(timeout=1)
