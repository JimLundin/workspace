"""The one place Workspace reassigns state: a cell holding one immutable value.

Every class we define is a frozen, slotted dataclass. An owner whose state
changes holds a `Cell` of a frozen state record and replaces the whole record on
each transition, so a reader always sees one consistent value:

    self.state.update(lambda state: replace(state, selected=note))

Standard library only, so the keyboard process can use it. A `set` is one
attribute store, atomic like any rebinding; `update` reads and then stores, so
an owner that updates from several threads serializes those updates itself.
"""

from collections.abc import Callable
from typing import override


class Cell[T]:
    __slots__ = ("_value",)

    def __init__(self, value: T) -> None:
        self._value = value

    def get(self) -> T:
        return self._value

    def set(self, value: T) -> None:
        self._value = value

    def update(self, change: Callable[[T], T]) -> T:
        """Replace the value with `change(value)` and return the new one."""
        self._value = value = change(self._value)
        return value

    @override
    def __repr__(self) -> str:
        return f"Cell({self._value!r})"
