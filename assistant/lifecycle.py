"""Optional content-free lifecycle measurements for deployment receipts."""

import contextlib
import json
import os
import time
from pathlib import Path


class Timings:
    __slots__ = ("event", "last", "output")

    def __init__(self, event: str) -> None:
        value = os.environ.get("WORKSPACE_LIFECYCLE_TRACE")
        self.output = Path(value) if value else None
        self.event = event
        self.last = time.perf_counter()

    def mark(self, phase: str) -> None:
        now = time.perf_counter()
        elapsed, self.last = now - self.last, now
        if self.output is not None:
            with contextlib.suppress(OSError), self.output.open("a", encoding="utf-8") as stream:
                record: dict[str, str | float] = {"event": self.event, "phase": phase, "seconds": round(elapsed, 4)}
                stream.write(json.dumps(record) + "\n")
