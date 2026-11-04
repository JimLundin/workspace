"""Policy behavior through the same source review used by editing checks."""

import json
import subprocess
import sys
from pathlib import Path

from scripts.architecture import dependencies, python_sources, review
from tests.check_fixture import copy_check_scripts
from tests.git_fixture import initialized


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


def process_tree(root: Path) -> None:
    write_tree(
        root,
        {
            "automation/__init__.py": "",
            "automation/entry.py": "lazy import assistant.shared\nlazy import automation.app\n",
            "automation/app.py": "lazy import assistant.work\n",
            "assistant/__init__.py": "",
            "assistant/entry.py": "lazy import assistant.shared\nlazy import assistant.desktop\n",
            "assistant/shared.py": "",
            "assistant/work.py": "lazy import assistant.shared\n",
            "assistant/desktop.py": "",
            "assistant/other.py": "",
            "assistant/unreachable.py": "lazy import assistant.other\n",
        },
    )
    with (root / "pyproject.toml").open("a", encoding="utf-8") as output:
        output.write(
            'desktop_only = ["assistant.desktop"]\n'
            'work_only = ["assistant.work"]\n'
            'shared = ["assistant", "assistant.shared"]\n'
            '\n[tool.workspace.architecture.processes]\nwork = "automation.entry"\ndesktop = "assistant.entry"\n'
            '\n[[tool.workspace.architecture.seams]]\nmodule = "automation.entry"\nreason = "Worker shared settings."\n'
            '\n[[tool.workspace.architecture.seams]]\nmodule = "automation.app"\nreason = "Worker composition."\n'
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
            "helper/__init__.py": "from desktop_ui import model\n",
            "helper/values.py": "value = 1\n",
            "assistant/__init__.py": "",
            "assistant/model.py": "",
            "desktop_ui/__init__.py": "",
            "desktop_ui/model.py": "",
        },
    )
    report = review(tmp_path)
    assert report.failures and all(finding.rule == "keyboard-isolation" for finding in report.failures)
    assert any("miryoku.engine → helper → desktop_ui" in finding.detail for finding in report.failures)
    (tmp_path / "helper/__init__.py").write_text("")
    assert not review(tmp_path).failures


def test_lower_layers_reach_assistant_only_through_declared_seams(tmp_path: Path) -> None:
    # Defect: an automation or winapi module imports a UI-side module, directly or
    # through a shared helper, or a seam outlives the dependency it documents.
    write_tree(
        tmp_path,
        {
            "automation/__init__.py": "",
            "automation/ipc.py": "from helper import value\n",
            "winapi/__init__.py": "",
            "winapi/status.py": "from desktop_ui.model import Model\n",
            "automation/app.py": "lazy from assistant.model import Model\n",
            "helper.py": "from assistant import model\nvalue = 1\n",
            "assistant/__init__.py": "",
            "assistant/model.py": "",
            "desktop_ui/__init__.py": "",
            "desktop_ui/model.py": "",
        },
    )
    with (tmp_path / "pyproject.toml").open("a", encoding="utf-8") as output:
        output.write('\n[[tool.workspace.architecture.seams]]\nmodule = "automation.app"\nreason = "The composition root."\n')
    assert [finding.detail for finding in review(tmp_path).failures] == ["automation.ipc → helper → assistant", "winapi.status → desktop_ui"]
    (tmp_path / "helper.py").write_text("value = 1\n")
    (tmp_path / "winapi/status.py").write_text("")
    assert not review(tmp_path).failures
    (tmp_path / "automation/app.py").write_text("")
    assert [finding.rule for finding in review(tmp_path).failures] == ["stale-seam"]


def test_worker_cannot_reach_desktop_only_modules(tmp_path: Path) -> None:
    # Defect: work isolation stops at an allowed composition seam, misses a
    # transitive lazy import, or rejects an owner the work process cannot reach.
    write_tree(
        tmp_path,
        {
            "automation/__init__.py": "",
            "automation/__main__.py": "lazy from assistant.settings import config\nlazy from automation.app import run\n",
            "automation/app.py": "lazy from assistant.tools import run\n",
            "assistant/__init__.py": "",
            "assistant/settings.py": "config = 1\n",
            "assistant/tools.py": "lazy import desktop_ui.session\n",
            "desktop_ui/__init__.py": "",
            "desktop_ui/session.py": "",
            "assistant/unreachable.py": "lazy import desktop_ui.session\n",
        },
    )
    with (tmp_path / "pyproject.toml").open("a", encoding="utf-8") as output:
        output.write(
            'desktop_only = ["desktop_ui"]\n'
            '\n[[tool.workspace.architecture.seams]]\nmodule = "automation.__main__"\nreason = "Worker settings."\n'
            '\n[[tool.workspace.architecture.seams]]\nmodule = "automation.app"\nreason = "Worker composition."\n'
        )
    failures = review(tmp_path).failures
    assert all(failure.rule == "worker-isolation" and failure.module == "automation.__main__" for failure in failures)
    assert {failure.detail for failure in failures} == {
        "automation.__main__ → automation.app → assistant.tools → desktop_ui",
        "automation.__main__ → automation.app → assistant.tools → desktop_ui.session",
    }
    (tmp_path / "assistant/tools.py").write_text("", encoding="utf-8")
    assert not review(tmp_path).failures


def test_headless_owners_reject_indirect_ui_and_native_qt_imports(tmp_path: Path) -> None:
    # Defect: a controller gains a view dependency through a shared contract or
    # a lazy native import, while process isolation still permits that route.
    write_tree(
        tmp_path,
        {
            "assistant/__init__.py": "",
            "assistant/owner.py": "lazy import assistant.contract\n",
            "assistant/contract.py": "lazy from desktop_ui.view import View\n",
            "desktop_ui/__init__.py": "",
            "desktop_ui/view.py": "class View: pass\n",
        },
    )
    with (tmp_path / "pyproject.toml").open("a", encoding="utf-8") as output:
        output.write('headless = ["assistant.owner"]\n')
    failures = review(tmp_path).failures
    assert failures and all(failure.rule == "ui-isolation" for failure in failures)
    assert any("assistant.owner → assistant.contract → desktop_ui.view" in failure.detail for failure in failures)
    contract = tmp_path / "assistant/contract.py"
    contract.write_text("lazy from PySide6.QtWidgets import QWidget\n", encoding="utf-8")
    assert any("PySide6.QtWidgets" in failure.detail for failure in review(tmp_path).failures)
    contract.write_text("", encoding="utf-8")
    assert not review(tmp_path).failures


def test_presentation_cannot_import_concrete_logic_owners_through_contracts(tmp_path: Path) -> None:
    # Defect: a view starts importing a concrete controller through a shared
    # contract, recreating lifecycle coupling despite the headless-owner rule.
    write_tree(
        tmp_path,
        {
            "assistant/__init__.py": "",
            "assistant/owner.py": "",
            "assistant/contract.py": "lazy import assistant.owner\n",
            "desktop_ui/__init__.py": "",
            "desktop_ui/view.py": "lazy import assistant.contract\n",
        },
    )
    with (tmp_path / "pyproject.toml").open("a", encoding="utf-8") as output:
        output.write('ui_private = ["assistant.owner"]\n')
    (failure,) = review(tmp_path).failures
    assert failure.rule == "presentation-isolation"
    assert failure.detail == "desktop_ui.view → assistant.contract → assistant.owner"
    (tmp_path / "assistant/contract.py").write_text("", encoding="utf-8")
    assert not review(tmp_path).failures


def test_work_imports_require_exact_process_declarations_through_seams(tmp_path: Path) -> None:
    # Defect: configured roots or composition seams hide an undeclared work
    # import, a package declaration grants its children access, or an unrelated
    # desktop import is mistaken for work reachability.
    process_tree(tmp_path)
    assert not review(tmp_path).failures
    (tmp_path / "assistant/work.py").write_text("lazy import assistant.shared\nlazy import assistant.other\n", encoding="utf-8")
    (failure,) = review(tmp_path).failures
    assert failure.rule == "process-declaration" and failure.module == "automation.entry"
    assert failure.detail.endswith("automation.entry → automation.app → assistant.work → assistant.other")
    config = tmp_path / "pyproject.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace('work_only = ["assistant.work"]', 'work_only = ["assistant.work", "assistant.other"]')
    )
    assert not review(tmp_path).failures
    (tmp_path / "assistant/work.py").write_text("lazy import assistant.shared\nlazy import assistant.desktop\n", encoding="utf-8")
    config.write_text(config.read_text(encoding="utf-8").replace(', "assistant.other"', ""))
    (failure,) = review(tmp_path).failures
    assert failure.rule == "worker-isolation" and failure.module == "automation.entry"


def test_desktop_imports_of_work_owners_require_shared_ownership(tmp_path: Path) -> None:
    # Defect: a new desktop consumer loads a declared work-only owner without
    # review, or the checker refuses the accurate shared declaration afterward.
    process_tree(tmp_path)
    (tmp_path / "assistant/entry.py").write_text("lazy import assistant.shared\nlazy import assistant.desktop\nlazy import assistant.work\n")
    (failure,) = review(tmp_path).failures
    assert failure.rule == "process-ownership" and failure.detail.endswith("assistant.entry → assistant.work")
    config = tmp_path / "pyproject.toml"
    config.write_text(
        config.read_text(encoding="utf-8")
        .replace('work_only = ["assistant.work"]', "work_only = []")
        .replace('shared = ["assistant", "assistant.shared"]', 'shared = ["assistant", "assistant.shared", "assistant.work"]')
    )
    assert not review(tmp_path).failures


def test_process_declarations_cannot_outlive_their_consumers_or_entry(tmp_path: Path) -> None:
    # Defect: removing a consumer leaves a misleading work/shared declaration,
    # or a missing configured entry silently disables the ownership check.
    process_tree(tmp_path)
    (tmp_path / "automation/app.py").write_text("lazy import assistant.shared\n")
    (failure,) = review(tmp_path).failures
    assert failure.rule == "stale-process" and failure.module == "assistant.work"
    config = tmp_path / "pyproject.toml"
    config.write_text(config.read_text(encoding="utf-8").replace('work_only = ["assistant.work"]', "work_only = []"))
    (tmp_path / "assistant/entry.py").write_text("lazy import assistant.desktop\n")
    (failure,) = review(tmp_path).failures
    assert failure.rule == "stale-process" and failure.module == "assistant.shared"
    (tmp_path / "assistant/entry.py").unlink()
    (failure,) = review(tmp_path).failures
    assert failure.rule == "process-entry" and failure.module == "assistant.entry"


def test_process_declarations_reject_conflicting_or_inexact_ownership(tmp_path: Path) -> None:
    # Defect: duplicate/conflicting declarations or package wildcards turn one
    # reviewed owner into broader permission; omitting roots disables the rule.
    declarations = (
        'work_only = ["assistant.work", "assistant.work"]',
        'work_only = ["assistant.work", "assistant.shared"]',
        'work_only = ["assistant.work", "assistant.desktop"]',
        'work_only = ["assistant.*"]',
    )
    for declaration in declarations:
        process_tree(tmp_path)
        config = tmp_path / "pyproject.toml"
        config.write_text(config.read_text(encoding="utf-8").replace('work_only = ["assistant.work"]', declaration))
        try:
            review(tmp_path)
        except ValueError:
            pass
        else:
            raise AssertionError("An ambiguous process declaration was accepted.")
    process_tree(tmp_path)
    config = tmp_path / "pyproject.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            '[tool.workspace.architecture.processes]\nwork = "automation.entry"\ndesktop = "assistant.entry"\n', ""
        )
    )
    try:
        review(tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError("Process declarations without roots were accepted.")


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
            "miryoku/__init__.py": "",
            "miryoku/engine.py": "import assistant\n",
            "assistant/__init__.py": "",
            "tests/test_requested.py": 'def test_requested():\n    raise AssertionError("must not execute")\n',
        },
    )
    copy_check_scripts(tmp_path, ("check.py",))
    initialized(tmp_path)
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
