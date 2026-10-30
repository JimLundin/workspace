"""Dependency bundles omit executables while retaining native Qt libraries."""

import unittest
import zipfile
from pathlib import Path

from scripts.bundle import extract, release


def test_dependency_extraction_omits_executables_and_bytecode_but_keeps_native_modules(tmp_path: Path) -> None:
    archive = tmp_path / "dependency.whl"
    removed = ("PySide6/designer.exe", "dependency/__pycache__/module.pyc", "dependency.data/scripts/tool.py")
    kept = ("PySide6/Qt6Core.dll", "PySide6/QtSvg.pyd", "dependency/module.py")
    with zipfile.ZipFile(archive, "w") as output:
        for name in (*removed, *kept):
            output.writestr(name, name.encode())
    folder = tmp_path / "runtime"
    extract(archive, folder)
    assert all(not (folder / name).exists() for name in removed)
    assert all((folder / name).read_text() == name for name in kept)


def test_pin_requires_a_python_315_release(tmp_path: Path) -> None:
    # Detect accepting a dependency ABI for an unsupported interpreter version.
    for version in ("3.12.5", "3.15", "3.15.x", "../3.15.1"):
        (tmp_path / ".python-version").write_text(version)
        with unittest.TestCase().assertRaises(ValueError):
            release(tmp_path)
    (tmp_path / ".python-version").write_text("3.15.1\n")
    assert release(tmp_path).tag == "315"
