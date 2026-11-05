"""Background integrations share the agent's defaults, Stop and privacy rules."""

import json
import threading
from pathlib import Path
from typing import cast

from assistant import browser_tools, business_tools, meeting_tools
from assistant.agent import Agent
from assistant.agent_session import activity_text
from assistant.llm import Settings, ToolCall
from assistant.meeting_tools import MeetingCommand, StartMeeting
from assistant.task_profiles import General
from automation.json_value import Json
from automation.presentation import ToolActivity
from tests.agent_requests import body
from tests.fake_endpoint import fake_endpoint
from tests.test_agent import FakeMachine, FakeWindow, Rig, calls, durable, no_feed, says


def test_meeting_voice_commands_use_the_recording_service_directly(tmp_path: Path) -> None:
    # Defect: the capture seam drops the selected source/title, dispatches the
    # wrong command, or exposes private capture arguments in live activity.
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
        assert rig.machine.meetings == [StartMeeting("both", "Private planning"), MeetingCommand.STATUS, MeetingCommand.STOP]
        assert all("Private planning" not in activity_text(item) for item in rig.window.live if isinstance(item, ToolActivity))
        request = cast(dict[str, Json], json.loads(endpoint.received[0].body))
        specs = cast(list[dict[str, Json]], request["tools"])
        assert {spec.name for spec in meeting_tools.CAPTURE_SPECS} <= {spec["name"] for spec in specs if isinstance(spec["name"], str)}


def test_stopped_agent_cannot_start_recording(tmp_path: Path) -> None:
    # Defect: typed start dispatch bypasses cancellation and reaches the
    # recording owner after the user stopped the work.
    machine, cancel = FakeMachine(), threading.Event()
    agent = Agent(
        Settings("", "", "", "", ""),
        machine,
        FakeWindow(),
        cancel,
        work=durable(tmp_path),
        toolset=lambda agent: General(agent, feed_request=no_feed),
    )
    cancel.set()
    assert not agent.call(ToolCall("stopped", "meeting_start", "{}")).ok
    assert machine.meetings == []


def test_background_tools_are_exposed_to_the_model_and_run_directly(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(
            endpoint,
            calls(("browser_open", {"url": "https://example.com"})),
            calls(("browser_action", {"target_id": "page", "id": "field", "action": "fill", "value": "fixture-private"})),
            says("Done."),
            work=durable(tmp_path),
        )
        rig.run("Fill the fixture form.")
        assert any(line.startswith("browser PageAction(") for line in rig.machine.log)
        request = cast(dict[str, Json], json.loads(endpoint.received[0].body))
        specs = cast(list[dict[str, Json]], request["tools"])
        names = {spec["name"] for spec in specs if isinstance(spec["name"], str)}
        assert {spec.name for spec in (*browser_tools.SPECS, *(tool.spec for tool in business_tools.WEB_TOOLS))} <= names
        # Teams is reached only through the signed-in browser.
        assert {name for name in names if name.startswith("teams_")} == {"teams_web_read", "teams_web_open_chat", "teams_web_draft_reply"}
        assert not any("fixture-private" in line for line in rig.window.log)
        activities = [item for item in rig.window.live if isinstance(item, ToolActivity)]
        assert activities and all(item.detail == "" for item in activities)
        assert all("fixture-private" not in activity_text(item) for item in activities)


def test_agent_cannot_attach_to_or_manage_the_personal_browser(tmp_path: Path) -> None:
    # Defect: a model can select the user's browser instead of its exclusive
    # instance through its arguments.
    machine = FakeMachine()
    agent = Agent(
        Settings("", "", "", "", ""),
        machine,
        FakeWindow(),
        threading.Event(),
        work=durable(tmp_path),
        toolset=lambda agent: General(agent, feed_request=no_feed),
    )
    for name, arguments in (
        ("browser_attach", {"browser": "edge"}),
        ("browser_open", {"url": "about:blank", "browser": "edge"}),
        ("browser_open", {"url": "about:blank", "browser": "chrome"}),
    ):
        result = agent.call(ToolCall("tabs", name, json.dumps(arguments)))
        assert not result.ok, (name, result.text)
    assert not machine.log
    assert "browser_attach" not in {spec.name for spec in browser_tools.SPECS}


def test_stopped_agent_does_not_start_background_tools_or_show_their_arguments(tmp_path: Path) -> None:
    machine, window, cancel = FakeMachine(), FakeWindow(), threading.Event()
    agent = Agent(
        Settings("", "", "", "", ""),
        machine,
        window,
        cancel,
        work=durable(tmp_path),
        toolset=lambda agent: General(agent, feed_request=no_feed),
    )
    cancel.set()
    for name in ("browser_action", "kanban_comment"):
        result = agent.call(ToolCall("stopped", name, '{"text":"private-secret"}'))
        assert not result.ok
    assert not machine.log
    assert "private-secret" not in str(window.log)
    assert all("private-secret" not in body(item) for item in window.live)
