"""Optional content-free lifecycle measurements for deployment receipts, and how a background owner stops."""

import contextlib
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


def _trace() -> Path | None:
    value = os.environ.get("WORKSPACE_LIFECYCLE_TRACE")
    return Path(value) if value else None


@dataclass(frozen=True, slots=True)
class Timings:
    event: str
    output: Path | None = field(default_factory=_trace)
    started: float = field(default_factory=time.perf_counter, init=False, repr=False)
    """When the measurement began; each phase records how long after it the phase ended."""

    def mark(self, phase: str) -> None:
        if self.output is not None:
            at = time.perf_counter() - self.started
            with contextlib.suppress(OSError), self.output.open("a", encoding="utf-8") as stream:
                record: dict[str, str | float] = {"event": self.event, "phase": phase, "at_seconds": round(at, 4)}
                stream.write(json.dumps(record) + "\n")


def joined(started: threading.Event, finished: threading.Event, release: Callable[[], None], failure: str) -> None:
    """Wait for a started worker thread to finish, which releases its own source; one that never started is released here."""
    if not started.is_set():
        release()
    elif not finished.wait(20):
        raise OSError(failure)
