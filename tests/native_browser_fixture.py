"""Explicit ownership of real disposable Edge profiles and borrowed clients."""

import shutil
import threading
import time
import unittest
from collections.abc import Generator
from contextlib import contextmanager

from assistant.browser import Browser
from assistant.browser_host import ConnectRequest, Host, HostedConnection, Server
from assistant.browser_session import Attached, BrowserSession, NativeSessions, Product, Source
from contracts.json_value import Json
from tests.test_browser import command, decoded
from winapi.processes import edge_path


def request(browser: Browser, operation: str, **args: Json) -> dict[str, Json]:
    return decoded(browser.request(command(operation, **args), threading.Event()).text)


def installed() -> None:
    if edge_path() is None:
        raise unittest.SkipTest("Microsoft Edge is not installed")


def dispose(browser: Browser) -> None:
    """Release the disposable profile owned by a browser fixture."""
    browser.close()
    # Windows can briefly retain a dictionary mapping after browser exit.
    # This bounded fixture policy never hides persistent access failures.
    delays = (0, 0.02, 0.05, 0.1, 0.2, 0.4, 0.8)
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            shutil.rmtree(browser.profile)
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == len(delays) - 1:
                raise
        else:
            return


@contextmanager
def disposable(browser: Browser) -> Generator[Browser]:
    """Own one profile across compatible scenarios, including intentional restarts."""
    installed()
    try:
        yield browser
    finally:
        process = browser.process
        try:
            dispose(browser)
        except Exception as primary:
            # Preserve normal-close failure while still reaping our exact root
            # and removing its profile before the next group starts.
            if process is not None:
                try:
                    process.wait(timeout=10)
                except Exception as error:
                    primary.add_note(f"The captured browser root did not finish exiting: {error}")
            try:
                dispose(browser)
            except Exception as error:
                primary.add_note(f"The disposable browser profile could not be removed: {error}")
            raise


@contextmanager
def borrowed(personal: Browser) -> Generator[Browser]:
    """Fresh client state per scenario; detaching leaves the owner's tabs alive."""
    unused = personal.profile.parent / "unused-attached-profile"
    browser = Browser(unused, source=Product.EDGE, opener=NativeSessions(unused, profiles=lambda _: personal.profile))
    try:
        yield browser
    finally:
        browser.close()


class HostedSessions:
    """Use the real host exchange over the fixture's existing native browser."""

    __slots__ = ("server",)

    def __init__(self, server: Server) -> None:
        self.server = server

    def open(self, source: Source, cancel: threading.Event, *, visible: bool = False) -> BrowserSession:
        assert source is Product.EDGE
        connection = HostedConnection(self.server.location)
        self.server.location.exchange(ConnectRequest(self.server.location.token, connection.identity), cancel, timeout=5)
        return BrowserSession(connection, Attached(Product.EDGE))


@contextmanager
def hosted(personal: Browser) -> Generator[Browser]:
    """Own a disposable host while borrowing one already running browser."""
    unused = personal.profile.parent / "unused-hosted-profile"
    opener = NativeSessions(unused, profiles=lambda _: personal.profile)
    server = Server.bind(personal.profile.parent / "browser-host", Host(Product.EDGE, opener))
    server.start()
    browser = Browser(unused, source=Product.EDGE, opener=HostedSessions(server))
    try:
        yield browser
    finally:
        try:
            browser.close()
        finally:
            server.close()
