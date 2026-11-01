"""Consumed pytest API: a bare fixture decorator on a plugin method and the in-process session entry point."""

from collections.abc import Callable, Sequence

class FixtureFunctionDefinition: ...

# The consumed fixture is a plugin method that takes only its instance.
def fixture[S](fixture_function: Callable[[S], object]) -> FixtureFunctionDefinition: ...

# pytest's ExitCode is an IntEnum, so every result is an int.
def main(args: list[str] | None = None, plugins: Sequence[object] | None = None) -> int: ...
