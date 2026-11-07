"""Start, stop or restart Workspace's programs from this checkout's uv environment.

    pythonw launch.py                  start every program that isn't running
    pythonw launch.py restart [NAME]   ask each (or NAME) to quit, then start it again
    pythonw launch.py stop [NAME]      ask each (or NAME) to quit

Each program is `python -m <module>` from `components.CATALOGUE`, started in its
order and stopped in reverse. A program is running when its control window
exists; stopping posts its quit message and ends it after its grace period.
Nothing supervises the programs: a crashed one stays down until the next start.
"""

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Final

from components import CATALOGUE, STATE_VARIABLE, Component, Entry

ROOT: Final = Path(__file__).resolve().parent
STATE: Final = Path(os.environ.get("LOCALAPPDATA") or ROOT) / "workspace" / "state"
"""Where the programs publish their endpoints and logs."""
DETACHED: Final = 0x0000_0008 | 0x0800_0000  # DETACHED_PROCESS | CREATE_NO_WINDOW

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_find = ctypes.WINFUNCTYPE(wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR)(("FindWindowW", _user32))
_post = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)(("PostMessageW", _user32))
_window_process = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))(("GetWindowThreadProcessId", _user32))
_open = ctypes.WINFUNCTYPE(wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)(("OpenProcess", _kernel32))
_terminate = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.UINT)(("TerminateProcess", _kernel32))
_close = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE)(("CloseHandle", _kernel32))


def pythonw() -> Path:
    """The checkout's environment interpreter, without a console."""
    return ROOT / ".venv" / "Scripts" / "pythonw.exe"


def window(entry: Entry) -> int:
    """The program's control window, 0 when it isn't running."""
    return int(_find(entry.window.window_class, entry.window.title) or 0)


def start(entry: Entry) -> None:
    if window(entry):
        return
    STATE.mkdir(parents=True, exist_ok=True)
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"} | {STATE_VARIABLE: str(STATE)}
    with (STATE / f"{entry.name}.log").open("ab") as errors:
        subprocess.Popen([str(pythonw()), "-m", entry.module], cwd=ROOT, env=environment, stdout=errors, stderr=errors, creationflags=DETACHED)


def stop(entry: Entry) -> None:
    """Ask the program to quit (the layout lets go of held keys first), then end it after its grace period."""
    handle = window(entry)
    if not handle:
        return
    process = wintypes.DWORD()
    _window_process(handle, ctypes.byref(process))
    _post(handle, entry.quit_message, 0, 0)
    deadline = time.monotonic() + entry.shutdown_s
    while window(entry) and time.monotonic() < deadline:
        time.sleep(0.1)
    if window(entry) and (owner := _open(0x0001, False, process.value)):  # PROCESS_TERMINATE
        try:
            _terminate(owner, 1)
        finally:
            _close(owner)


def selected(names: list[str]) -> tuple[Entry, ...]:
    unknown = frozenset(names) - CATALOGUE.keys()
    if unknown:
        raise SystemExit(f"Unknown program: {', '.join(sorted(unknown))}. Choose from {', '.join(CATALOGUE)}.")
    chosen: frozenset[Component] = frozenset(name for name in CATALOGUE if name in names) if names else frozenset(CATALOGUE)
    return tuple(entry for name, entry in CATALOGUE.items() if name in chosen)


def main(arguments: list[str]) -> None:
    command, *names = arguments or ["start"]
    entries = selected(names)
    if command not in ("start", "stop", "restart"):
        raise SystemExit(__doc__)
    if command in ("stop", "restart"):
        for entry in reversed(entries):
            stop(entry)
    if command in ("start", "restart"):
        for entry in entries:
            start(entry)


if __name__ == "__main__":
    main(sys.argv[1:])
