"""selfcheck: deciding whether a copy of Workspace is sound, with only Python."""

import os
import subprocess
import sys
from pathlib import Path

from selfcheck import compile_all

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


def test_a_failing_test_fails(tmp_path: Path) -> None:
    files = {**SOUND, "tests/test_maths.py": "from tools.maths import double\ndef test_double() -> None:\n    assert double(2) == 5\n"}
    code, report = selfcheck(tree(tmp_path, files))
    assert code == 1
    assert "FAILED tests.test_maths.test_double" in report
    assert "AssertionError" in report


def test_a_syntax_error_fails(tmp_path: Path) -> None:
    code, report = selfcheck(tree(tmp_path, {**SOUND, "tools/broken.py": "def oops(:\n"}))
    assert code == 1
    assert "doesn't compile: tools/broken.py" in report


def test_a_module_that_cant_import_fails(tmp_path: Path) -> None:
    code, report = selfcheck(tree(tmp_path, {**SOUND, "tools/needs.py": "import no_such_thing\n"}))
    assert code == 1
    assert "doesn't import: tools.needs" in report


def test_missing_native_ui_dependencies_are_only_skipped_off_windows(tmp_path: Path) -> None:
    native = {
        f"tools/native_{index}.py": f"raise ModuleNotFoundError(\"No module named '{name}'\")\n"
        for index, name in enumerate(("PySide6", "shiboken6", "win32more"))
    }
    code, report = selfcheck(tree(tmp_path, {**SOUND, **native}))
    if sys.platform == "win32":
        assert code == 1 and all(f"doesn't import: tools.native_{index}" in report for index in range(3)), report
    else:
        assert code == 0 and "2 passed" in report, report


def test_a_crashing_test_module_fails(tmp_path: Path) -> None:
    code, report = selfcheck(tree(tmp_path, {**SOUND, "tests/test_bad.py": "raise RuntimeError('boom')\n"}))
    assert code == 1
    assert "boom" in report


def test_broken_windowless_launcher_fails(tmp_path: Path) -> None:
    code, report = selfcheck(tree(tmp_path, {**SOUND, "workspace.pyw": "def broken(:\n"}))
    assert code == 1
    assert "doesn't compile: workspace.pyw" in report


def test_fast_checks_defer_native_tests_but_the_default_install_gate_runs_them(tmp_path: Path) -> None:
    root = tree(tmp_path, {**SOUND, "tests/test_windows_native.py": "def test_native():\n    assert False, 'native integration failed'\n"})
    code, report = selfcheck(root, "--fast")
    assert code == 0, report
    assert "2 passed" in report and "1 native module deferred" in report
    code, report = selfcheck(root)
    assert code == 1 and "FAILED tests.test_windows_native.test_native" in report


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


def test_candidate_dependency_manifest_takes_precedence_over_the_checker_runtime(tmp_path: Path) -> None:
    # Detect checking against the launcher's bundle after selecting a candidate
    # that declares an incompatible adjacent runtime.
    candidate = tree(tmp_path, {**SOUND, ".runtime/manifest.json": '{"python": "3.99"}'})
    code, report = selfcheck(candidate)
    assert code == 1 and "Windows x64 Python 3.99" in report, report


def test_candidate_bootstrap_import_failure_is_not_hidden_by_the_checker_runtime(tmp_path: Path) -> None:
    # Detect skipping the selected copy's runtime because activation preloaded
    # the checker's module under the same import name.
    candidate = tree(tmp_path, {**SOUND, "runtime.py": "raise RuntimeError('candidate runtime failed')\n"})
    code, report = selfcheck(candidate)
    assert code == 1 and "doesn't import: runtime" in report and "candidate runtime failed" in report, report
