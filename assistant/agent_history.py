"""Volatile conversation storage; parsed SDK collections never remain shared."""

from collections.abc import Iterable
from dataclasses import dataclass, field

from pydantic import TypeAdapter

from cell import Cell
from contracts.json_value import Json

_ITEM = TypeAdapter(Json)
_ITEMS = TypeAdapter(tuple[Json, ...])


@dataclass(frozen=True, slots=True)
class History:
    """Own session IO across serialized executions, retaining immutable wire bytes.

    The execution owner retains this handle, and its SDK session is the sole
    writer during a run. Parsing gives the SDK fresh collections each time;
    neither SDK edits nor callers can mutate a retained conversation item.
    History stays in memory, including opaque reasoning and recent images.
    Durable checkpoints retain structural progress through their own adapter.
    """

    _items: Cell[tuple[bytes, ...]] = field(default_factory=lambda: Cell[tuple[bytes, ...]](()), repr=False)

    def read(self, limit: int | None = None) -> list[Json]:
        held = self._items.get()
        items = held if limit is None else held[-limit:] if limit > 0 else ()
        return [_ITEM.validate_json(item) for item in items]

    def replace(self, items: Iterable[Json]) -> None:
        self._items.set(tuple(_ITEM.dump_json(item) for item in items))

    def pop(self) -> Json:
        *kept, item = self._items.get()
        self._items.set(tuple(kept))
        return _ITEM.validate_json(item)

    def clear(self) -> None:
        self._items.set(())

    def encoded(self) -> bytes:
        return _ITEMS.dump_json(tuple(self.read()))

    def __bool__(self) -> bool:
        return bool(self._items.get())
