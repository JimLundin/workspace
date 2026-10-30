"""Policy behavior through the same source review used by editing checks."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.architecture import dependencies, python_sources, review

ROOT = Path(__file__).resolve().parent.parent


def write_tree(root: Path, files: dict[str, str], *, models: tuple[str, ...] = ()) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / "pyproject.toml").write_text("[tool.workspace.architecture]\nmodels = " + json.dumps(models) + "\n", encoding="utf-8")


def exception(root: Path, *, reason: str = "Read the optional native error code.") -> None:
    with (root / "pyproject.toml").open("a", encoding="utf-8") as output:
        output.write(
            "\n[[tool.workspace.architecture.exceptions]]\n"
            'rule = "explicit-attributes"\nmodule = "native"\ndeclaration = "Owner.read"\n'
            "expression = \"getattr(error, 'winerror', None)\"\nreason = " + json.dumps(reason) + "\n"
        )


def test_recursive_inventory_excludes_dependencies_and_honors_checked_names(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "assistant/__init__.py": "",
            "assistant/feed/__init__.py": "",
            "assistant/feed/model.py": "",
            "runtime.py": "",
            "scripts/owner.py": "",
            ".venv/package.py": "",
            ".runtime/package.py": "",
            "__pycache__/ignored.py": "",
        },
    )
    assert python_sources(tmp_path) == (
        "assistant/__init__.py",
        "assistant/feed/__init__.py",
        "assistant/feed/model.py",
        "runtime.py",
        "scripts/owner.py",
    )
    assert python_sources(tmp_path, ("runtime.py", "deleted.py")) == ("runtime.py",)


def test_keyboard_rejection_follows_lazy_imports_and_package_initializers(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "miryoku/__init__.py": "",
            "miryoku/engine.py": "lazy from helper.values import value\n",
            "helper/__init__.py": "from assistant import model\n",
            "helper/values.py": "value = 1\n",
            "assistant/__init__.py": "",
            "assistant/model.py": "",
        },
    )
    report = review(tmp_path)
    assert report.failures and all(finding.rule == "keyboard-isolation" for finding in report.failures)
    assert any("miryoku.engine → helper → assistant" in finding.detail for finding in report.failures)
    (tmp_path / "helper/__init__.py").write_text("")
    assert not review(tmp_path).failures


def test_relative_lazy_and_aliased_dynamic_imports_select_their_consumers() -> None:
    imported = dependencies(
        "app/nested/owner.py", 'lazy from .. import model\nfrom importlib import import_module as load\nload("app.effects.native")\n'
    )
    assert {"app", "app.model", "app.effects", "app.effects.native"} <= imported


def test_keyboard_cannot_hide_dependencies_in_unresolved_dynamic_imports(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "miryoku/__init__.py": "",
            "miryoku/engine.py": "from importlib import import_module as load\ndef start(target):\n    return load(target)\n",
        },
    )
    assert [finding.rule for finding in review(tmp_path).failures] == ["keyboard-import"]


def test_immutable_data_is_default_even_outside_declared_model_modules(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "assistant/__init__.py": "",
            "assistant/feed/__init__.py": "",
            "assistant/feed/model.py": "from dataclasses import dataclass as variant\n@variant(slots=True)\nclass Payload:\n    value: str\n",
            "assistant/worker.py": "from dataclasses import dataclass\n@dataclass(frozen=True, slots=True)\nclass Buffer:\n    value: str\n",
        },
        models=("assistant.worker",),
    )
    report = review(tmp_path)
    assert [(finding.rule, finding.module, finding.declaration) for finding in report.failures] == [
        ("immutable-data", "assistant.feed.model", "Payload")
    ]
    (tmp_path / "assistant/feed/model.py").write_text(
        "import dataclasses as data\n@data.dataclass(frozen=True, slots=True)\nclass Payload:\n    value: str\n"
    )
    assert not review(tmp_path).failures
    (tmp_path / "assistant/worker.py").unlink()
    assert [finding.rule for finding in review(tmp_path).failures] == ["model-coverage"]


def test_a_frozen_record_cannot_hide_a_mutable_collection(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "owner.py": "from dataclasses import dataclass\n"
            "@dataclass(frozen=True, slots=True)\nclass Snapshot:\n    values: tuple[dict[str, str], ...]\n"
        },
    )
    assert [(finding.rule, finding.declaration) for finding in review(tmp_path).failures] == [("mutable-field", "Snapshot.values")]


def test_exact_reflection_exception_survives_lines_but_cannot_cover_other_declarations(tmp_path: Path) -> None:
    write_tree(tmp_path, {"native.py": '\n\nclass Owner:\n    def read(self, error):\n        return getattr(error, "winerror", None)\n'})
    exception(tmp_path)
    report = review(tmp_path)
    assert not report.failures and len(report.exceptions) == 1
    with (tmp_path / "native.py").open("a") as output:
        output.write('    def other(self, error):\n        return getattr(error, "winerror", None)\n')
    assert [finding.declaration for finding in review(tmp_path).failures] == ["Owner.other"]
    (tmp_path / "native.py").write_text("class Owner:\n    def read(self, error):\n        return error\n")
    assert [finding.rule for finding in review(tmp_path).failures] == ["stale-exception"]


def test_reflection_aliases_are_detected_without_leaking_between_functions(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "owner.py": "import builtins as native\n"
            'def first(value):\n    from builtins import getattr as read\n    return read(value, "state")\n'
            'def second(value):\n    read = native.getattr\n    return read(value, "state")\n'
            'def third(value):\n    return native.hasattr(value, "state")\n'
        },
    )
    assert {finding.declaration for finding in review(tmp_path).failures} == {"first", "second", "third"}


def test_unsupported_and_unexplained_exceptions_are_configuration_errors(tmp_path: Path) -> None:
    write_tree(tmp_path, {})
    exception(tmp_path, reason="")
    try:
        review(tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError("An unexplained exception was accepted.")


def test_explicit_test_scope_cannot_bypass_architecture_or_write_a_receipt(tmp_path: Path) -> None:
    write_tree(
        tmp_path,
        {
            "scripts/__init__.py": "",
            "scripts/deploy_files.py": "",
            "miryoku/__init__.py": "",
            "miryoku/engine.py": "import assistant\n",
            "assistant/__init__.py": "",
            "tests/test_requested.py": 'def test_requested():\n    raise AssertionError("must not execute")\n',
        },
    )
    for name in ("architecture.py", "quality.py", "check.py", "deploy_files.py", "development_paths.py", "source_analysis.py"):
        shutil.copyfile(ROOT / "scripts" / name, tmp_path / "scripts" / name)
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    receipt = tmp_path / "checked.json"
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check", "--tests", "tests/test_requested.py", "--receipt", str(receipt)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 1 and "keyboard-isolation" in result.stdout
    assert "must not execute" not in result.stdout and not receipt.exists()


def test_mock_frameworks_and_replacement_fixtures_are_rejected_in_all_sources(tmp_path: Path) -> None:
    cases = (
        'from unittest.mock import patch as replace\nreplace("owner.effect")\n',
        "import unittest.mock as replacement\nreplacement.Mock()\n",
        'from unittest import mock\nmock.patch.object(owner, "effect")\n',
        "from pytest import MonkeyPatch as Replacement\nReplacement()\n",
        'def test_effect(monkeypatch):\n    monkeypatch.setattr(owner, "effect", lambda: None)\n',
        'def test_effect(mocker):\n    mocker.patch("owner.effect")\n',
        'import importlib\nimportlib.import_module("unittest.mock")\n',
    )
    for text in cases:
        write_tree(tmp_path, {"owner.py": text, "tests/test_owner.py": text})
        failures = review(tmp_path).failures
        assert {finding.module for finding in failures if finding.rule == "testing-dependencies"} == {"owner", "tests.test_owner"}
    write_tree(
        tmp_path,
        {
            "owner.py": "def observe(reader):\n    return reader()\n",
            "tests/test_owner.py": "from owner import observe\ndef test_read():\n    assert observe(lambda: 7) == 7\n",
        },
    )
    assert not review(tmp_path).failures


def test_current_working_tree_satisfies_declared_architecture() -> None:
    report = review(ROOT)
    assert not report.failures, "\n".join(finding.describe() for finding in report.failures)
