"""Bounded failure evidence without exception objects, content or source lines, and the programs' own logs."""

import contextlib
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from winapi.shapes import InputRejectedError

type Detail = str | int | float | bool


@dataclass(frozen=True, slots=True)
class FailureInfo:
    error_type: str
    locations: tuple[str, ...]
    accepted: int | None
    expected: int | None

    def details(self) -> dict[str, Detail]:
        details: dict[str, Detail] = {"error_type": self.error_type, "locations": " > ".join(self.locations)}
        if self.accepted is not None and self.expected is not None:
            details.update(input_accepted=self.accepted, input_expected=self.expected)
        return details


def _traces(trace: TracebackType | None) -> Iterator[TracebackType]:
    while trace is not None:
        yield trace
        trace = trace.tb_next


def _location(trace: TracebackType) -> str:
    code = trace.tb_frame.f_code
    filename = code.co_filename.replace("\\", "/").rsplit("/", 1)[-1]
    return f"{filename}:{trace.tb_lineno}:{code.co_name}"


def failure_info(error: Exception) -> FailureInfo:
    """Copy only scalar evidence; a traceback would retain the keyboard's heap."""
    locations = tuple(_location(trace) for trace in tuple(_traces(error.__traceback__))[-8:])
    accepted, expected = (error.accepted, error.expected) if isinstance(error, InputRejectedError) else (None, None)
    return FailureInfo(type(error).__name__, locations, accepted, expected)


def append(log: Path, text: str) -> None:
    """One timestamped line in a program's own log, its record of problems and crashes (there's no console under pythonw)."""
    with contextlib.suppress(OSError):
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as file:
            file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")


def evidence(event: str, details: Mapping[str, Detail]) -> str:
    """An event and its scalar details, as one line for a program's own log."""
    return " ".join((f"{event}:", *(f"{name}={value}" for name, value in details.items())))
