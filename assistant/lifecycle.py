"""Optional content-free lifecycle measurements for deployment receipts."""

import contextlib
import json
import os
import time
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
