"""What the assistant tells the desktop, and the agent session's view over it.

The assistant never touches the desktop's windows: it sends `contracts.desktop_link`
messages through a `DesktopPort`. `LinkedDesktop` carries them over the link to
the desktop process; states are kept and replayed when a desktop connects.
"""

import queue
import threading
from collections.abc import Callable
from typing import Protocol

from contracts.agent_session import Snapshot
from contracts.desktop_link import MicLevel, SessionChanged, ShowWork, ToDesktop, state_key, to_desktop
from link.server import Server


class DesktopPort(Protocol):
    def send(self, message: ToDesktop) -> None: ...

    @property
    def connected(self) -> bool:
        """A desktop is listening now; while none is, events are dropped and states kept."""
        ...


class LinkedDesktop:
    """The desktop process, over the link's server end."""

    __slots__ = ("_server",)

    def __init__(self, server: Server) -> None:
        self._server = server

    def send(self, message: ToDesktop) -> None:
        self._server.send(to_desktop(message), state_key(message))

    @property
    def connected(self) -> bool:
        return self._server.connected


class ViewThread:
    """One thread for the agent session's view, as Qt's was: jobs run in order, one at a time."""

    __slots__ = ("_jobs", "_thread")

    def __init__(self) -> None:
        self._jobs: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="session view", daemon=True)
        self._thread.start()

    def post(self, job: Callable[[], None]) -> None:
        self._jobs.put(job)

    def _run(self) -> None:
        while (job := self._jobs.get()) is not None:
            job()

    def close(self) -> None:
        self._jobs.put(None)
        self._thread.join(timeout=5)


class SessionView:
    """The agent session's view: its snapshots go to the desktop and to the session's other observers."""

    __slots__ = ("_observe", "_port")

    def __init__(self, port: DesktopPort, observe: Callable[[Snapshot], object]) -> None:
        self._port, self._observe = port, observe

    def render(self, state: Snapshot) -> None:
        self._observe(state)
        self._port.send(SessionChanged(state))

    def show(self, *, focus: bool = False) -> None:
        self._port.send(ShowWork(focus=focus))

    def close(self) -> None:
        pass


class LevelFeed:
    """While dictation listens, the microphone's level goes to the desktop's trace every 50 ms."""

    __slots__ = ("_listening", "_port", "_read", "_stopped", "_thread")

    def __init__(self, read: Callable[[], float | None], port: DesktopPort) -> None:
        self._read, self._port = read, port
        self._listening, self._stopped = threading.Event(), threading.Event()
        self._thread = threading.Thread(target=self._run, name="microphone level feed", daemon=True)
        self._thread.start()

    def listen(self, *, enabled: bool) -> None:
        if enabled:
            self._listening.set()
        else:
            self._listening.clear()
            self._port.send(MicLevel(None))

    def _run(self) -> None:
        while not self._stopped.is_set():
            if not self._listening.wait(0.2):
                continue
            level = self._read()
            self._port.send(MicLevel(None if level is None else min(1.0, max(0.0, level))))
            self._stopped.wait(0.05)

    def close(self) -> None:
        self._stopped.set()
        self._listening.set()
        self._thread.join(timeout=1)
