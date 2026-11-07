"""The release ZIP is the source alone: no dependencies, no binaries, no development state."""

import unittest
import zipfile
from pathlib import Path

from scripts.release import build, release


def test_the_release_holds_the_source_but_no_dependencies_binaries_or_development_state(tmp_path: Path) -> None:
    # Defects: a stale .runtime, the dev .venv or a cache ships with the release,
    # a binary slips in, or the source isn't under workspace/ where StartWorkspace.cmd runs.
    root = tmp_path / "checkout"
    for name, data in {
        ".python-version": b"3.15.1\n",
        "workspace.pyw": b"",
        "requirements/windows-py315.lock": b"pydantic==2 --hash=sha256:aa\n",
        ".runtime/PySide6/QtCore.pyd": b"old bundle",
        ".venv/Scripts/python.exe": b"dev",
        "assistant/__pycache__/app.cpython-315.pyc": b"cache",
    }.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    output = tmp_path / "dist/workspace.zip"
    assert build(output, root) == 3
    with zipfile.ZipFile(output) as archive:
        assert sorted(archive.namelist()) == ["workspace/.python-version", "workspace/requirements/windows-py315.lock", "workspace/workspace.pyw"]
    (root / "tools/helper.exe").parent.mkdir()
    (root / "tools/helper.exe").write_bytes(b"MZ")
    with unittest.TestCase().assertRaises(ValueError):
        build(output, root)


def test_pin_requires_a_python_315_release(tmp_path: Path) -> None:
    # Detect accepting a source release for an unsupported interpreter version.
    for version in ("3.12.5", "3.15", "3.15.x", "../3.15.1"):
        (tmp_path / ".python-version").write_text(version)
        with unittest.TestCase().assertRaises(ValueError):
            release(tmp_path)
    (tmp_path / ".python-version").write_text("3.15.1\n")
    assert release(tmp_path).minor == "3.15"
