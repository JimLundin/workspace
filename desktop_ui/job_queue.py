"""Running queued UI jobs a frame's slice at a time, in order, never inside one another."""

import queue
import threading
import time
from collections.abc import Callable
from typing import Final

BUDGET_S: Final = 0.004
"""A quarter of a 60 Hz frame, leaving room for painting and input."""
LIMIT: Final = 64
"""At most this many jobs per drain, however short."""


def drain[J](
    jobs: queue.Queue[J],
    run: Callable[[J], None],
    busy: threading.Event,
    *,
    clock: Callable[[], float] = time.monotonic,
    budget_s: float = BUDGET_S,
) -> None:
    """Run waiting jobs in order until the budget is spent; call only on the owning thread.

    One job still runs to completion: expensive preparation belongs off this
    queue. A job that pumps native events can reach this drain again; `busy`
    makes that nested drain return, so the next job never starts inside it.
    """
    if busy.is_set():
        return
    busy.set()
    deadline = clock() + budget_s
    try:
        for _ in range(LIMIT):
            try:
                job = jobs.get_nowait()
            except queue.Empty:
                break
            run(job)
            if clock() >= deadline:
                break
    finally:
        busy.clear()
