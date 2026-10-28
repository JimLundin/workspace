"""Bounded failure evidence without exception objects, content or source lines."""

from dataclasses import dataclass

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


def failure_info(error: Exception) -> FailureInfo:
    """Copy only scalar evidence; a traceback would retain the keyboard's heap."""
    locations: list[str] = []
    trace = error.__traceback__
    while trace is not None:
        code = trace.tb_frame.f_code
        filename = code.co_filename.replace("\\", "/").rsplit("/", 1)[-1]
        locations.append(f"{filename}:{trace.tb_lineno}:{code.co_name}")
        if len(locations) > 8:
            del locations[0]
        trace = trace.tb_next
    accepted, expected = (error.accepted, error.expected) if isinstance(error, InputRejectedError) else (None, None)
    return FailureInfo(type(error).__name__, tuple(locations), accepted, expected)
