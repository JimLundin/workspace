"""The usage log: features' uses and failures, with their diagnostic details. One JSON
object per line in `%LOCALAPPDATA%/workspace/usage.jsonl`. It records that a feature
was used (and how long it took, whether it failed), never what was typed or said.
Standard library only: the keyboard process records through this module, so it
writes with `json` instead of loading Pydantic.
"""

import contextlib
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Final

DIRECTORY: Final = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "workspace"
"""Where the workspace keeps its logs."""
USAGE_LOG: Final = DIRECTORY / "usage.jsonl"

type Detail = str | int | float | bool


def _append(entry: Mapping[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def record(source: str, feature: str, details: Mapping[str, Detail] | None = None, *, path: Path = USAGE_LOG) -> None:
    """One use of a feature. `details` may say `ok` (False for a failure), `seconds`..."""
    _append({"t": _now(), "source": source, "feature": feature, **(details or {})}, path)


def record_counts(source: str, counts: Mapping[str, int], *, path: Path = USAGE_LOG) -> None:
    """Uses counted since the last call, for features used too often to log one by one."""
    if counts:
        _append({"t": _now(), "source": source, "counts": dict(counts)}, path)


def record_quietly(source: str, feature: str, details: Mapping[str, Detail]) -> None:
    """`record`, dropping a write failure: the log is a convenience, never a reason for a feature to fail."""
    with contextlib.suppress(OSError):
        record(source, feature, details)
