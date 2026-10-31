"""Volatile conversation storage; parsed SDK collections never remain shared."""

from collections.abc import Iterable

from pydantic import TypeAdapter

from automation.json_value import Json

_ITEM = TypeAdapter(Json)
_ITEMS = TypeAdapter(tuple[Json, ...])


class History:
    """Own session IO across serialized executions, retaining immutable wire bytes.

    The execution owner retains this handle, and its SDK session is the sole
    writer during a run. Parsing gives the SDK fresh collections each time;
    neither SDK edits nor callers can mutate a retained conversation item.
    History stays in memory, including opaque reasoning and recent images.
    Durable checkpoints retain structural progress through their own adapter.
    """

    __slots__ = ("_items",)

    def __init__(self) -> None:
        self._items: tuple[bytes, ...] = ()

    def read(self, limit: int | None = None) -> list[Json]:
        items = self._items if limit is None else self._items[-limit:] if limit > 0 else ()
        return [_ITEM.validate_json(item) for item in items]

    def replace(self, items: Iterable[Json]) -> None:
        self._items = tuple(_ITEM.dump_json(item) for item in items)

    def pop(self) -> Json:
        item = self._items[-1]
        self._items = self._items[:-1]
        return _ITEM.validate_json(item)

    def clear(self) -> None:
        self._items = ()

    def encoded(self) -> bytes:
        return _ITEMS.dump_json(tuple(self.read()))

    def __bool__(self) -> bool:
        return bool(self._items)
