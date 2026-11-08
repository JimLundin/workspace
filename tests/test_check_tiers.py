"""The editing tier's selection and its per-test time budget."""

from pathlib import Path

from scripts.check_results import Selection
from scripts.check_tiers import (
    NATIVE_BUDGET_S,
    NATIVE_SLOW,
    SLOW,
    editing,
    over_budget,
    over_native_budget,
    test_functions,
)

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
        (2.5, "worker:tests.test_agent.test_slow"),
        (1.6, "tests.properties.test_pcm.test_generated"),
        (1.4, "tests.test_agent.test_quick"),
        (9.0, "phase:import changed source"),
        (3.0, "worker:module:tests.test_agent"),
    )
    assert [(failure.node, failure.summary) for failure in over_budget(durations)] == [
        ("tests/test_agent.py::test_slow", "took 2.5 s, over the 1.5 s editing budget"),
        ("tests/properties/test_pcm.py::test_generated", "took 1.6 s, over the 1.5 s editing budget"),
    ]


# At most this many slow portable and native tests: adding one beyond a cap means removing or fixing another.
SLOW_CAP, NATIVE_SLOW_CAP = 30, 12


def test_every_slow_entry_names_an_existing_test_with_a_reason_within_its_cap() -> None:
    # Defects: a renamed or deleted test leaves a stale entry that no longer
    # defers anything, an entry carries no reason for being slow, or the lists
    # grow past their caps instead of a slow test being fixed.
    for entries, cap in ((SLOW, SLOW_CAP), (NATIVE_SLOW, NATIVE_SLOW_CAP)):
        missing = [entry for entry in entries if entry.partition("::")[2] not in test_functions(ROOT / entry.partition("::")[0])]
        assert not missing, missing
        assert all(reason.strip() for reason in entries.values())
        assert len(entries) <= cap, f"{len(entries)} slow tests, over the cap of {cap}"
    assert all(Path(entry).name.startswith("test_windows_") for entry in NATIVE_SLOW)
    assert not any(Path(entry.partition("::")[0]).name.startswith("test_windows_") for entry in SLOW)


def test_a_native_test_over_its_budget_fails_by_name_unless_listed() -> None:
    # Defects: a slow native test passes unnoticed, a listed exception fails
    # anyway, or a portable test is held to the native budget.
    listed = sorted(NATIVE_SLOW)[0].replace("/", ".").replace(".py::", ".")
    durations = (
        (NATIVE_BUDGET_S + 1, "worker:tests.test_windows_bar.test_slow"),
        (NATIVE_BUDGET_S + 9, listed),
        (NATIVE_BUDGET_S - 1, "tests.test_windows_bar.test_quick"),
        (NATIVE_BUDGET_S + 1, "tests.test_agent.test_portable"),
    )
    assert [failure.node for failure in over_native_budget(durations)] == ["tests/test_windows_bar.py::test_slow"]
