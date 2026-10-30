"""Regressions for Workspace's tool routing and reply presentation choices."""

from datetime import UTC, datetime
from pathlib import Path

from assistant import notification_text
from assistant.communications import Delivery, Reply
from assistant.feed_contracts import SolutionKind
from assistant.feed_items import WorkItem
from assistant.feed_sources import SourceKey, SourceKind
from assistant.feed_triage import Assessment, Solution
from assistant.notifications import Entry, Settled, Turn
from automation.presentation import Answer, StreamState, Succeeded, ToolActivity
from tests.fake_endpoint import fake_endpoint
from tests.json_fixture import json_object, json_rows
from tests.test_agent import Rig, ToolRig, calls, durable, says


def test_time_calls_observe_fresh_time_and_publish_tool_activity(tmp_path: Path) -> None:
    """Detect a missing dispatch or a tool reusing the prompt's stale time."""
    observations = (datetime(2026, 10, 28, 10, tzinfo=UTC), datetime(2026, 10, 28, 11, tzinfo=UTC))
    times = iter(observations)
    rig = ToolRig(clock=lambda: next(times), work=durable(tmp_path))
    first = rig.call("get_current_time")
    second = rig.call("get_current_time")
    assert first.ok and second.ok
    assert "2026-10-28T10:00:00+00:00" in first.text
    assert "2026-10-28T11:00:00+00:00" in second.text
    calls = tuple(item for item in rig.window.live if isinstance(item, ToolActivity))
    assert len(calls) == 4 and all(item.name == "get_current_time" for item in calls)
    assert isinstance(calls[-1].outcome, Succeeded)


def test_collapsed_turn_exposes_latest_tool_call_as_literal_metadata() -> None:
    """Detect tools disappearing behind disclosure or command Markdown parsing."""
    tool = ToolActivity("cli", "run_powershell", 'Write-Output "**literal**"', 1, Succeeded("Exit code 0.\n**literal**"))
    turn = Turn(0, (Entry(1, tool), Entry(2, Answer("a", "The **result**.", 2, StreamState.COMPLETE))), Settled.FINISHED)
    detail = notification_text.details(turn, expanded=False)
    assert any("run_powershell" in span.text and "tool_call" in span.tags for span in detail)
    assert any("**literal**" in span.text and "code" in span.tags for span in detail)
    assert "Succeeded" in "".join(span.text for span in detail)
    assert any(span.text == "result" and "bold" in span.tags for span in notification_text.spans(turn))


def test_earlier_answers_keep_markdown_when_moved_into_steps() -> None:
    """Detect the history adapter flattening an already formatted reply."""
    turn = Turn(0, (Entry(1, Answer("old", "A **finding**.", 1)), Entry(2, Answer("new", "Done.", 2))), Settled.FINISHED)
    assert any(span.text == "finding" and "bold" in span.tags for span in notification_text.details(turn))


def test_reply_work_item_uses_the_markdown_body_adapter() -> None:
    """Detect the Reply variant bypassing our existing rich-text path."""
    reply = Reply("reply", "chat", "Proposed reply", "Please check **the totals**.", 1, Delivery.UNKNOWN)
    row = WorkItem(SourceKey(SourceKind.REPLY, "reply"), reply, reply.title)
    assert any("the totals" in span.text and "bold" in span.tags for span in notification_text.spans(row))


def test_model_can_invoke_the_registered_time_tool(tmp_path: Path) -> None:
    """Detect a time handler omitted from the SDK's exposed tool catalog."""
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, calls(("get_current_time", {})), says("Time checked."), work=durable(tmp_path))
        rig.run("Check the current time.")
        request = json_object(endpoint.received[0].body)
        assert any(spec["name"] == "get_current_time" for spec in json_rows(request["tools"]))
        assert "UTC time:" in rig.results()[0]


def test_cli_arguments_and_json_output_stay_literal_through_the_tool_boundary(tmp_path: Path) -> None:
    """Detect our preview adapter rewriting a command/result as prose."""
    rig = ToolRig(work=durable(tmp_path))
    command = 'Write-Output \'{"status":"**literal**"}\''
    rig.machine.commands[command] = (0, '{"status":"**literal**"}')
    assert rig.call("run_powershell", command=command).ok
    activity = rig.window.live[-1]
    assert isinstance(activity, ToolActivity) and activity.detail == command
    detail = notification_text.details(Entry(1, activity))
    assert any(span.text == command + "\n" and "tool_input" in span.tags for span in detail)
    assert any('{"status":"**literal**"}' in span.text and "tool_output" in span.tags for span in detail)


def test_expanded_proposal_formats_each_possible_reply() -> None:
    """Detect solution details being available only as a plain button tooltip."""
    item = Assessment(
        "plan",
        (),
        "Review budget",
        "A review is needed.",
        "Prepare a response.",
        "",
        1,
        1,
        solutions=(Solution("draft", "Draft reply", SolutionKind.DRAFT, "Please check **the totals** in `FY27`."),),
    )
    row = WorkItem(SourceKey(SourceKind.PROPOSAL, "plan"), item, item.title)
    detail = notification_text.spans(row, expanded=True)
    assert any("the totals" in span.text and "bold" in span.tags for span in detail)
    assert any(span.text == "FY27" and "code" in span.tags for span in detail)
