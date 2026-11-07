"""Bounded failure evidence without exception objects, content or source lines."""

from collections.abc import Iterator
from dataclasses import dataclass
from types import TracebackType

from usage import Detail
from winapi.shapes import InputRejectedError


@dataclass(frozen=True, slots=True)
class FailureInfo:
    kind: str
    locations: tuple[str, ...]
    accepted: int | None
    expected: int | None

    def details(self) -> dict[str, Detail]:
        details: dict[str, Detail] = {"error_type": self.kind, "locations": " > ".join(self.locations)}
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
