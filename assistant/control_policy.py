"""The assistant's control-thread startup and shell effects, without application resources."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import protocol
from components import LAYOUT


class StartupEffects(Protocol):
    def find_window(self, title: str) -> int | None: ...
    # Preserve HWND, message and both payload fields of the native wire contract.
    def post(self, handle: int, message: int, wparam: int, lparam: int) -> bool: ...
    def start_timer(self, handle: int) -> int: ...


def initialize_controls(handle: int, start_workers: Callable[[], None], effects: StartupEffects) -> int:
    """Start owners before requesting state replay."""
    timer = effects.start_timer(handle)
    start_workers()
    if (layout := effects.find_window(LAYOUT.window.title)) is not None:
        effects.post(layout, protocol.WM_QUERY_LAYOUT_STATE, 0, 0)
    return timer


def meeting_file_job(path: Path, open_file: Callable[[Path], None], report_error: Callable[[str], None]) -> Callable[[], None]:
    """Keep the canonical path and defer shell effects to the controller's worker."""

    def open_saved_file() -> None:
        try:
            open_file(path)
        except OSError:
            report_error("Windows could not open this file. Choose Open meeting transcripts in All Workspace controls to find it.")

    return open_saved_file
