"""Use Windows' accessibility API through its installed PowerShell/.NET bridge."""

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter


@dataclass(frozen=True, slots=True)
class Inspect:
    """List a window's accessible controls; handle 0 means the foreground window."""

    handle: int
    query: str = ""
    limit: int = 60
    depth: int = 8
    offset: int = 0
    operation: Literal["inspect"] = "inspect"


@dataclass(frozen=True, slots=True)
class Act:
    """Act on one inspected control; -1 leaves a scroll axis unchanged."""

    handle: int
    id: str
    action: str
    value: str = ""
    horizontal: int = -1
    vertical: int = -1
    operation: Literal["act"] = "act"


type UiRequest = Inspect | Act
_REQUEST = TypeAdapter[UiRequest](UiRequest)


def script(request: UiRequest) -> str:
    """Data is encoded separately from code, including text entered into controls."""
    payload = base64.b64encode(_REQUEST.dump_json(request)).decode("ascii")
    source = Path(__file__).with_suffix(".ps1").read_text(encoding="utf-8")
    return f"$request = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')) | ConvertFrom-Json\n{source}"
