from collections.abc import Mapping
from ctypes import wintypes
from dataclasses import dataclass
from typing import Final, assert_never

from winapi import windows
from winapi._core import CloseHandle, OpenProcess, PostMessageW, fn, kernel32

DETACHED: Final = 0x0000_0008 | 0x0800_0000
"""DETACHED_PROCESS | CREATE_NO_WINDOW: a child that outlives its parent, without a console."""

_WM_CLOSE: Final = 0x0010
_PROCESS_TERMINATE: Final = 0x0001

_TerminateProcess = fn(
    kernel32, "TerminateProcess", wintypes.BOOL, wintypes.HANDLE, wintypes.UINT
)


@dataclass(frozen=True, slots=True)
class CloseWindows:
    handles: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Terminate:
    pids: frozenset[int]


type Ending = CloseWindows | Terminate


def ending(owners: Mapping[int, int], pids: frozenset[int]) -> Ending:
    """Closes an app's windows, as their close buttons would, so it can save its work; ends it only when it has none."""
    handles = tuple(handle for handle, pid in owners.items() if pid in pids)
    return CloseWindows(handles) if handles else Terminate(pids)


def end(pids: frozenset[int]) -> None:
    owners = frozendict(
        (window.handle, windows.process_id(window.handle))
        for window in windows.windows(include_cloaked=True)
    )
    match chosen := ending(owners, pids):
        case CloseWindows(handles):
            for handle in handles:
                PostMessageW(handle, _WM_CLOSE, 0, 0)
        case Terminate(pids=ended):
            for pid in ended:
                if process := OpenProcess(_PROCESS_TERMINATE, False, pid):
                    try:
                        _TerminateProcess(process, 1)
                    finally:
                        CloseHandle(process)
        case _:
            assert_never(chosen)
