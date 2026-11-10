"""A setting Workspace must put back, kept on disk while it is changed, so a restart can still put it back.

The away-screens owner turns the keyboard's backlight and the laptop's panel
down while the session is locked. If Workspace restarts meanwhile, the new
process reads the value it should restore from here instead of the dark one.
"""

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class Kept(Protocol):
    def load(self) -> int | None: ...

    def save(self, value: int) -> None: ...

    def clear(self) -> None: ...


@dataclass(frozen=True, slots=True)
class KeptFile:
    """One whole number in a file. A failed write only loses the value across a restart, so it is ignored."""

    path: Path

    def load(self) -> int | None:
        try:
            return int(self.path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return None

    def save(self, value: int) -> None:
        with suppress(OSError):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(str(value), encoding="utf-8")
            temporary.replace(self.path)

    def clear(self) -> None:
        with suppress(OSError):
            self.path.unlink(missing_ok=True)
