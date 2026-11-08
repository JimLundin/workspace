"""Waiting in a test for something another thread, process or event loop does."""

import time
from collections.abc import Callable


def until(condition: Callable[[], bool], seconds: float = 5.0, *, pump: Callable[[], None] = lambda: None) -> bool:
    """Whether `condition` held within `seconds`; `pump` runs before each look, such as Qt's processEvents."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pump()
        if condition():
            return True
        time.sleep(0.01)
    return False
