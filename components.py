"""The programs the keeper supervises, and how each one proves it is up.

The keeper, the deployment coordinator and every child read this one catalogue.
It is protected with the keeper and uses only the standard library, so the
keyboard process announces readiness without importing the keeper.

A readiness marker names the process that wrote it: its id and creation time.
Together they identify one process even after Windows reuses the id, so a
reader compares the writer with the process it observed instead of a file time.
"""

import contextlib
import ctypes
import os
from collections.abc import Iterable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol

type Component = Literal["layout", "assistant", "automation"]

WM_CLOSE: Final = 0x0010


@dataclass(frozen=True, slots=True)
class Window:
    """The hidden control window a component creates; other processes find it by title."""

    title: str
    window_class: str | None
    """None matches any class: the component uses a system class, not its own."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Entry:
    name: Component
    module: str
    """Started as `python -m <module>`."""
    window: Window
    quit_message: int
    """Posted to `window` to ask for a clean exit; the layout lets go of held keys first."""
    shutdown_s: float
    """How long the keeper waits for a clean exit before ending the process."""

    def marker(self, state: Path) -> Path:
        return state / f"ready-{self.name}"


# Assistant cleanup includes a 20-second personal-work join, and automation must
# park ongoing work and close its browser: a bounded minute each. The keyboard
# has nothing to drain, so a stuck one is replaced quickly.
LAYOUT: Final = Entry(name="layout", module="miryoku", window=Window("workspace layout", None), quit_message=0x8003, shutdown_s=5.0)
ASSISTANT: Final = Entry(
    name="assistant",
    module="assistant",
    window=Window("workspace assistant", "workspace assistant class"),
    quit_message=WM_CLOSE,
    shutdown_s=60.0,
)
AUTOMATION: Final = Entry(name="automation", module="automation", window=Window("workspace automation", None), quit_message=WM_CLOSE, shutdown_s=60.0)

CATALOGUE: Final[frozendict[Component, Entry]] = frozendict({entry.name: entry for entry in (LAYOUT, ASSISTANT, AUTOMATION)})
"""In startup order. Shutdown reverses it so automation releases the desktop before the assistant's UI."""

BAR_WINDOW: Final = "Workspace floating bar"
"""The assistant's visible surface; a deployment restores it when it was showing."""


def shutdown_budget(names: Iterable[Component]) -> float:
    """The keeper stops children one at a time, so their budgets add up."""
    return sum(CATALOGUE[name].shutdown_s for name in names)


@dataclass(frozen=True, slots=True)
class Writer:
    pid: int
    started_ms: int
    """Process creation time, Unix milliseconds."""


class _Function[T](Protocol):
    """The stdcall prototype validates ABI arguments and fixes the scalar result."""

    def __call__(self, *args: object) -> T: ...


def unix_ms(time: wintypes.FILETIME) -> int:
    return ((time.dwHighDateTime << 32) | time.dwLowDateTime) // 10_000 - 11_644_473_600_000


def started_ms(pid: int) -> int:
    """When Windows created the process."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process: _Function[int | None] = ctypes.WINFUNCTYPE(wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)(("OpenProcess", kernel))
    process_times: _Function[int] = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))(
        ("GetProcessTimes", kernel)
    )
    close: _Function[int] = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE)(("CloseHandle", kernel))
    handle = open_process(0x1000, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        times = tuple(wintypes.FILETIME() for _ in range(4))
        if not process_times(handle, *(ctypes.byref(time) for time in times)):
            raise ctypes.WinError(ctypes.get_last_error())
        return unix_ms(times[0])
    finally:
        close(handle)


def write_marker(marker: Path, writer: Writer) -> None:
    marker.write_text(f"{writer.pid} {writer.started_ms}", encoding="ascii")


def read_marker(marker: Path) -> Writer | None:
    """Who announced readiness; None until a complete marker exists."""
    try:
        text = marker.read_text(encoding="ascii")
    except OSError, UnicodeDecodeError:
        return None
    match text.split():
        case [pid, started] if pid.isdecimal() and started.isdecimal():
            return Writer(int(pid), int(started))
        case _:
            return None


def ready() -> None:
    """Called by a program the keeper runs, once it's up."""
    if path := os.environ.get("WORKSPACE_READY"):
        with contextlib.suppress(OSError):
            pid = os.getpid()
            write_marker(Path(path), Writer(pid, started_ms(pid)))
