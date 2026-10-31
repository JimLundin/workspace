"""Explicit ownership of real disposable Edge profiles and borrowed clients."""

import shutil
import threading
import time
import unittest
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

from assistant.browser import Browser
from assistant.browser_session import NativeSessions, Product, edge_path
from automation.json_value import Json
from tests.test_browser import command, decoded


def request(browser: Browser, operation: str, **args: Json) -> dict[str, Json]:
    return decoded(browser.request(command(operation, **args), threading.Event()).text)


def installed() -> None:
    if edge_path() is None:
        raise unittest.SkipTest("Microsoft Edge is not installed")


def dispose(browser: Browser, remove: Callable[[Path], None] = shutil.rmtree) -> None:
    """Release the disposable profile owned by a browser fixture."""
    browser.close()
    # Windows can briefly retain a dictionary mapping after browser exit.
    # This bounded fixture policy never hides persistent access failures.
    delays = (0, 0.02, 0.05, 0.1, 0.2, 0.4, 0.8)
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            remove(browser.profile)
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
