"""Dependency ABI validation before activation changes process state."""

import os
import sys
from pathlib import Path
from unittest import TestCase

from runtime import Interpreter, activate, validate_dependencies


def test_dependency_abi_is_checked_before_native_modules_are_loaded(tmp_path: Path) -> None:
    dependencies = tmp_path / ".runtime"
    dependencies.mkdir()
    (dependencies / "manifest.json").write_text('{"python": "3.99", "platform": "win_amd64"}')
    search_path, environment = tuple(sys.path), dict(os.environ)
    with TestCase().assertRaisesRegex(RuntimeError, "Python 3.99.*StartWorkspace.cmd"):
        activate(dependencies)
    assert tuple(sys.path) == search_path and dict(os.environ) == environment


def test_manifest_requires_the_declared_python_and_windows_abi() -> None:
    invalid: tuple[object, ...] = (None, [1], dict[str, str](), {"python": "3"}, {"python": "3.x"}, {"python": 3.15})
    for metadata in invalid:
        with TestCase().assertRaisesRegex(RuntimeError, "no valid Python version"):
            validate_dependencies(metadata, Interpreter("win32", (3, 15), 8))
    for platform, version, size in (("linux", (3, 15), 8), ("win32", (3, 12), 8), ("win32", (3, 15), 4)):
        with TestCase().assertRaisesRegex(RuntimeError, "Windows x64 Python 3.15"):
            validate_dependencies({"python": "3.15"}, Interpreter(platform, version, size))
    validate_dependencies({"python": "3.15"}, Interpreter("win32", (3, 15), 8))
