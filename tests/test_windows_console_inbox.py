"""Real Windows hook subprocesses wait for answers from the native inbox."""

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from tests.json_fixture import json_fields, json_object, json_text

if sys.platform != "win32":
    raise unittest.SkipTest("Windows console hook transport")

from assistant.agent_toasts import AgentToasts
from assistant.console_inbox import ConsoleInbox
from assistant.console_requests import Answer, Provider, Request, State
from assistant.feed_items import WorkItem, action_spans, body_spans
from tests.test_console_inbox import event
from tests.test_windows_agent_toasts import notifications


def answer_request(view: AgentToasts, current: Request, approval: str) -> None:
    if approval:
        decision = next(
            span.link
            for card in view.cards.values()
            if isinstance(card.content, WorkItem)
            for span in (*body_spans(card.content), *action_spans(card.content))
            if span.link.startswith("workspace://console-option?") and f"answer={approval}" in span.link
        )
        view.action_link(decision)
    else:
        # The voice agent relays the user's answer through the existing console owner.
        action = view.agent.on_console
        assert action is not None and action(Answer(current.identity, 0, "Revenue · Åäö"))


def test_windows_cli_hook_processes_receive_native_inbox_answers_and_explicit_permission_decisions(tmp_path: Path) -> None:
    script = Path(__file__).parent.parent / "scripts" / "inbox_hook.py"
    with notifications() as panel:
        broker = ConsoleInbox(tmp_path / "workspace" / "inbox-bridge.json", panel.agent.consoles, timeout=10)
        panel.agent.on_console = broker.command
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
                    while time.monotonic() < deadline:
                        panel.pump()
                        current = next(
                            (
                                item
                                for item in panel.view.session.console_requests
                                if item.session == raw["session_id"] and item.state is State.WAITING
                            ),
                            None,
                        )
                        if current is not None:
                            break
                        time.sleep(0.02)
                    assert current is not None, "The Windows hook did not reach the native inbox."
                    view = panel.view
                    assert any(provider.value in card.content.title for card in view.cards.values() if isinstance(card.content, WorkItem))
                    answer_request(view, current, approval)
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
