"""Development orchestration policies; OS event mechanics belong to Watchdog."""

import sys
from pathlib import Path

from scripts.watch import Settings, check_command, preview_change, source_path


def test_watch_uses_only_successful_session_baseline_and_keeps_native_scope(tmp_path: Path) -> None:
    # Detect a watch command comparing every save only to deployed bytes, losing
    # its source receipt, or silently dropping Windows coverage/function scope.
    receipt = tmp_path / "checked.json"
    settings = Settings(tests=("tests/test_windows_feed.py::test_source_badge_overlaps_and_title_shares_header_with_controls",))
    initial = check_command(settings, receipt)
    assert initial[:4] == (sys.executable, "-B", "-m", "scripts.check") and "--native" in initial
    assert initial[initial.index("--receipt") + 1] == str(receipt)
    assert initial[initial.index("--tests") + 1 :] == settings.tests
    receipt.write_text("{}")  # Presence represents the prior successful check; checker owns schema validation.
    following = check_command(settings, receipt)
    assert following[following.index("--baseline") + 1] == str(receipt)
    assert "--native" not in check_command(Settings(native=False), receipt)


def test_watch_filters_its_outputs_and_only_restarts_preview_for_production_changes(tmp_path: Path) -> None:
    # Detect self-triggered check storms or preview restarts for test/docs edits,
    # and losing deletion/rename paths after their source files no longer exist.
    root = tmp_path / "source"
    root.mkdir()
    removed = root / "assistant" / "removed.py"
    assert source_path(root, str(removed)) == removed
    for name in (".venv/installed.py", ".ruff_cache/entry", "__pycache__/model.pyc", ".env", "assistant/model.py.tmp"):
        assert source_path(root, str(root / name)) is None
    assert source_path(root, str(tmp_path / "outside.py")) is None
    assert source_path(root, str(root / "../outside.py")) is None
    assert not preview_change(root, frozenset({root / "tests/test_feed.py", root / "docs/notes.md"}))
    assert preview_change(root, frozenset({removed}))
