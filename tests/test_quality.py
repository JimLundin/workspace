"""Workspace's interface policy gate and receipt protection."""

import ast
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.check_standards import Standard, background
from scripts.quality import imports
from tests.check_fixture import copy_check_scripts
from tests.git_fixture import initialized


def source_tree(root: Path, text: str) -> None:
    (root / "assistant").mkdir()
    (root / "assistant" / "api.py").write_text(text, encoding="utf-8")
    (root / "pyproject.toml").write_text("[tool.workspace.architecture]\n", encoding="utf-8")


def development_lint() -> None:
    if importlib.util.find_spec("ruff") is None:
        raise unittest.SkipTest("Ruff is a development tool; the installed selfcheck does not require it.")


def test_import_ownership_rejects_aliases_and_forwarding() -> None:
    text = (
        "from owner import Request as Request\nfrom owner import Reply as ConsoleReply\n"
        "import owner as api\nfrom owner import Event\n"
        'def local():\n    pass\n__all__ = ("Event", "local")\n'
    )
    found = tuple(imports("assistant/api.py", ast.parse(text)))
    assert tuple((item.rule, item.line) for item in found) == (("import-alias", 1), ("import-alias", 2), ("import-alias", 3), ("re-export", 7))
    assert not tuple(imports("assistant/api.py", ast.parse('from owner import Event\ndef local():\n    pass\n__all__ = ("local",)\n')))


def test_explicit_test_scope_cannot_bypass_quality_or_write_a_receipt(tmp_path: Path) -> None:
    development_lint()
    source_tree(tmp_path, "def update(enabled: bool):\n    pass\n")
    copy_check_scripts(tmp_path, ("check.py",))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_requested.py").write_text('def test_requested():\n    raise AssertionError("must not execute")\n')
    initialized(tmp_path)
    receipt = tmp_path / "checked.json"
    result = subprocess.run(
        (sys.executable, "-m", "scripts.check", "--tests", "tests/test_requested.py", "--receipt", str(receipt)),
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 1 and "FBT001" in result.stdout, result.stdout + result.stderr
    assert "must not execute" not in result.stdout and not receipt.exists()


def test_standards_fail_on_a_lint_error_outside_the_selected_tests_before_tests_or_a_receipt(tmp_path: Path) -> None:
    # Detect Dev.cmd check passing tree-wide lint errors again: the flag not
    # wired, a failing standard not blocking, or scope limited to the selection.
    development_lint()
    source_tree(tmp_path, "import os\n")
    copy_check_scripts(tmp_path, ("check.py",))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_requested.py").write_text('def test_requested():\n    raise AssertionError("must not execute")\n')
    initialized(tmp_path)
    receipt = tmp_path / "checked.json"
    result = subprocess.run(
        (sys.executable, "-m", "scripts.check", "--standards", "--tests", "tests/test_requested.py", "--receipt", str(receipt)),
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 1 and "F401" in result.stdout, result.stdout + result.stderr
    assert "must not execute" not in result.stdout and not receipt.exists()


def test_background_standards_report_each_failure_and_output_only_when_it_fails(tmp_path: Path) -> None:
    # Detect an overlapped standard losing its exit status or report,
    # including the second one when the first passes.
    passing = Standard("pyright", (sys.executable, "-c", "print('0 errors')"))
    failing = Standard("lint", (sys.executable, "-c", "print('api.py:1: error: unknown'); raise SystemExit(1)"))
    with background((passing, failing), tmp_path) as collect:
        failures = collect()
    assert [(failure.node, failure.summary) for failure in failures] == [("lint", "lint exited with status 1")]
    assert "api.py:1: error: unknown" in failures[0].report
    with background((passing, passing), tmp_path) as collect:
        assert collect() == ()
