"""Which tests a change selects, and which import failures only mean the check isn't on Windows."""

import subprocess
import sys
from pathlib import Path

from scripts.selection import ASSET_READERS, affected_tests, asset_readers, windows_only

ROOT = Path(__file__).resolve().parent.parent


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_a_changed_asset_selects_the_tests_of_its_readers_only(tmp_path: Path) -> None:
    # Detect a known asset selecting the whole suite again (every deploy that
    # touched pyproject.toml ran all 133 modules), or missing a test that reaches
    # the asset's reader through a helper.
    root = tree(
        tmp_path,
        {
            "scripts/__init__.py": "",
            "scripts/quality.py": "",
            "tests/__init__.py": "",
            "tests/helper.py": "from scripts import quality\n",
            "tests/test_quality.py": "from tests.helper import quality\n",
            "tests/test_other.py": "import json\n",
        },
    )
    assert affected_tests(root, ["pyproject.toml"]) == {"tests/test_quality.py"}
    assert affected_tests(root, ["docs/notes.md", "AGENTS.md"]) == frozenset()
    assert affected_tests(root, ["tools/data.json"]) is None


def test_every_source_asset_names_readers_that_exist() -> None:
    # Detect a new asset that silently selects the whole suite on every change,
    # or a renamed reader that leaves an asset's tests unselected.
    root = ROOT
    if (root / ".git").exists():
        listed = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout.decode().split("\0")
    else:
        listed = [path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()]
    whole_suite = (".python-version", "uv.lock")
    assets = [
        name
        for name in listed
        if name
        and not name.endswith((".py", ".pyw", ".pyi"))
        and not any(part.startswith(".") or part == "__pycache__" for part in name.split("/"))
        and not name.startswith(whole_suite)
    ]
    assert [name for name in assets if asset_readers(name) is None] == []
    assert [reader for readers in ASSET_READERS.values() for reader in readers if not (root / reader).is_file()] == []


def test_a_missing_native_dependency_is_excused_only_off_windows() -> None:
    # Defects: a missing Qt or Win32 dependency is excused on Windows, where it
    # is a real failure, or an ordinary missing module is excused anywhere.
    native = ModuleNotFoundError("No module named 'PySide6'")
    assert windows_only(native) is (sys.platform != "win32")
    assert not windows_only(ModuleNotFoundError("No module named 'no_such_thing'"))
