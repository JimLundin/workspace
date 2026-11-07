"""selfcheck: deciding whether a copy of Workspace is sound, with only Python."""

import os
import subprocess
import sys
from pathlib import Path

from selfcheck import ASSET_READERS, affected_tests, asset_readers, compile_all

SELFCHECK = Path(__file__).resolve().parent.parent / "selfcheck.py"


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def selfcheck(root: Path, *options: str) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    done = subprocess.run([sys.executable, str(SELFCHECK), str(root), *options], capture_output=True, text=True, timeout=60, env=env, check=False)
    return done.returncode, done.stdout + done.stderr


SOUND = {
    "tools/__init__.py": "",
    "tools/maths.py": "def double(x: int) -> int:\n    return 2 * x\n",
    "tests/__init__.py": "",
    "tests/test_maths.py": (
        "from pathlib import Path\n"
        "from tools.maths import double\n"
        "def test_double() -> None:\n    assert double(2) == 4\n"
        "def test_with_a_folder(tmp_path: Path) -> None:\n    (tmp_path / 'x').write_text('hi')\n    assert (tmp_path / 'x').read_text() == 'hi'\n"
    ),
    "tests/test_later.py": "import unittest\nraise unittest.SkipTest('not here')\n",
}


def test_a_sound_tree_passes(tmp_path: Path) -> None:
    code, report = selfcheck(tree(tmp_path, SOUND))
    assert code == 0, report
    assert "2 passed" in report
    assert "1 module skipped" in report


def test_worker_modules_report_their_passes_and_failures(tmp_path: Path) -> None:
    # Detect a failing test (here, one on a worker) dropped from the counts, the
    # report or the exit code, or reported without its traceback.
    files = {
        **SOUND,
        "tests/test_llm.py": "def test_worker_passes() -> None:\n    assert True\n",
        "tests/test_agent.py": "def test_worker_fails() -> None:\n    assert 1 == 2\n",
    }
    code, report = selfcheck(tree(tmp_path, files))
    assert code == 1, report
    assert "FAILED tests.test_agent.test_worker_fails" in report and "AssertionError" in report
    assert "3 passed, 1 failed" in report


def test_an_install_check_runs_last_failures_first_and_stops_at_the_first_failure(tmp_path: Path) -> None:
    # Defects: a retried fix that still fails waits behind every other module
    # before saying so, or the check keeps running modules after one failed,
    # or it hides that it stopped early.
    files = {
        **SOUND,
        "tests/test_a_first.py": "def test_passes() -> None:\n    assert True\n",
        "tests/test_z_last.py": "def test_still_broken() -> None:\n    assert False, 'still broken'\n",
    }
    root = tree(tmp_path / "tree", files)
    previous = tmp_path / "previous.txt"
    previous.write_text("FAILED tests.test_z_last.test_still_broken\nTraceback ...\n\n0 passed, 1 failed\n", encoding="utf-8")
    code, report = selfcheck(root, "--previous", str(previous), "--stop-at-first-failure")
    assert code == 1, report
    progress = [line.split()[1] for line in report.splitlines() if line.strip().endswith("failed") and ".py:" in line]
    assert progress == ["test_z_last.py:"], report
    assert "Stopped at the first failure: 3 affected test modules not run." in report
    code, report = selfcheck(root, "--previous", str(tmp_path / "absent.txt"))
    assert code == 1 and "test_a_first.py: 1 passed" in report and "Stopped" not in report


def test_a_change_runs_only_the_tests_that_import_it(tmp_path: Path) -> None:
    # Detect the scoped check running unaffected tests, missing a test that
    # reaches the change through a helper, or missing an asset's implicit readers.
    files = {
        **SOUND,
        "tools/other.py": "VALUE = 1\n",
        "tests/helper.py": "from tools.maths import double\n",
        "tests/test_through_helper.py": "from tests.helper import double\ndef test_helper() -> None:\n    assert double(1) == 2\n",
        "tests/test_other.py": "from tools.other import VALUE\ndef test_other() -> None:\n    assert VALUE == 1\n",
    }
    base = tree(tmp_path / "base", files)
    candidate = tree(tmp_path / "candidate", {**files, "tools/maths.py": "def double(x: int) -> int:\n    return x + x\n"})
    code, report = selfcheck(candidate, "--fast", "--changed-from", str(base))
    assert code == 0, report
    assert "3 passed" in report and "2 affected test modules" in report
    tree(candidate, {"tools/data.json": "{}"})
    code, report = selfcheck(candidate, "--fast", "--changed-from", str(base))
    assert code == 0 and "4 passed" in report, report


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
    root = SELFCHECK.parent
    if (root / ".git").exists():
        listed = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout.decode().split("\0")
    else:
        listed = [path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()]
    whole_suite = (".python-version", "requirements/")
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


def test_a_syntax_error_fails_in_modules_and_the_windowless_launcher(tmp_path: Path) -> None:
    # Defects: a module or the .pyw launcher that doesn't compile is installed.
    code, report = selfcheck(tree(tmp_path, {**SOUND, "tools/broken.py": "def oops(:\n", "workspace.pyw": "def broken(:\n"}))
    assert code == 1
    assert "doesn't compile: tools/broken.py" in report and "doesn't compile: workspace.pyw" in report


def test_a_module_that_cant_import_fails_and_missing_native_ui_is_skipped_only_off_windows(tmp_path: Path) -> None:
    # Defects: a module that can't import is installed, or a missing Qt/Win32
    # dependency is excused on Windows, where it is a real failure.
    native = {
        f"tools/native_{index}.py": f"raise ModuleNotFoundError(\"No module named '{name}'\")\n"
        for index, name in enumerate(("PySide6", "shiboken6", "win32more"))
    }
    code, report = selfcheck(tree(tmp_path, {**SOUND, **native, "tools/needs.py": "import no_such_thing\n"}))
    assert code == 1 and "doesn't import: tools.needs" in report, report
    excused = not any(f"doesn't import: tools.native_{index}" in report for index in range(3))
    assert excused is (sys.platform != "win32"), report


def test_a_crashing_test_module_fails(tmp_path: Path) -> None:
    code, report = selfcheck(tree(tmp_path, {**SOUND, "tests/test_bad.py": "raise RuntimeError('boom')\n"}))
    assert code == 1
    assert "boom" in report


def test_fast_checks_defer_native_tests_but_the_default_install_gate_runs_them(tmp_path: Path) -> None:
    root = tree(tmp_path, {**SOUND, "tests/test_windows_native.py": "def test_native():\n    assert False, 'native integration failed'\n"})
    code, report = selfcheck(root, "--fast")
    assert code == 0, report
    assert "2 passed" in report and "1 native module deferred" in report
    code, report = selfcheck(root)
    assert code == 1 and "FAILED tests.test_windows_native.test_native" in report
    # The keeper's remainder after a passing fast check: native modules only.
    code, report = selfcheck(root, "--native")
    assert code == 1 and "0 passed, 1 failed" in report, report


def test_fast_checks_still_compile_native_tests_and_import_production_modules(tmp_path: Path) -> None:
    root = tree(tmp_path, {**SOUND, "tests/test_windows_native.py": "def broken(:\n"})
    code, report = selfcheck(root, "--fast")
    assert code == 1 and "doesn't compile: tests/test_windows_native.py" in report
    (root / "tests/test_windows_native.py").unlink()
    tree(root, {"tools/broken.py": "import no_such_dependency\n"})
    code, report = selfcheck(root, "--fast")
    assert code == 1 and "doesn't import: tools.broken" in report


def test_compile_excludes_dependency_and_cache_sources(tmp_path: Path) -> None:
    root = tree(tmp_path, {**SOUND, **{f"{folder}/broken.py": "def broken(:\n" for folder in (".runtime", ".python", ".venv", "__pycache__")}})
    problems: list[str] = []
    compile_all(root, problems)
    assert not problems
