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
        self._value = value = change(self._value)
        return value

    @override
    def __repr__(self) -> str:
        return f"Cell({self._value!r})"
