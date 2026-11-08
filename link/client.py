"""The connecting end of a link: finds the server's published endpoint, and again after it restarts.

The client keeps trying until it reaches the server, proves the token, then
reads frames until the server goes away, and starts over. `status` reports
each change, so the client's owner can say what is unavailable meanwhile.
Frames sent while disconnected are refused (`send` returns False), not queued:
a command meant for a server that is restarting would act on a stale view.
"""

import contextlib
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Final

from cell import Cell
from link import frames
from link.endpoint import read

RETRY_S: Final = 0.5


class Status(Enum):
    CONNECTED = auto()
    DISCONNECTED = auto()


@dataclass(frozen=True, slots=True)
class _Connected:
    outbox: frames.Outbox
    stream: socket.socket


@dataclass(frozen=True, slots=True)
class Client:
    endpoint: Path
    receive: Callable[[bytes], None]
    status: Callable[[Status], None]
    _connected: Cell[_Connected | None] = field(default_factory=lambda: Cell[_Connected | None](None), init=False, repr=False)
    """The live session's outbox and socket, replaced whole under the lock."""
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _closed: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _started: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _finished: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    """Set when the connecting thread exits."""

    def start(self) -> None:
        self._started.set()
        threading.Thread(target=self._run, name="link client", daemon=True).start()

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected.get() is not None

    def send(self, payload: bytes) -> bool:
        """Any thread: queue a frame; False while no server is connected."""
        with self._lock:
            connected = self._connected.get()
        if connected is None:
            return False
        connected.outbox.put(payload)
        return True

    def _run(self) -> None:
        try:
            while not self._closed.is_set():
                published = read(self.endpoint)
                if published is not None:
                    with contextlib.suppress(OSError):
                        self._session(published.port, published.token)
                self._closed.wait(RETRY_S)
        finally:
            self._finished.set()

    def _session(self, port: int, token: str) -> None:
        with socket.create_connection(("127.0.0.1", port), timeout=RETRY_S * 4) as connected:
            connected.settimeout(None)
            frames.send(connected, token.encode())
            outbox = frames.Outbox()
            with self._lock:
                if self._closed.is_set():
                    return
                self._connected.set(_Connected(outbox, connected))
            writer = threading.Thread(target=frames.drain, args=(outbox, connected), name="link writer", daemon=True)
            writer.start()
            self.status(Status.CONNECTED)
            try:
                while (frame := frames.receive(connected)) is not None:
                    self.receive(frame)
            finally:
                with self._lock:
                    self._connected.set(None)
                outbox.close()
                self.status(Status.DISCONNECTED)

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            current = self._connected.get()
        if current is not None:
            with contextlib.suppress(OSError):
                current.stream.shutdown(socket.SHUT_RDWR)
        if self._started.is_set():
            self._finished.wait(timeout=5)
