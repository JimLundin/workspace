import time
from collections.abc import Callable


def until(
    condition: Callable[[], bool],
    seconds: float = 5.0,
    *,
    pump: Callable[[], None] = lambda: None,
) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pump()
        if condition():
            return True
        time.sleep(0.01)
    return False
