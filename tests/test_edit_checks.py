"""Changed-source selection through actual imports, package initialization and deletion."""

import contextlib
import io
import sys
from pathlib import Path

from scripts.architecture import Report, dependencies
from scripts.check import (
    COST_RECORD,
    SUMMARY_LIMIT,
    CheckRun,
    ExecutionPlan,
    Options,
    RecordedFailure,
    Selection,
    combined_results,
    execute,
    execution_plan,
    publish_check,
    select,
    windows_only,
    worker_result,
)
from scripts.check_results import Failure


def tree(root: Path) -> dict[str, str]:
    text = {
        "app/__init__.py": "",
        "app/value.py": "value = 42\n",
        "app/api.py": "from .value import value\n",
        "tests/fixture.py": "from app import api\n",
        "tests/test_api.py": "from tests.fixture import api\n",
        "tests/test_other.py": "import json\n",
        "tests/test_windows_api.py": "from app.api import value\n",
    }
    for name, content in text.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return dict.fromkeys(text, "before")


def test_selection_follows_relative_imports_and_test_fixtures(tmp_path: Path) -> None:
    previous = tree(tmp_path)
    nested = "tests/properties/test_api.py"
    path = tmp_path / nested
    path.parent.mkdir()
    path.write_text("from tests.fixture import api\n")
    previous = previous | {nested: "before"}
    current = previous | {"app/value.py": "after"}
    result = select(tmp_path, current, previous)
    assert set(result.tests) == {"tests/test_api.py", nested}
    result = select(tmp_path, current, previous, native=True)
    assert set(result.tests) == {"tests/test_api.py", "tests/test_windows_api.py", nested}
    assert set(select(tmp_path, current, previous, full=True).tests) == {"tests/test_api.py", "tests/test_other.py", nested}


def test_package_initializer_and_deleted_source_select_consumers(tmp_path: Path) -> None:
    previous = tree(tmp_path)
    assert select(tmp_path, previous | {"app/__init__.py": "after"}, previous).tests == ("tests/test_api.py",)
    current = {name: digest for name, digest in previous.items() if name != "app/value.py"}
    (tmp_path / "app/value.py").unlink()
    assert select(tmp_path, current, previous).tests == ("tests/test_api.py",)


def test_broad_changes_fall_back_to_full_suite(tmp_path: Path) -> None:
    previous = tree(tmp_path)
    for name in ("runtime.py", "requirements/windows-py315.lock", "app/assets.js"):
        result = select(tmp_path, previous | {name: "after"}, previous)
        assert set(result.tests) == {"tests/test_api.py", "tests/test_other.py"}
    assert select(tmp_path, previous, previous).tests == ()
    assert set(select(tmp_path, previous, previous, full=True).tests) == {"tests/test_api.py", "tests/test_other.py"}


def test_static_dynamic_imports_and_ancestors_are_dependencies() -> None:
    imports = dependencies("app/sub/source.py", 'from .. import api\nimport app.value\nimportlib.import_module("app.more.value")\n')
    assert {"app", "app.api", "app.value", "app.more", "app.more.value"} <= imports


def test_editing_checks_do_not_hide_local_import_or_runtime_failures() -> None:
    assert not windows_only(ImportError("missing_workspace_module"))
    assert not windows_only(RuntimeError("PySide6 initialization failed"))
    assert windows_only(ImportError("PySide6 missing")) is (sys.platform != "win32")


REJECTION = "expected 2 drafts, saw 3 " + "x" * 600


class SourceFixture:
    """Own the fixture's ordered load observations; no process globals change."""

    def __init__(self) -> None:
        self.order: list[str] = []

    def activate(self) -> None:
        pass

    def compile(self, root: Path, failures: list[str]) -> None:
        pass

    def import_all(self, root: Path, failures: list[str]) -> None:
        self.order.append("imports")
        failures.append("A dependency does not import")

    def load(self, module: str) -> object:
        if module == "assistant.sdk":
            self.order.append("sdk")
            return None
        assert module == __name__
        return self

    def test_requested(self) -> None:
        self.order.append("generated")
        assert "sdk" not in self.order and "imports" not in self.order

    def test_rejected(self) -> None:
        raise AssertionError(REJECTION)


def test_function_selection_runs_the_requested_case_and_rejects_typos(tmp_path: Path) -> None:
    runtime = SourceFixture()
    name = __name__.replace(".", "/") + ".py"
    passed, skipped, failures, _ = execute(Selection((name + "::test_requested",), (), "explicit iteration scope"), tmp_path, runtime)
    assert (passed, skipped, failures) == (1, 0, ()) and runtime.order == ["generated"]
    passed, _, failures, _ = execute(Selection((name + "::test_missing",), (), "explicit iteration scope"), tmp_path, runtime)
    missing = name + "::test_missing"
    assert passed == 0 and failures == (Failure(missing, "No test function matched", "No test function matched " + missing),)


def test_generated_checks_precede_broad_dependency_imports_and_keep_import_gate(tmp_path: Path) -> None:
    # A loader presents a concrete module whose function owns the fixture state.
    # The same loaded test is used in narrow and broad runtime lifetimes.
    runtime = SourceFixture()
    name = "tests/properties/test_order.py"

    class PropertyRuntime(SourceFixture):
        def load(self, module: str) -> object:
            if module == "tests.properties.test_order":
                return module_fixture
            return super().load(module)

    def generated() -> None:
        runtime.order.append("generated")
        assert "sdk" not in runtime.order and "imports" not in runtime.order

    generated.__module__ = "tests.properties.test_order"

    class PropertyModule:
        test_order = staticmethod(generated)

    module_fixture = PropertyModule()
    for sdk_present in (False, True):
        runtime = PropertyRuntime()
        if sdk_present:
            sdk = tmp_path / "assistant" / "sdk.py"
            sdk.parent.mkdir()
            sdk.write_text("# SDK boundary")
        passed, skipped, failures, _ = execute(Selection((name,), (), "full source checks"), tmp_path, runtime)
        assert runtime.order == (["generated", "sdk", "imports"] if sdk_present else ["generated", "imports"])
        problem = Failure("import all production modules", "A dependency does not import", "A dependency does not import")
        assert (passed, skipped, failures) == (1, 0, (problem,))
    runtime = PropertyRuntime()
    passed, skipped, failures, _ = execute(Selection((name,), (), "explicit iteration scope"), tmp_path, runtime)
    assert runtime.order == ["generated"] and (passed, skipped, failures) == (1, 0, ())


def test_failed_checks_keep_cost_evidence_naming_each_failure_without_a_receipt(tmp_path: Path) -> None:
    # Defects: a failed check discarded its durations, or its retained record
    # could not say which test failed or why once console output was lost.
    report, receipt = tmp_path / "timings.json", tmp_path / "receipt.json"
    name = __name__.replace(".", "/") + ".py"
    selected = Selection((name + "::test_rejected",), (), "explicit iteration scope")
    passed, skipped, failures, timings = execute(selected, tmp_path, SourceFixture())
    durations = (*timings, (50.0, "worker:tests.test_agent.test_refusal"))
    current = frozendict({name: "checked-source"})
    options = Options(full=False, native=False, tests=selected.tests, timings=report, receipt=receipt, baseline=tmp_path)
    run = CheckRun(current, selected, (passed, skipped, failures, durations), Report((), (), ()), 80)
    console = io.StringIO()
    with contextlib.redirect_stdout(console):
        assert publish_check(options, run)
    record = COST_RECORD.validate_json(report.read_bytes())
    assert record.failures == (RecordedFailure(name + "::test_rejected", f"AssertionError: {REJECTION}"[:SUMMARY_LIMIT]),)
    assert (record.passed, record.failed, record.files, record.durations, record.worker_seconds) == (0, 1, current, durations, 50.0)
    assert "Traceback" in console.getvalue() and not receipt.exists()


def test_broad_workers_keep_desktop_ownership_exact_selection_and_failures() -> None:
    selectors: tuple[str, ...] = (
        "tests/test_agent.py::test_declined",
        "tests/test_work_store.py",
        "tests/test_windows_browser.py",
        "tests/test_unreviewed.py",
    )
    plan = execution_plan(selectors)
    assert plan == ExecutionPlan(selectors[:2], selectors[2:])
    assert execution_plan(selectors[2:]) == ExecutionPlan((), selectors[2:])
    assert execution_plan(selectors[:2]) == ExecutionPlan((), selectors[:2])
    # Our aggregation must preserve failed child assertions and attribute child
    # costs separately from the sequential desktop lane's elapsed work.
    refusal = Failure("tests/test_agent.py::test_declined", "AssertionError", "Refusal failed")
    child = worker_result((1, 0, (refusal,), ((2.0, "tests.test_agent.test_declined"),)))
    other = worker_result((3, 1, (), ((1.0, "module:tests.test_work_store"),)))
    parent = (4, 0, (), ((3.0, "tests.test_windows_browser.test_owned"),))
    passed, skipped, failures, durations = combined_results((parent, child, other))
    assert (passed, skipped, failures) == (8, 1, (refusal,))
    assert (2.0, "worker:tests.test_agent.test_declined") in durations
    assert (1.0, "worker:module:tests.test_work_store") in durations
