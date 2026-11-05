"""The editing tier's selection and its per-test time budget."""

from pathlib import Path

from scripts.check_results import Selection
from scripts.check_tiers import SLOW, editing, over_budget, test_functions

ROOT = Path(__file__).resolve().parent.parent


def test_editing_tier_drops_native_modules_and_slow_tests_but_keeps_their_neighbours(tmp_path: Path) -> None:
    # Defects: the editing check runs a native module or a registered slow test,
    # or drops a slow test's fast neighbours along with it.
    (slow_module, slow_function) = sorted(SLOW)[0].split("::")
    module = tmp_path / slow_module
    module.parent.mkdir(parents=True)
    module.write_text(f"def {slow_function}() -> None: ...\n\n\ndef test_fast() -> None: ...\n\n\ndef helper() -> None: ...\n", encoding="utf-8")
    selection = Selection((slow_module, "tests/test_windows_bar.py", "tests/test_other.py"), ("assistant/bar.py",), "direct")
    assert editing(selection, tmp_path) == Selection((f"{slow_module}::test_fast", "tests/test_other.py"), ("assistant/bar.py",), "direct")
    named = Selection((sorted(SLOW)[0], "tests/test_other.py::test_x"), (), "direct")
    assert editing(named, tmp_path).tests == ("tests/test_other.py::test_x",)


def test_a_test_over_budget_fails_by_name_and_phases_never_do() -> None:
    # Defects: a slow editing test passes silently, its failure names a label the
    # selector syntax cannot rerun, or a long phase or module import is blamed.
    durations = (
        (1.5, "worker:tests.test_agent.test_slow"),
        (1.2, "tests.properties.test_pcm.test_generated"),
        (0.4, "tests.test_agent.test_quick"),
        (9.0, "phase:import changed source"),
        (3.0, "worker:module:tests.test_agent"),
    )
    assert [(failure.node, failure.summary) for failure in over_budget(durations)] == [
        ("tests/test_agent.py::test_slow", "took 1.5 s, over the 1 s editing budget"),
        ("tests/properties/test_pcm.py::test_generated", "took 1.2 s, over the 1 s editing budget"),
    ]


def test_every_slow_entry_names_an_existing_test() -> None:
    # Defect: a renamed or deleted test leaves a stale entry that no longer defers anything.
    missing = [entry for entry in SLOW if entry.partition("::")[2] not in test_functions(ROOT / entry.partition("::")[0])]
    assert not missing, missing
