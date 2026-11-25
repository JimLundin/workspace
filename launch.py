import ctypes
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from ctypes import wintypes
from pathlib import Path
from typing import Final

from protocol import Component, Entry, Places, Programs, interpreter
from settings import programs
from winapi._core import (
    CloseHandle,
    FindWindowW,
    GetWindowThreadProcessId,
    OpenProcess,
    PostMessageW,
    WaitForSingleObject,
)
from winapi.processes import DETACHED

ROOT: Final = Path(__file__).resolve().parent

SYNCHRONIZE: Final = 0x0010_0000
WAIT_TIMEOUT: Final = 0x0000_0102


def window(entry: Entry) -> int:
    return int(FindWindowW(entry.window.window_class, entry.window.title) or 0)


def started(entry: Entry, state: Path) -> int | None:
    try:
        pid = int((state / f"{entry.name}.pid").read_text(encoding="ascii"))
    except OSError, ValueError:
        return None
    handle = OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return None
    try:
        return pid if WaitForSingleObject(handle, 0) == WAIT_TIMEOUT else None
    finally:
        CloseHandle(handle)


def running(entry: Entry, state: Path) -> bool:
    return bool(window(entry)) or started(entry, state) is not None


def start(entry: Entry, state: Path, variable: str) -> None:
    if running(entry, state):
        return
    state.mkdir(parents=True, exist_ok=True)
    environment = {
        key: value for key, value in os.environ.items() if key != "PYTHONPATH"
    } | {variable: str(state)}
    with (state / f"{entry.name}.log").open("ab") as errors:
        process = subprocess.Popen(
            [str(interpreter(ROOT)), "-m", entry.module],
            cwd=ROOT,
            env=environment,
            stdout=errors,
            stderr=errors,
            creationflags=DETACHED,
        )
    (state / f"{entry.name}.pid").write_text(str(process.pid), encoding="ascii")


def stop(entry: Entry, state: Path) -> None:
    if handle := window(entry):
        PostMessageW(handle, entry.quit_message, 0, 0)
    deadline = time.monotonic() + entry.shutdown_s
    while running(entry, state) and time.monotonic() < deadline:
        time.sleep(0.1)
    if handle := window(entry):
        owner = wintypes.DWORD()
        GetWindowThreadProcessId(handle, ctypes.byref(owner))
        terminate(owner.value)
    if (pid := started(entry, state)) is not None:
        terminate(pid)


def terminate(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        check=False,
        creationflags=0x0800_0000,
    )


def selected(
    names: Sequence[str], catalogue: frozendict[Component, Entry]
) -> tuple[Entry, ...]:
    unknown = frozenset(names) - catalogue.keys()
    if unknown:
        raise SystemExit(
            f"Unknown program: {', '.join(sorted(unknown))}. Choose from {', '.join(catalogue)}."
        )
    chosen: frozenset[Component] = (
        frozenset(name for name in catalogue if name in names)
        if names
        else frozenset(catalogue)
    )
    return tuple(entry for name, entry in catalogue.items() if name in chosen)


def main(arguments: Sequence[str], workspace: Programs) -> None:
    command, *names = arguments or ["start"]
    entries = selected(names, workspace.catalogue)
    if command not in ("start", "stop", "restart"):
        raise SystemExit(__doc__)
    state = Places.of(os.environ, workspace).directory / "state"
    if command in ("stop", "restart"):
        for entry in reversed(entries):
            stop(entry, state)
    if command in ("start", "restart"):
        for entry in entries:
            start(entry, state, workspace.state_variable)


if __name__ == "__main__":
    main(sys.argv[1:], programs.PROGRAMS)
