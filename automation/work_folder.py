"""Shared storage paths used by the assistant and supervised work process."""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from usage import DIRECTORY


@dataclass(frozen=True, slots=True)
class WorkFolder:
    root: Path

    @property
    def journal(self) -> Path:
        return self.root / "work.sqlite3"


WORK: Final = WorkFolder(DIRECTORY / "work")
BROWSER_PROFILE: Final = DIRECTORY / "browser-profile"
