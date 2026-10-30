"""Console configuration preserves existing handlers and remains stable on reinstall."""

import json
from pathlib import Path
from typing import cast

from scripts.install_inbox_hooks import MARKER, install, merged
from tests.json_fixture import json_object


def test_installing_both_providers_preserves_unrelated_handlers_and_is_idempotent(tmp_path: Path) -> None:
    for codex in (True, False):
        previous: dict[str, list[dict[str, object]]] = {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "existing-handler"}]}],
            "CustomEvent": [{"hooks": [{"command": "another-handler"}]}],
        }
        original = {"unrelated": {"enabled": True}, "hooks": previous}
        current = tmp_path / ("codex.json" if codex else "claude.json")
        current.write_text(json.dumps(original))
        command = "python owned-hook.py"
        assert install(current, command, codex=codex)
        updated = cast(dict[str, object], json_object(current.read_text()))
        updated_hooks = cast(dict[str, list[dict[str, object]]], updated["hooks"])
        assert updated["unrelated"] == original["unrelated"]
        assert updated_hooks["PreToolUse"][0] == previous["PreToolUse"][0]
        assert updated_hooks["CustomEvent"] == previous["CustomEvent"]
        assert not install(current, command, codex=codex)
        changed = merged(updated, "python new-hook.py", codex=codex)
        hooks = cast(dict[str, list[dict[str, object]]], changed["hooks"])
        for event in ("PreToolUse", "PermissionRequest", "Stop", "SessionEnd"):
            owned = [
                handler
                for group in hooks[event]
                for handler in cast(list[dict[str, object]], group["hooks"])
                if handler.get("statusMessage") == MARKER
            ]
            assert len(owned) == 1 and owned[0]["command"] == "python new-hook.py"
        backups = list(tmp_path.glob(current.name + ".workspace-backup-*"))
        assert len(backups) == 1 and json_object(backups[0].read_text()) == original
