"""Real Windows hook subprocesses wait for answers from the console inbox."""

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from queue import Empty, Queue

from tests.json_fixture import json_fields, json_object, json_text

if sys.platform != "win32":
    raise unittest.SkipTest("Windows console hook transport")

from assistant.console_inbox import ConsoleInbox
from assistant.console_requests import Answer, Provider, Request, State
from tests.test_console_inbox import event


def test_windows_cli_hook_processes_receive_inbox_answers_and_explicit_permission_decisions(tmp_path: Path) -> None:
    script = Path(__file__).parent.parent / "scripts" / "inbox_hook.py"
    # The broker publishes from its own thread; the queue hands each observation to this test.
    published: Queue[tuple[Request, ...]] = Queue()
    broker = ConsoleInbox(tmp_path / "workspace" / "inbox-bridge.json", published.put, timeout=10)
    try:
        for provider, approval in ((Provider.CODEX, ""), (Provider.CLAUDE, ""), (Provider.CODEX, "Decline"), (Provider.CLAUDE, "Approve")):
            raw = event(provider, "owned-" + provider.name + approval)
            if approval:
                raw.update(hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "echo fictional-fixture"})
            args = [sys.executable, "-B", str(script), *(["--claude"] if provider is Provider.CLAUDE else [])]
            process = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "LOCALAPPDATA": str(tmp_path)}
            )
            try:
                assert process.stdin is not None
                process.stdin.write(json.dumps(raw).encode())
                process.stdin.close()
                process.stdin = None
                current: Request | None = None
                deadline = time.monotonic() + 6
                while current is None and time.monotonic() < deadline:
                    try:
                        requests = published.get(timeout=0.1)
                    except Empty:
                        continue
                    current = next((item for item in requests if item.session == raw["session_id"] and item.state is State.WAITING), None)
                assert current is not None, "The Windows hook did not reach the console inbox."
                assert broker.command(Answer(current.identity, 0, approval or "Revenue · Åäö"))
                output, errors = process.communicate(timeout=4)
                assert int(process.returncode or 0) == 0 and not errors
                result = json_fields(json_object(output)["hookSpecificOutput"])
                if approval:
                    assert json_fields(result["decision"])["behavior"] == ("allow" if approval == "Approve" else "deny")
                elif provider is Provider.CLAUDE:
                    assert json_fields(result["updatedInput"])["answers"] == {"Which sheet?": "Revenue · Åäö"}
                else:
                    assert result["permissionDecision"] == "deny" and "Revenue · Åäö" in json_text(result["permissionDecisionReason"])
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=2)
    finally:
        broker.close()
