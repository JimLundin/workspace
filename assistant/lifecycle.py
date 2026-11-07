"""Optional content-free lifecycle measurements for deployment receipts."""

import contextlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from cell import Cell


def _trace() -> Path | None:
    value = os.environ.get("WORKSPACE_LIFECYCLE_TRACE")
    return Path(value) if value else None


@dataclass(frozen=True, slots=True)
class Timings:
    event: str
    output: Path | None = field(default_factory=_trace)
    _last: Cell[float] = field(default_factory=lambda: Cell(time.perf_counter()), init=False, repr=False)
    """When the previous phase ended."""

    def mark(self, phase: str) -> None:
        now = time.perf_counter()
        elapsed = now - self._last.get()
        self._last.set(now)
        if self.output is not None:
            with contextlib.suppress(OSError), self.output.open("a", encoding="utf-8") as stream:
                record: dict[str, str | float] = {"event": self.event, "phase": phase, "seconds": round(elapsed, 4)}
                stream.write(json.dumps(record) + "\n")
