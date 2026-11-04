"""Workspace's interface policy gate and receipt protection."""

import ast
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.check_standards import TYPES, Standard, background
from scripts.quality import imports, scan
from tests.check_fixture import copy_check_scripts
from tests.git_fixture import initialized

ROOT = Path(__file__).resolve().parent.parent


def source_tree(root: Path, text: str) -> None:
    (root / "assistant").mkdir()
    (root / "assistant" / "api.py").write_text(text, encoding="utf-8")
    (root / "pyproject.toml").write_text("[tool.workspace.architecture]\nmodels = []\n[tool.ruff.lint.pylint]\nmax-args = 5\n", encoding="utf-8")


def development_lint() -> None:
    if importlib.util.find_spec("ruff") is None:
        raise unittest.SkipTest("Ruff is a development tool; the installed selfcheck does not require it.")


def test_boolean_and_wide_signature_gate_blocks_unless_a_reason_is_given(tmp_path: Path) -> None:
    development_lint()
    source_tree(
        tmp_path,
        "def named(*, enabled: bool):\n    pass\n"
        "def positional(enabled: bool):\n    pass\n"
        "def defaulted(enabled=True):\n    pass\n"
        "class Owner:\n"
        "    def five(self, a, b, c, *, d, e):\n        pass\n"
        "    def six(self, a, b, c, *, d, e, f):\n        pass\n"
        "    def native(self, a, b, c, d, e, f):  # noqa: PLR0913 - required native ABI\n        pass\n",
    )
    assert tuple((item.rule, item.line) for item in scan(tmp_path)) == (("FBT001", 3), ("FBT002", 5), ("PLR0913", 10))


def test_import_ownership_rejects_aliases_and_forwarding() -> None:
    text = (
        "from owner import Request as Request\nfrom owner import Reply as ConsoleReply\n"
        "import owner as api\nfrom owner import Event\n"
        'def local():\n    pass\n__all__ = ("Event", "local")\n'
    )
    found = tuple(imports("assistant/api.py", ast.parse(text)))
    assert tuple((item.rule, item.line) for item in found) == (("import-alias", 1), ("import-alias", 2), ("import-alias", 3), ("re-export", 7))
    assert not tuple(imports("assistant/api.py", ast.parse('from owner import Event\ndef local():\n    pass\n__all__ = ("local",)\n')))


def test_gate_blocks_imports_inside_function_bodies() -> None:
    inline = "def run():\n    from owner import activate\n    activate()\n"
    findings = tuple(imports("assistant/api.py", ast.parse(inline)))
    assert tuple(item.rule for item in findings) == ("inline-import",)


def test_absolute_import_gate_covers_lazy_and_parent_imports(tmp_path: Path) -> None:
    # A missing level check would let explicit test scopes accept relative
    # dependencies even though ordinary Ruff lint rejects them.
    development_lint()
    source_tree(tmp_path, "from .owner import Event\nlazy from .. import model\nfrom assistant.owner import Local\n")
    assert tuple((item.rule, item.line) for item in scan(tmp_path)) == (("relative-import", 1), ("relative-import", 2))


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
    # Detect an overlapped type checker losing its exit status or report,
    # including the second checker when the first passes.
    passing = Standard("pyright", (sys.executable, "-c", "print('0 errors')"))
    failing = Standard("mypy", (sys.executable, "-c", "print('api.py:1: error: unknown'); raise SystemExit(1)"))
    with background((passing, failing), tmp_path) as collect:
        failures = collect()
    assert [(failure.node, failure.summary) for failure in failures] == [("mypy", "mypy exited with status 1")]
    assert "api.py:1: error: unknown" in failures[0].report
    with background((passing, passing), tmp_path) as collect:
        assert collect() == ()


def test_the_type_standards_run_both_checkers_over_the_whole_tree() -> None:
    # Detect Dev.cmd check dropping mypy (or pyright) from its type gate, or
    # narrowing either checker to the selected files.
    assert [(standard.node, standard.command[1:3], standard.command[-1]) for standard in TYPES] == [
        ("pyright", ("-m", "pyright"), sys.executable),
        ("mypy", ("-m", "mypy"), "."),
    ]
