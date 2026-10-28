"""Console configuration preserves existing handlers and remains stable on reinstall."""

import json
from pathlib import Path

from scripts.install_inbox_hooks import MARKER, install, merged


def test_installing_both_providers_preserves_unrelated_handlers_and_is_idempotent(tmp_path: Path) -> None:
    for codex in (True, False):
        original = {"unrelated": {"enabled": True}, "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "existing-handler"}]},
        ], "CustomEvent": [{"hooks": [{"command": "another-handler"}]}]}}
        current = tmp_path / ("codex.json" if codex else "claude.json")
        current.write_text(json.dumps(original))
        command = "python owned-hook.py"
        assert install(current, command, codex=codex)
        updated = json.loads(current.read_text())
        assert updated["unrelated"] == original["unrelated"]
        assert updated["hooks"]["PreToolUse"][0] == original["hooks"]["PreToolUse"][0]
        assert updated["hooks"]["CustomEvent"] == original["hooks"]["CustomEvent"]
        assert not install(current, command, codex=codex)
        changed = merged(updated, "python new-hook.py", codex=codex)
        for event in ("PreToolUse", "PermissionRequest", "Stop", "SessionEnd"):
            owned = [handler for group in changed["hooks"][event] for handler in group["hooks"]
                     if handler.get("statusMessage") == MARKER]
            assert len(owned) == 1 and owned[0]["command"] == "python new-hook.py"
        backups = list(tmp_path.glob(current.name + ".workspace-backup-*"))
        assert len(backups) == 1 and json.loads(backups[0].read_text()) == original
