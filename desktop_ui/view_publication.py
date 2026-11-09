"""The desktop's own log: its problems and crashes, and why a view could not open or fell back."""

from typing import Final

import diagnostics
from diagnostics import DIRECTORY

LOG: Final = DIRECTORY / "desktop.log"


def log(text: str) -> None:
    diagnostics.append(LOG, text)
