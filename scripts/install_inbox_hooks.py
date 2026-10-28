"""Install Workspace's opt-in console hooks without replacing existing hook handlers."""

import argparse
import copy
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

MARKER = "Workspace inbox"


def merged(original: dict[str, object], command: str, *, codex: bool) -> dict[str, object]:
    result = copy.deepcopy(original)
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Existing console hooks must be an object.")
    events = [("PreToolUse", r"(?:^|\.)(?:request_user_input|request_user_input_async)$" if codex else "^AskUserQuestion$", 600),
              ("PermissionRequest", "", 600), ("Stop", "", 10), ("SessionEnd", "", 3)]
    if codex:
        events.append(("Interrupt", "", 3))
    else:
        events.append(("Notification", "agent_needs_input|permission_prompt|elicitation_dialog", 10))
    for event, matcher, timeout in events:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError("Existing console hook events must be lists.")
        retained = []
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError("Invalid existing console matcher group.")
            handlers = group.get("hooks", [])
            if not isinstance(handlers, list):
                raise ValueError("Invalid existing console hook handlers.")
            keep = [handler for handler in handlers if not isinstance(handler, dict) or handler.get("statusMessage") != MARKER]
            if keep:
                retained.append({**group, "hooks": keep})
        handler: dict[str, object] = {"type": "command", "command": command, "timeout": timeout, "statusMessage": MARKER}
        if event in ("Stop", "Notification"):
            handler["async"] = True
        retained.append({"matcher": matcher, "hooks": [handler]})
        hooks[event] = retained
    return result


def install(path: Path, command: str, *, codex: bool) -> bool:
    current = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(current, dict):
        raise ValueError("Console configuration must be an object.")
    updated = merged(current, command, codex=codex)
    if updated == current:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(path.name + f".workspace-backup-{time.time_ns()}")
        backup.write_bytes(path.read_bytes())
        backup.chmod(0o600)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True)
    parser.add_argument("--script", required=True)
    parser.add_argument("--home", type=Path, default=Path.home())
    args = parser.parse_args()
    parts = (args.python, "-B", args.script)
    command = subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)
    changes = {"codex": install(args.home / ".codex" / "hooks.json", command, codex=True),
               "claude": install(args.home / ".claude" / "settings.json", command + " --claude", codex=False)}
    print(json.dumps({"workspace_hooks_updated": changes}))


if __name__ == "__main__":
    main()
