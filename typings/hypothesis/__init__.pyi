"""Consumed Hypothesis API: synchronous tests with one generated argument."""

from collections.abc import Callable

from hypothesis.strategies import SearchStrategy

def given[T](strategy: SearchStrategy[T], /) -> Callable[[Callable[[T], None]], Callable[[], None]]: ...

class settings:
    def __init__(self, *, max_examples: int, derandomize: bool, database: None, deadline: None) -> None: ...
    def __call__[T](self, test: T) -> T: ...
