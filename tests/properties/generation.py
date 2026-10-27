"""Configure bounded Hypothesis campaigns for the existing callable test runner."""

from collections.abc import Callable

from hypothesis import given, settings
from hypothesis.strategies import DrawFn, SearchStrategy, composite


def cases[T](build: Callable[[DrawFn], T]) -> SearchStrategy[T]:
    factory: Callable[[], SearchStrategy[T]] = composite(build)
    return factory()


def property_test[T](strategy: SearchStrategy[T]) -> Callable[[Callable[[T], None]], Callable[[], None]]:
    decorate = given(strategy)

    def configured(test: Callable[[T], None]) -> Callable[[], None]:
        return settings(max_examples=100, derandomize=True, database=None, deadline=None)(decorate(test))

    return configured
