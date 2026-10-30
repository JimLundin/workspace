"""Saved monitor hint for the floating conversation, in physical screen pixels."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, TypedDict

from pydantic import Field, StrictInt, TypeAdapter

from usage import DIRECTORY
from winapi.shapes import Rect

PREFERENCE: Final = DIRECTORY / "agent-panel.json"


@dataclass(frozen=True, slots=True)
class PanelPreferences:
    bounds: Rect | None = None


class SavedBounds(TypedDict):
    x: StrictInt
    y: StrictInt
    width: Annotated[StrictInt, Field(gt=0)]
    height: Annotated[StrictInt, Field(gt=0)]


_BOUNDS = TypeAdapter(SavedBounds)


def load_preferences(path: Path = PREFERENCE) -> PanelPreferences:
    try:
        values = _BOUNDS.validate_json(path.read_bytes())
    except OSError, ValueError:
        return PanelPreferences()
    return PanelPreferences(Rect(values["x"], values["y"], values["x"] + values["width"], values["y"] + values["height"]))
