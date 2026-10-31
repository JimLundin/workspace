"""A JSON value, as Workspace's wire, storage and model boundaries carry it."""

type Json = str | int | float | bool | list[Json] | dict[str, Json] | None
