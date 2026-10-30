"""Install Workspace's opt-in console hooks without replacing existing hook handlers."""

import argparse
import copy
import inspect
import json
import os
import shlex
import subprocess
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

MARKER = "Workspace inbox"


@runtime_checkable
class ObjectFields(Protocol):
    def items(self) -> Iterable[tuple[object, object]]: ...


@runtime_checkable
class Elements(Protocol):
    def __iter__(self) -> Iterator[object]: ...


def configuration(value: object) -> dict[str, object]:
    """Validate hook objects without importing the application's Python 3.15 runtime."""
    match value, value:
        case dict(), ObjectFields() as fields:
            pass
        case _:
            raise ValueError("Console configuration must be an object.")
    result: dict[str, object] = {}
    for key, field in fields.items():
        match key:
            case str():
                result[key] = field
            case _:
                raise ValueError("Console configuration keys must be strings.")
    return result


def entries(value: object) -> Iterable[object]:
    """Validate the JSON array before consuming only its iteration interface."""
    match value, value:
        case list(), Elements() as elements:
            return elements
        case _:
            raise ValueError("Existing console hook events and handlers must be lists.")


def merged(original: dict[str, object], command: str, *, codex: bool) -> dict[str, object]:
    result = copy.deepcopy(original)
    hooks = configuration(result.get("hooks", {}))
    events = [
        ("PreToolUse", r"(?:^|\.)(?:request_user_input|request_user_input_async)$" if codex else "^AskUserQuestion$", 600),
        ("PermissionRequest", "", 600),
        ("Stop", "", 10),
        ("SessionEnd", "", 3),
    ]
    if codex:
        events.append(("Interrupt", "", 3))
    else:
        events.append(("Notification", "agent_needs_input|permission_prompt|elicitation_dialog", 10))
    for event, matcher, timeout in events:
        retained: list[dict[str, object]] = []
        for group in entries(hooks.get(event, [])):
            matcher_group = configuration(group)
            keep: list[object] = []
            for handler in entries(matcher_group.get("hooks", [])):
                match handler:
                    case {"statusMessage": str() as marker} if marker == MARKER:
                        pass
                    case _:
                        keep.append(handler)
            if keep:
                retained.append({**matcher_group, "hooks": keep})
        owned_handler: dict[str, object] = {"type": "command", "command": command, "timeout": timeout, "statusMessage": MARKER}
        if event in ("Stop", "Notification"):
            owned_handler["async"] = True
        retained.append({"matcher": matcher, "hooks": [owned_handler]})
        hooks[event] = retained
    result["hooks"] = hooks
    return result


def install(path: Path, command: str, *, codex: bool) -> bool:
    if path.exists():
        loaded: object = json.loads(path.read_text())
    else:
        loaded = dict[str, object]()
    current = configuration(loaded)
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
    observed: dict[str, object] = dict(inspect.getmembers(parser.parse_args()))
    match observed:
        case {"python": str() as interpreter, "script": str() as script, "home": Path() as home}:
            pass
        case _:
            parser.error("Invalid hook installation arguments.")
    parts = (interpreter, "-B", script)
    command = subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)
    changes = {
        "codex": install(home / ".codex" / "hooks.json", command, codex=True),
        "claude": install(home / ".claude" / "settings.json", command + " --claude", codex=False),
    }
    result: dict[str, object] = {"workspace_hooks_updated": changes}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
