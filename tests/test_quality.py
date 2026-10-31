"""Workspace's policy gate, exact migration ownership and receipt protection."""

import ast
import importlib.util
import json
import subprocess
import sys
import unittest
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from scripts.quality import Entry, Finding, Key, compare, imports, load, scan
from tests.check_fixture import copy_check_scripts

ROOT = Path(__file__).resolve().parent.parent


def source_tree(root: Path, text: str) -> None:
    (root / "assistant").mkdir()
    (root / "assistant" / "api.py").write_text(text, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[tool.workspace.architecture]\nmodels = []\n[tool.ruff.lint.pylint]\nmax-args = 3\nmax-positional-args = 5\n", encoding="utf-8"
    )


def migrations(root: Path, entries: Iterable[Entry] = ()) -> Path:
    path = root / "docs" / "quality-migrations.json"
    path.parent.mkdir(exist_ok=True)
    record = {
        "kind": "workspace-quality-migrations-v1",
        "entries": tuple(
            {
                "key": {"rule": entry.key.rule, "path": entry.key.path, "scope": entry.key.scope, "signature": entry.key.signature},
                "reason": entry.reason,
                "kind": entry.kind,
            }
            for entry in entries
        ),
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def development_lint() -> None:
    if importlib.util.find_spec("ruff") is None:
        raise unittest.SkipTest("Ruff is a development tool; the installed selfcheck does not require it.")


def test_gate_separates_blocking_violations_from_interface_review_warnings() -> None:
    positional = Finding(Key("FBT001", "assistant/api.py", "update.enabled", "1" * 64), 10, "Name the Boolean input.")
    oversized = Finding(replace(positional.key, rule="PLR0913", scope="update"), 10, "Review the input concept.")
    report = compare((positional, oversized), ())
    assert report.failures == (positional,) and report.warnings == (oversized,)
    accepted = Entry(positional.key, "Existing interface must migrate its callers.")
    report = compare((replace(positional, line=100), oversized), (accepted,))
    assert not report.failures and not report.stale and report.legacy == 1
    changed = replace(positional, key=replace(positional.key, signature="2" * 64))
    report = compare((changed,), (accepted,))
    assert report.failures == (changed,) and report.stale == (accepted,)


def test_boolean_gate_and_three_input_target_use_workspace_configuration(tmp_path: Path) -> None:
    development_lint()
    source_tree(
        tmp_path,
        "def named(*, enabled: bool):\n    pass\n"
        "def positional(enabled: bool):\n    pass\n"
        "def defaulted(enabled=True):\n    pass\n"
        "class Owner:\n"
        "    def three(self, first, second, *, third):\n        pass\n"
        "    def four(self, first, second, *, third, fourth):\n        pass\n",
    )
    report = compare(scan(tmp_path), ())
    assert {(item.key.rule, item.key.scope) for item in report.failures} == {("FBT001", "positional.enabled"), ("FBT002", "defaulted.enabled")}
    assert tuple(item.key.scope for item in report.warnings) == ("Owner.four",)


def test_signature_migration_survives_line_moves_but_cannot_cover_another_interface(tmp_path: Path) -> None:
    development_lint()
    original = "def update(enabled: bool):\n    pass\n"
    source_tree(tmp_path, original)
    observed = scan(tmp_path)
    entries = tuple(Entry(item.key, "Existing call sites await migration.") for item in observed)
    path = tmp_path / "assistant" / "api.py"
    path.write_text("\n\n" + original, encoding="utf-8")
    moved = compare(scan(tmp_path), entries)
    assert not moved.failures and not moved.stale and moved.legacy == 1
    path.write_text(original + original.replace("update", "another"), encoding="utf-8")
    added = compare(scan(tmp_path), entries)
    assert tuple(item.key.scope for item in added.failures) == ("another.enabled",)
    path.write_text(original.replace("enabled", "active"), encoding="utf-8")
    changed = compare(scan(tmp_path), entries)
    assert tuple(item.key.scope for item in changed.failures) == ("update.active",)
    assert changed.stale == entries


def test_import_ownership_rejects_aliases_and_forwarding_with_exact_keys() -> None:
    text = (
        "from owner import Request as Request\nfrom owner import Reply as ConsoleReply\n"
        "import owner as api\nfrom owner import Event\n"
        'def local():\n    pass\n__all__ = ("Event", "local")\n'
    )
    found = tuple(imports("assistant/api.py", ast.parse(text)))
    assert tuple(item.key.rule for item in found) == ("import-alias", "import-alias", "import-alias", "re-export")
    assert tuple(item.key for item in imports("assistant/api.py", ast.parse("\n\n" + text))) == tuple(item.key for item in found)
    entries = tuple(Entry(item.key, "Existing consumers await owner imports.") for item in found)
    assert not compare(found, entries).failures
    changed = tuple(imports("assistant/api.py", ast.parse(text.replace("ConsoleReply", "PrefixedReply"))))
    report = compare(changed, entries)
    assert len(report.failures) == 1 and len(report.stale) == 1
    assert not tuple(imports("assistant/api.py", ast.parse('from owner import Event\ndef local():\n    pass\n__all__ = ("local",)\n')))


def test_migration_schema_requires_unique_explained_exact_entries(tmp_path: Path) -> None:
    entry = Entry(Key("FBT001", "assistant/api.py", "update.enabled", "1" * 64), "Existing interface awaiting migration.")
    assert load(migrations(tmp_path, (entry,))) == (entry,)
    invalid = (
        (entry, entry),
        (replace(entry, reason=" "),),
        (replace(entry, key=replace(entry.key, path="../assistant/api.py")),),
        (replace(entry, key=replace(entry.key, scope="Owner.*")),),
        (replace(entry, key=replace(entry.key, signature="invalid")),),
    )
    for entries in invalid:
        try:
            load(migrations(tmp_path, entries))
        except ValueError:
            pass
        else:
            raise AssertionError("An invalid policy migration was accepted.")


def test_gate_blocks_imports_inside_function_bodies() -> None:
    inline = "def run():\n    from owner import activate\n    activate()\n"
    findings = tuple(imports("assistant/api.py", ast.parse(inline)))
    assert tuple(item.key.rule for item in compare(findings, ()).failures) == ("inline-import",)


def test_absolute_import_gate_covers_lazy_and_parent_imports(tmp_path: Path) -> None:
    # A missing level check would let explicit test scopes accept relative
    # dependencies even though ordinary Ruff lint rejects them.
    development_lint()
    source_tree(tmp_path, "from .owner import Event\nlazy from .. import model\nfrom assistant.owner import Local\n")
    report = compare(scan(tmp_path), ())
    assert tuple(item.key.rule for item in report.failures) == ("relative-import", "relative-import")
    assert tuple(item.line for item in report.failures) == (1, 2)
    entry = Entry(report.failures[0].key, "A migration must not relax the absolute import policy.")
    try:
        load(migrations(tmp_path, (entry,)))
    except ValueError:
        pass
    else:
        raise AssertionError("A relative import migration was accepted.")


def test_explicit_test_scope_cannot_bypass_quality_or_write_a_receipt(tmp_path: Path) -> None:
    development_lint()
    source_tree(tmp_path, "def update(enabled: bool):\n    pass\n")
    migrations(tmp_path)
    copy_check_scripts(tmp_path, ("check.py",))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_requested.py").write_text('def test_requested():\n    raise AssertionError("must not execute")\n')
    subprocess.run(("git", "init", "--quiet", str(tmp_path)), check=True, capture_output=True)
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


def test_reviewed_native_interface_remains_exact_and_cannot_excuse_boolean_or_import_violations(tmp_path: Path) -> None:
    # Detect counting a required ABI as migration debt, granting its exception
    # to a changed signature, or using interface status to permit forbidden code.
    native = Finding(Key("PLR0913", "native.py", "message", "1" * 64), 10, "Required native ABI.")
    accepted = Entry(native.key, "Win32 requires a window, message and two payload words.", "interface")
    assert load(migrations(tmp_path, (accepted,))) == (accepted,)
    report = compare((native,), (accepted,))
    assert report.legacy == 0 and report.interfaces == 1 and not report.warnings
    changed = replace(native, key=replace(native.key, signature="2" * 64))
    report = compare((changed,), (accepted,))
    assert report.warnings == (changed,) and report.stale == (accepted,)
    for rule in ("FBT001", "inline-import"):
        invalid = replace(accepted, key=replace(accepted.key, rule=rule))
        with unittest.TestCase().assertRaises(ValueError):
            load(migrations(tmp_path, (invalid,)))
