"""The desktop's view log: why a view could not open or fell back, for diagnosis."""

import contextlib
import time
from typing import Final

from usage import DIRECTORY

VIEW_LOG: Final = DIRECTORY / "agent-ui.log"


def log_view(text: str) -> None:
    with contextlib.suppress(OSError):
        VIEW_LOG.parent.mkdir(parents=True, exist_ok=True)
        with VIEW_LOG.open("a", encoding="utf-8") as output:
            output.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
