"""Every class we define uses slots, so instances can't grow attributes that
nobody declared. Enums, exceptions, protocols, tuples, ctypes structures,
Qt objects, SDK lifecycle hooks, and stdlib threading events manage their own storage. TypedDicts describe dicts,
not instances of an application class."""

import importlib
import inspect
import sys
from collections.abc import Iterator
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import is_typeddict

from scripts.architecture import module_name, python_sources

ROOT = Path(__file__).resolve().parent.parent


def modules() -> list[ModuleType]:
    """Every module of Workspace. Off Windows, the ones that need Windows are skipped."""
    names = [module_name(name) for name in python_sources(ROOT) if name.endswith('.py') and not name.startswith('tests/')]
    found: list[ModuleType] = []
    for name in names:
        try:
            found.append(importlib.import_module(name))
        except (ImportError, AttributeError, OSError):
            if sys.platform == "win32":
                raise
    return found


def exempt(cls: type) -> bool:
    bases = [(base.__module__, base.__qualname__) for base in cls.__mro__]
    return (
        is_typeddict(cls)
        or issubclass(cls, (Enum, BaseException, tuple))
        or ("typing", "Protocol") in bases
        or any(module in ("ctypes", "_ctypes") for module, _ in bases)
        or ("agents.lifecycle", "RunHooksBase") in bases
        or ("PySide6.QtCore", "QObject") in bases
        or ("threading", "Event") in bases
    )


def missing_classes(module: ModuleType) -> Iterator[str]:
    for name, value in inspect.getmembers(module):
        match value:
            case type() if value.__module__ == module.__name__ and not exempt(value) and value.__dictoffset__ != 0:
                yield f"{module.__name__}.{name}"
            case _:
                pass


def test_every_class_uses_slots() -> None:
    # A class's instances have no __dict__ (so no undeclared attributes) exactly
    # when __dictoffset__ is 0, which needs __slots__ on it and all its bases.
    missing = tuple(name for module in modules() for name in missing_classes(module))
    assert not missing, f"classes without __slots__: {missing}"
