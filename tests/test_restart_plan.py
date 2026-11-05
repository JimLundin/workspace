"""Which programs an install restarts, from both versions' import closures."""

from pathlib import Path

from keeper import PROTECTED, source_tree
from restart_plan import Relaunch, RestartChildren, RestartPlan, restart_plan

SOURCE = {
    "keeper.py": "import keeper_control\nimport supervisor_support\n",
    "keeper_control.py": "",
    "supervisor_support.py": "value = 1\n",
    "miryoku/__init__.py": "",
    "miryoku/__main__.py": "from miryoku import engine\n",
    "miryoku/engine.py": "import protocol\n",
    "assistant/__init__.py": "",
    "assistant/__main__.py": "from assistant import app\n",
    "assistant/app.py": "import protocol\nimport retired\nimport desktop_ui.ui\nlazy from automation import worker\n",
    "automation/__init__.py": "",
    "automation/worker.py": "value = 1\n",
    "desktop_ui/__init__.py": "",
    "desktop_ui/ui.py": "value = 1\n",
    "protocol.py": "value = 1\n",
    "retired.py": "value = 1\n",
    "docs/note.md": "before\n",
    "pyproject.toml": "before\n",
}


def plan(tmp_path: Path, edits: dict[str, str], removed: tuple[str, ...] = ()) -> RestartPlan:
    before, after = tmp_path / "before", tmp_path / "after"
    for root, files in ((before, SOURCE), (after, {name: text for name, text in SOURCE.items() if name not in removed} | edits)):
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")
    return restart_plan(source_tree(before), source_tree(after), PROTECTED)


def test_restart_plan_tracks_shared_removed_lazy_and_package_dependencies(tmp_path: Path) -> None:
    # Detect selecting by directory alone, dropping consumers of removed imports,
    # missing a lazy import or package initializer in a child's lifetime, or
    # keeping the keeper running on changed keeper code.
    cases: tuple[tuple[dict[str, str], tuple[str, ...], RestartPlan], ...] = (
        ({"assistant/app.py": "import protocol\nimport retired\nvalue = 2\n"}, (), RestartChildren(("assistant",))),
        ({"automation/worker.py": "value = 2\n"}, (), RestartChildren(("assistant",))),
        ({"desktop_ui/__init__.py": "value = 2\n"}, (), RestartChildren(("assistant",))),
        ({"protocol.py": "value = 2\n"}, (), RestartChildren(("layout", "assistant"))),
        ({"assistant/app.py": "import protocol\n"}, ("retired.py",), RestartChildren(("assistant",))),
        ({"miryoku/__init__.py": "value = 2\n"}, (), RestartChildren(("layout",))),
        ({"keeper_control.py": "value = 2\n"}, (), Relaunch.KEEPER),
        ({"supervisor_support.py": "value = 2\n"}, (), Relaunch.KEEPER),
        ({"pyproject.toml": "after\n"}, (), RestartChildren(("layout", "assistant"))),
        ({"docs/note.md": "after\n"}, (), RestartChildren(())),
    )
    for index, (edits, removed, expected) in enumerate(cases):
        assert plan(tmp_path / str(index), edits, removed) == expected, edits
