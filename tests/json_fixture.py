"""Narrow casts for JSON objects emitted by the controlled local test fixtures."""

import json
from typing import cast

from assistant.llm import Json


def json_object(encoded: str | bytes) -> dict[str, Json]:
    return cast(dict[str, Json], json.loads(encoded))


def json_rows(value: Json) -> list[dict[str, Json]]:
    return cast(list[dict[str, Json]], value)


def json_fields(value: Json) -> dict[str, Json]:
    return cast(dict[str, Json], value)


def json_text(value: Json) -> str:
    return cast(str, value)


def json_value(encoded: str | bytes) -> Json:
    return cast(Json, json.loads(encoded))
