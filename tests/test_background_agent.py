"""Background integrations share the agent's defaults, Stop and privacy rules."""

import json
import threading
from pathlib import Path
from typing import cast

from assistant import browser_tools, business_tools, meeting_tools
from assistant.agent import Agent
from assistant.agent_session import ToolActivity
from assistant.agent_toolsets import General
from assistant.geometry import Shot
from assistant.llm import Json, Settings, ToolCall
from tests.fake_endpoint import fake_endpoint
from tests.test_agent import FakeMachine, FakeWindow, Rig, calls, durable, says
from winapi.shapes import Rect


def test_meeting_voice_commands_use_the_recording_service_without_default_approvals(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(
            endpoint,
            calls(("meeting_start", {"source": "both", "title": "Private planning"})),
            calls(("meeting_status", {})),
            calls(("meeting_stop", {})),
            says("The transcript is saved."),
            work=durable(tmp_path),
        )
        rig.run("Record this meeting, check its progress, and then stop it.")
        assert "meeting start both Private planning" in rig.machine.log
        assert any(line.startswith("meeting stop") for line in rig.machine.log)
        assert all("Private planning" not in item.text for item in rig.window.live if isinstance(item, ToolActivity))
        request = cast(dict[str, Json], json.loads(endpoint.received[0].body))
        specs = cast(list[dict[str, Json]], request["tools"])
        assert {spec.name for spec in meeting_tools.CAPTURE_SPECS} <= {spec["name"] for spec in specs if isinstance(spec["name"], str)}


def test_stopped_agent_cannot_start_recording_and_explicit_approval_mode_is_preserved(tmp_path: Path) -> None:
    machine, cancel = FakeMachine(), threading.Event()
    agent = Agent(Settings("", "", "", "", "", "", "", agent_approvals=True), machine, FakeWindow(), cancel, work=durable(tmp_path), toolset=General)
    assert not agent.call(ToolCall("record", "meeting_start", "{}")).ok
    assert not any(line.startswith("meeting") for line in machine.log)
    cancel.set()
    assert not agent.call(ToolCall("stopped", "meeting_start", "{}")).ok
    assert not any(line.startswith("meeting") for line in machine.log)


def test_background_tools_are_exposed_to_the_model_and_run_without_default_prompts(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(
            endpoint,
            calls(("browser_attach", {"browser": "edge"})),
            calls(("browser_open", {"url": "https://example.com"})),
            calls(("browser_action", {"target_id": "page", "id": "field", "action": "fill", "value": "fixture-private"})),
            calls(("teams_status", {})),
            calls(("teams_send_message", {"chat_id": "chat", "text": "requested message"})),
            says("Done."),
            work=durable(tmp_path),
        )
        rig.run("Fill the fixture form and send the specified Teams message.")
        assert any(line.startswith("browser action") for line in rig.machine.log)
        assert any(line.startswith("teams send_message") for line in rig.machine.log)
        request = cast(dict[str, Json], json.loads(endpoint.received[0].body))
        specs = cast(list[dict[str, Json]], request["tools"])
        names = {spec["name"] for spec in specs if isinstance(spec["name"], str)}
        assert {spec.name for spec in (*browser_tools.SPECS, *business_tools.TEAMS_SPECS)} <= names
        assert not any("fixture-private" in line for line in rig.window.log)
        activities = [item for item in rig.window.live if isinstance(item, ToolActivity)]
        assert activities and all(item.detail == "" for item in activities)
        assert all("fixture-private" not in item.text and "requested message" not in item.text for item in activities)


def test_explicit_approval_mode_can_decline_browser_changes_and_teams_sends(tmp_path: Path) -> None:
    # Defect: a browser change or Teams send skips the approval gate. Each tool
    # gets its own task: the first unreviewed approval suspends a task.
    machine = FakeMachine()
    for name, arguments in (
        ("browser_attach", {"browser": "edge"}),
        ("browser_action", {"target_id": "page", "id": "button", "action": "click"}),
        ("browser_group", {"tab_ids": [7], "title": "Workspace"}),
        ("browser_ungroup", {"tab_ids": [7]}),
        ("browser_tab", {"tab_id": 7, "action": "pin"}),
        ("browser_close", {"group_id": 23}),
        ("teams_send_message", {"chat_id": "chat", "text": "message"}),
    ):
        work = durable(tmp_path)
        agent = Agent(
            Settings("", "", "", "", "", "", "", agent_approvals=True), machine, FakeWindow(), threading.Event(), work=work, toolset=General
        )
        assert not agent.call(ToolCall("fixture", name, json.dumps(arguments))).ok
        assert work.disposition is not None, name
    assert not any(line.startswith(("browser ", "teams ")) for line in machine.log)


def test_browser_images_invalidate_desktop_coordinates(tmp_path: Path) -> None:
    machine = FakeMachine()
    agent = Agent(Settings("", "", "", "", "", "", ""), machine, FakeWindow(), threading.Event(), work=durable(tmp_path), toolset=General)
    agent.screen.shot = Shot(Rect(0, 0, 1920, 1080), 960, 540)
    result = agent.call(ToolCall("browser", "browser_screenshot", '{"target_id":"page"}'))
    assert result.image is not None
    click = agent.call(ToolCall("desktop", "click", '{"x":10,"y":10}'))
    assert not click.ok and "screenshot first" in click.text
    assert not any(line.startswith("click ") for line in machine.log)


def test_agent_can_manage_tabs_and_groups_without_default_approval_prompts(tmp_path: Path) -> None:
    machine = FakeMachine()
    agent = Agent(Settings("", "", "", "", "", "", ""), machine, FakeWindow(), threading.Event(), work=durable(tmp_path), toolset=General)
    for name, arguments in (
        ("browser_tabs", {"view": "strip"}),
        ("browser_open", {"url": "about:blank", "group_id": 23}),
        ("browser_group", {"tab_ids": [7, 8], "title": "Workspace", "collapsed": True}),
        ("browser_group", {"group_id": 23, "title": "Research", "index": -1}),
        ("browser_ungroup", {"tab_ids": [8]}),
        ("browser_tab", {"tab_id": 7, "action": "pin"}),
        ("browser_close", {"group_id": 23}),
    ):
        result = agent.call(ToolCall("tabs", name, json.dumps(arguments)))
        assert result.ok, (name, result.text)
    assert len(machine.log) == 7 and all(line.startswith("browser ") for line in machine.log)
    assert {"browser_group", "browser_ungroup", "browser_tab"} <= {spec.name for spec in browser_tools.SPECS}


def test_stopped_agent_does_not_start_background_tools_or_show_their_arguments(tmp_path: Path) -> None:
    machine, window, cancel = FakeMachine(), FakeWindow(), threading.Event()
    agent = Agent(Settings("", "", "", "", "", "", ""), machine, window, cancel, work=durable(tmp_path), toolset=General)
    cancel.set()
    for name in ("browser_action", "teams_send_message"):
        result = agent.call(ToolCall("stopped", name, '{"text":"private-secret"}'))
        assert not result.ok
    assert not machine.log
    assert "private-secret" not in str(window.log)
    assert all("private-secret" not in item.text for item in window.live)
