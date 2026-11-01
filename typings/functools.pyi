"""Consumed caching and callback API; preserve result and parameter types."""

from collections.abc import Callable
from typing import Concatenate, NamedTuple, Protocol

class _CacheInfo(NamedTuple):
    hits: int
    misses: int
    maxsize: int | None
    currsize: int

class _lru_cache_wrapper[**P, R](Protocol):
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R: ...
    def cache_clear(self) -> None: ...
    def cache_info(self) -> _CacheInfo: ...

def lru_cache[**P, R](maxsize: int | None = 128, typed: bool = False) -> Callable[[Callable[P, R]], _lru_cache_wrapper[P, R]]: ...
def partial[T, **P, R](function: Callable[Concatenate[T, P], R], value: T, /) -> Callable[P, R]: ...
