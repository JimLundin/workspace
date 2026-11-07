"""The serving end of a link: one client at a time, its token proven, states replayed on connect.

The server listens on loopback and publishes its port and a per-boot token. A
client that connects sends the token first; a wrong token is closed without a
reply. A new client replaces the one before it. Keyed frames (states) replace
their waiting predecessor and the latest of each key is replayed to every client
that connects; unkeyed frames (events) are sent once, or dropped with no client.
"""

import contextlib
import hmac
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

from cell import Cell
from link import frames
from link.endpoint import Endpoint, publish

HANDSHAKE_S: Final = 5.0
"""How long a connecting client has to prove its token."""


@dataclass(frozen=True, slots=True)
class _Connection:
    stream: socket.socket
    outbox: frames.Outbox = field(default_factory=frames.Outbox)

    def close(self) -> None:
        self.outbox.close()
        with contextlib.suppress(OSError):
            self.stream.shutdown(socket.SHUT_RDWR)
        self.stream.close()


@dataclass(frozen=True, slots=True)
class _Serving:
    retained: frozendict[str, bytes] = frozendict()
    """The latest frame of each key, so a replay reads a fixed set."""
    current: _Connection | None = None
    closed: bool = False


@dataclass(frozen=True, slots=True)
class Server:
    token: str
    receive: Callable[[bytes], None]
    _listener: socket.socket
    _serving: Cell[_Serving] = field(default_factory=lambda: Cell(_Serving()), init=False, repr=False)
    """Replaced whole under the lock."""
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def listen(cls, token: str, receive: Callable[[bytes], None], *, port: int = 0) -> Server:
        return cls(token, receive, socket.create_server(("127.0.0.1", port)))

    @property
    def port(self) -> int:
        address: tuple[str, int] = self._listener.getsockname()
        return address[1]

    def start(self, published: Path | None = None) -> None:
        """Serve from now on; `published` is where clients find the port and token."""
        if published is not None:
            publish(published, Endpoint(self.port, self.token))
        threading.Thread(target=self._accept, name="link server", daemon=True).start()

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._serving.get().current is not None

    def send(self, payload: bytes, key: str | None = None) -> None:
        """Any thread: queue a frame for the client; a keyed frame is also kept for the next."""
        with self._lock:
            if key is not None:
                self._serving.update(lambda serving: replace(serving, retained=frozendict({**serving.retained, key: payload})))
            current = self._serving.get().current
        if current is not None:
            current.outbox.put(payload, key)

    def _accept(self) -> None:
        while not self._serving.get().closed:
            try:
                connected, _ = self._listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(connected,), name="link client", daemon=True).start()

    def _serve(self, connected: socket.socket) -> None:
        connection = _Connection(connected)
        try:
            connected.settimeout(HANDSHAKE_S)
            offered = frames.receive(connected)
            if offered is None or not hmac.compare_digest(offered, self.token.encode()):
                return
            connected.settimeout(None)
            with self._lock:
                serving = self._serving.get()
                self._serving.set(replace(serving, current=connection))
                for key, payload in serving.retained.items():
                    connection.outbox.put(payload, key)
            previous = serving.current
            if previous is not None:
                previous.close()
            threading.Thread(target=self._write, args=(connection,), name="link writer", daemon=True).start()
            while (frame := frames.receive(connected)) is not None:
                self.receive(frame)
        except OSError:
            pass
        finally:
            with self._lock:
                if self._serving.get().current is connection:
                    self._serving.update(lambda serving: replace(serving, current=None))
            connection.close()

    @staticmethod
    def _write(connection: _Connection) -> None:
        with contextlib.suppress(OSError):
            while (payload := connection.outbox.take()) is not None:
                frames.send(connection.stream, payload)

    def close(self) -> None:
        with self._lock:
            current = self._serving.get().current
            self._serving.update(lambda serving: replace(serving, current=None, closed=True))
        with contextlib.suppress(OSError):
            self._listener.close()
        if current is not None:
            current.close()
