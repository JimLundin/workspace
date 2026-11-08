"""Changed-source selection through actual imports, package initialization and deletion."""

import contextlib
import io
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import override

from scripts.architecture import Report
from scripts.check import (
    COST_RECORD,
    POOL_MINIMUM,
    SUMMARY_LIMIT,
    CheckRun,
    ExecutionPlan,
    Options,
    RecordedFailure,
    combined_results,
    execute,
    execution_plan,
    publish_check,
    sdk_packages,
    select,
    windows_only,
    worker_result,
)
from scripts.check_results import Failure, Results, Selection, raised


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
    current = previous | {"app/api.py": "after"}
    result = select(tmp_path, current, previous)
    assert set(result.tests) == {"tests/test_api.py", nested}
    result = select(tmp_path, current, previous, native=True)
    assert set(result.tests) == {"tests/test_api.py", "tests/test_windows_api.py", nested}
    # Production imports are not followed: value.py reaches tests only through api.py.
    assert select(tmp_path, previous | {"app/value.py": "after"}, previous).tests == ()
    assert set(select(tmp_path, current, previous, full=True).tests) == {"tests/test_api.py", "tests/test_other.py", nested}


def test_package_initializer_and_deleted_source_select_consumers(tmp_path: Path) -> None:
    previous = tree(tmp_path)
    assert select(tmp_path, previous | {"app/__init__.py": "after"}, previous).tests == ("tests/test_api.py",)
    current = {name: digest for name, digest in previous.items() if name != "app/api.py"}
    (tmp_path / "app/api.py").unlink()
    assert select(tmp_path, current, previous).tests == ("tests/test_api.py",)


def test_pins_and_unknown_assets_fall_back_to_full_suite_but_known_assets_select_their_readers_tests(tmp_path: Path) -> None:
    # Defect: a changed asset selects the whole suite again, or one with unknown readers selects too little.
    previous = tree(tmp_path)
    for name in ("uv.lock", "app/assets.js"):
        result = select(tmp_path, previous | {name: "after"}, previous)
        assert set(result.tests) == {"tests/test_api.py", "tests/test_other.py"}
    # Defect: a page script beside its module changes without selecting that module's tests.
    assert select(tmp_path, previous | {"app/api.observe.js": "after"}, previous).tests == ("tests/test_api.py",)
    (tmp_path / "tests/test_quality.py").write_text("from scripts import quality\n")
    previous = previous | {"tests/test_quality.py": "before"}
    assert select(tmp_path, previous | {"pyproject.toml": "after"}, previous).tests == ("tests/test_quality.py",)
    # Repository configuration and type stubs have no test readers.
    assert select(tmp_path, previous | {".gitattributes": "after", "typings/lib.pyi": "after"}, previous).tests == ()
    assert select(tmp_path, previous, previous).tests == ()
    assert set(select(tmp_path, previous, previous, full=True).tests) == {"tests/test_api.py", "tests/test_other.py", "tests/test_quality.py"}


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

    def import_all(self, root: Path) -> Iterable[str]:
        self.order.append("imports")
        return ("A dependency does not import",)

    def load(self, module: str) -> object:
        assert module == __name__
        return self

    def test_requested(self) -> None:
        self.order.append("generated")
        print("expected warning from a passing case", file=sys.stderr)
        assert "imports" not in self.order

    def test_rejected(self) -> None:
        print("diagnostic before the rejection", file=sys.stderr)
        raise AssertionError(REJECTION)


def test_function_selection_runs_the_requested_case_and_rejects_typos(tmp_path: Path) -> None:
    # Defect: a passing case's expected stderr still reached the check console.
    runtime = SourceFixture()
    name = __name__.replace(".", "/") + ".py"
    console = io.StringIO()
    with contextlib.redirect_stderr(console):
        result = execute(Selection((name + "::test_requested",), (), "explicit iteration scope"), tmp_path, runtime)
    assert (result.passed, result.skipped, result.failures) == (1, 0, ()) and runtime.order == ["generated"]
    assert console.getvalue() == ""
    missing = name + "::test_missing"
    result = execute(Selection((missing,), (), "explicit iteration scope"), tmp_path, runtime)
    assert result.passed == 0 and result.failures == (Failure(missing, "No test function matched", "No test function matched " + missing),)


def test_generated_checks_precede_broad_dependency_imports_and_keep_import_gate(tmp_path: Path) -> None:
    # A loader presents a concrete module whose function owns the fixture state.
    # The same loaded test is used in narrow and broad runtime lifetimes.
    runtime = SourceFixture()
    name = "tests/properties/test_order.py"

    class PropertyRuntime(SourceFixture):
        @override
        def load(self, module: str) -> object:
            if module == "tests.properties.test_order":
                return module_fixture
            return super().load(module)

    def generated() -> None:
        runtime.order.append("generated")
        assert "imports" not in runtime.order

    generated.__module__ = "tests.properties.test_order"

    class PropertyModule:
        test_order = staticmethod(generated)

    module_fixture = PropertyModule()
    runtime = PropertyRuntime()
    result = execute(Selection((name,), (), "full source checks"), tmp_path, runtime)
    assert runtime.order == ["generated", "imports"]
    problem = Failure("import all production modules", "A dependency does not import", "A dependency does not import")
    assert (result.passed, result.skipped, result.failures) == (1, 0, (problem,))
    runtime = PropertyRuntime()
    result = execute(Selection((name,), (), "explicit iteration scope"), tmp_path, runtime)
    assert runtime.order == ["generated"] and (result.passed, result.skipped, result.failures) == (1, 0, ())


def test_failed_checks_keep_cost_evidence_naming_each_failure_without_a_receipt(tmp_path: Path) -> None:
    # Defects: a failed check discarded its durations, its retained record
    # could not say which test failed or why once console output was lost,
    # or capturing stderr hid what the failing test wrote before it failed.
    report, receipt = tmp_path / "timings.json", tmp_path / "receipt.json"
    name = __name__.replace(".", "/") + ".py"
    selected = Selection((name + "::test_rejected",), (), "explicit iteration scope")
    result = execute(selected, tmp_path, SourceFixture())
    durations = (*result.durations, (50.0, "worker:tests.test_agent.test_refusal"))
    current = frozendict({name: "checked-source"})
    options = Options(full=False, native=False, standards=False, tests=selected.tests, timings=report, receipt=receipt, baseline=tmp_path)
    run = CheckRun(current, selected, Results(result.passed, result.skipped, result.failures, durations), Report((), (), ()), 80)
    console = io.StringIO()
    with contextlib.redirect_stdout(console):
        assert publish_check(options, run)
    record = COST_RECORD.validate_json(report.read_bytes())
    assert record.failures == (RecordedFailure(name + "::test_rejected", f"AssertionError: {REJECTION}"[:SUMMARY_LIMIT]),)
    assert (record.passed, record.failed, record.files, record.durations, record.worker_seconds) == (0, 1, current, durations, 50.0)
    assert "Traceback" in console.getvalue() and not receipt.exists()
    assert "Captured stderr:\ndiagnostic before the rejection\n" in console.getvalue()


def test_broad_workers_keep_desktop_ownership_exact_selection_and_failures() -> None:
    # Defects: a native module runs in a worker, a known heavy module doesn't lead
    # the queue, a selector loses its function, or a few modules (however many
    # selectors name them) wait for workers to start.
    unreviewed = tuple(f"tests/test_unreviewed_{index}.py" for index in range(POOL_MINIMUM - 2))
    selectors: tuple[str, ...] = (
        *unreviewed,
        "tests/test_windows_ambient.py",
        "tests/test_features.py",
        "tests/test_meetings.py::test_declined",
    )
    plan = execution_plan(selectors)
    assert plan == ExecutionPlan(("tests/test_meetings.py::test_declined", "tests/test_features.py", *unreviewed), ("tests/test_windows_ambient.py",))
    assert execution_plan(selectors[2:]) == ExecutionPlan((), selectors[2:])
    # One module's functions, as the editing tier names a module with slow tests, start no pool.
    functions = tuple(f"tests/test_agent.py::test_{index}" for index in range(POOL_MINIMUM))
    assert execution_plan(functions) == ExecutionPlan((), functions)
    # Our aggregation must preserve failed child assertions and attribute child
    # costs separately from the sequential desktop lane's elapsed work.
    refusal = Failure("tests/test_agent.py::test_declined", "AssertionError", "Refusal failed")
    child = worker_result(Results(1, 0, (refusal,), ((2.0, "tests.test_agent.test_declined"),)))
    other = worker_result(Results(3, 1, (), ((1.0, "module:tests.test_work_store"),)))
    parent = Results(4, 0, (), ((3.0, "tests.test_windows_browser.test_owned"),))
    combined = combined_results((parent, child, other))
    assert (combined.passed, combined.skipped, combined.failures) == (8, 1, (refusal,))
    assert (2.0, "worker:tests.test_agent.test_declined") in combined.durations
    assert (1.0, "worker:module:tests.test_work_store") in combined.durations


def test_the_sdk_is_imported_before_timing_only_for_tests_that_load_it(tmp_path: Path) -> None:
    # Defects: a test that loads the SDK through a Workspace module pays its cold
    # import inside the time budget, or a test that only reaches it lazily (and so
    # never loads it unless it runs an agent) pays seconds for nothing.
    files = {
        "app/__init__.py": "",
        "app/model.py": "from app import client\n",
        "app/client.py": "import openai\n",
        "app/agent.py": "lazy import openai\n",
        "tests/test_model.py": "from app.model import x\n",
        "tests/test_agent.py": "from app import agent\n",
        "tests/test_pure.py": "import os\n",
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert sdk_packages(("tests/test_model.py::test_one", "tests/test_pure.py"), tmp_path) == ("openai",)
    assert sdk_packages(("tests/test_agent.py", "tests/test_pure.py"), tmp_path) == ()


def test_a_failure_summary_says_where_in_the_source_it_was_raised() -> None:
    # Defect: the retained record keeps only "TimeoutError", so a flaky failure
    # seen once under load can't be located after its console is gone.
    def wait() -> None:
        raise TimeoutError

    try:
        wait()
    except TimeoutError as error:
        failure = raised("tests/test_x.py::test_y", error)
    else:
        raise AssertionError("wait() returned")
    assert failure.summary.startswith("TimeoutError at tests/test_edit_checks.py:"), failure.summary
