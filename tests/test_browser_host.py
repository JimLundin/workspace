"""Exercise real local exchanges and the lifetime of one shared browser connection."""

import threading
import time
from pathlib import Path
from unittest import TestCase

from assistant.browser_host import Host, HostedConnection, Server, exchange
from assistant.browser_session import Attached, BrowserSession, Product, Source
from assistant.browser_values import BrowserError, DisconnectedError, InterruptedError, NavigationContextError
from assistant.llm import Json


class Connection:
    def __init__(self) -> None:
        self.closed = 0
        self.sessions = 0
        self.calls: list[str] = []
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def call(
        self, method: str, params: dict[str, Json], cancel: threading.Event, *, session: str = "", timeout: float = 15,
    ) -> dict[str, Json]:
        self.calls.append(method)
        if method == "Target.attachToTarget":
            self.sessions += 1
            return {"sessionId": str(self.sessions)}
        if method == "slow":
            raise BrowserError("Operation timed out")
        if method == "retired-context":
            raise BrowserError("Cannot find context with specified id")  # A host started before the client update.
        if method == "wait":
            self.started.set()
            assert cancel.wait(3)
            self.cancelled.set()
            raise InterruptedError("Stopped")
        if method == "disconnect":
            raise DisconnectedError("Browser closed")
        return {"value": "observed"}

    def close(self) -> None:
        self.closed += 1


class Opener:
    def __init__(self) -> None:
        self.opens = 0
        self.connection = Connection()

    def open(self, source: Source, cancel: threading.Event, *, visible: bool = False) -> BrowserSession:
        assert source is Product.EDGE
        self.opens += 1
        return BrowserSession(self.connection, Attached(Product.EDGE))


def client(server: Server) -> HostedConnection:
    connection = HostedConnection(server.location)
    exchange(server.location, {"operation": "connect", "client": connection.identity}, threading.Event(), timeout=1)
    return connection


def test_reloaded_clients_share_one_connection_and_release_only_their_sessions(tmp_path: Path) -> None:
    opener = Opener()
    server = Server(tmp_path, Host(Product.EDGE, opener))
    server.start()
    try:
        first, second = client(server), client(server)
        session = first.call("Target.attachToTarget", {}, threading.Event())["sessionId"]
        assert isinstance(session, str)
        with TestCase().assertRaisesRegex(BrowserError, "another client"):
            second.call("Runtime.evaluate", {}, threading.Event(), session=session)
        first.close()
        third = client(server)
        assert third.call("Browser.getVersion", {}, threading.Event()) == {"value": "observed"}
        assert opener.opens == 1 and opener.connection.closed == 0
        assert "Target.detachFromTarget" in opener.connection.calls
        status = exchange(server.location, {"operation": "status"}, threading.Event(), timeout=1)
        assert status["generation"] == 1 and status["clients"] == 2
        second.close()
        third.close()
    finally:
        server.close()
    assert opener.connection.closed == 1


def test_timeout_and_cancel_do_not_disconnect_the_shared_browser(tmp_path: Path) -> None:
    opener = Opener()
    server = Server(tmp_path, Host(Product.EDGE, opener))
    server.start()
    failures: list[Exception] = []
    cancelled = threading.Event()
    try:
        connection = client(server)
        with TestCase().assertRaisesRegex(BrowserError, "timed out"):
            connection.call("slow", {}, threading.Event())
        def wait() -> None:
            try:
                connection.call("wait", {}, cancelled)
            except Exception as error:
                failures.append(error)
        thread = threading.Thread(target=wait)
        thread.start()
        assert opener.connection.started.wait(1)
        cancelled.set()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert failures and isinstance(failures[0], InterruptedError)
        assert opener.connection.cancelled.wait(2)
        assert connection.call("Browser.getVersion", {}, threading.Event()) == {"value": "observed"}
        assert opener.opens == 1 and opener.connection.closed == 0
        connection.close()
    finally:
        server.close()


def test_lost_browser_requires_explicit_reconnection_and_status_never_connects(tmp_path: Path) -> None:
    opener = Opener()
    server = Server(tmp_path, Host(Product.EDGE, opener))
    server.start()
    try:
        assert exchange(server.location, {"operation": "status"}, threading.Event(), timeout=1)["connected"] is False
        assert opener.opens == 0
        connection = client(server)
        with TestCase().assertRaises(DisconnectedError):
            connection.call("disconnect", {}, threading.Event())
        for _ in range(3):
            with TestCase().assertRaises(DisconnectedError):
                connection.call("Browser.getVersion", {}, threading.Event())
        assert opener.opens == 1
        assert exchange(server.location, {"operation": "status"}, threading.Event(), timeout=1)["connected"] is False
        replacement = client(server)
        assert opener.opens == 2
        replacement.close()
    finally:
        server.close()


def test_old_host_retired_context_remains_recoverable_without_a_new_browser_connection(tmp_path: Path) -> None:
    opener = Opener()
    server = Server(tmp_path, Host(Product.EDGE, opener))
    server.start()
    try:
        connection = client(server)
        with TestCase().assertRaises(NavigationContextError):
            connection.call("retired-context", {}, threading.Event())
        assert connection.call("Browser.getVersion", {}, threading.Event()) == {"value": "observed"}
        assert opener.opens == 1 and opener.connection.closed == 0
        connection.close()
    finally:
        server.close()


def test_cancelling_a_queued_request_never_runs_it(tmp_path: Path) -> None:
    opener = Opener()
    server = Server(tmp_path, Host(Product.EDGE, opener))
    server.start()
    cancelled = threading.Event()
    errors: list[Exception] = []
    try:
        connection = client(server)
        server.host.lock.acquire()
        def queued() -> None:
            try:
                connection.call("must-not-run", {}, cancelled)
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=queued)
        thread.start()
        time.sleep(.1)
        cancelled.set()
        thread.join(timeout=1)
        time.sleep(.2)
        server.host.lock.release()
        assert errors and isinstance(errors[0], InterruptedError)
        assert "must-not-run" not in opener.connection.calls
        connection.close()
    finally:
        server.close()
