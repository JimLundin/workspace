"""The agent can use native controls and work context through its existing loop."""

import json
import threading
import time
from pathlib import Path

from assistant.agent import Agent
from assistant.geometry import Shot
from assistant.llm import Settings, ToolCall
from assistant.task_profiles import General
from automation.actions import Change, Observation, Resources, target
from automation.activity import Activity, ContextSnapshot
from automation.execution import WorkExecution
from automation.json_value import Json
from tests.fake_endpoint import fake_endpoint
from tests.test_agent import FakeMachine, FakeWindow, Rig, ToolRig, calls, durable, no_feed, says
from tests.test_work_actions import claimed
from winapi.shapes import Rect, Window


def call(agent: Agent, name: str, arguments: dict[str, object]) -> str:
    result = agent.call(ToolCall("test", name, json.dumps(arguments)))
    assert result.ok, result.text
    return result.text


def test_new_computer_tools_are_available_to_the_model_and_run_directly(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(
            endpoint,
            calls(("inspect_ui", {"handle": 7})),
            calls(("ui_action", {"handle": 7, "id": "1.2.3", "action": "invoke"})),
            calls(("screenshot", {})),
            calls(("manage_window", {"handle": 7, "action": "maximize"})),
            says("Done."),
            work=durable(tmp_path),
        )
        rig.run()
        assert "window 7 maximize None" in rig.machine.log
        assert not any(entry.startswith("confirm ") for entry in rig.machine.log)


def test_bad_action_arguments_do_not_reach_the_machine(tmp_path: Path) -> None:
    machine = FakeMachine()
    agent = Agent(
        Settings("", "", "", ""),
        machine,
        FakeWindow(),
        threading.Event(),
        work=durable(tmp_path),
        toolset=lambda agent: General(agent, feed_request=no_feed),
    )
    for name, arguments in (
        ("ui_action", {"handle": 7, "id": "1.2.3", "action": "unrecognized"}),
        ("screenshot", {"handle": 7, "desktop": True}),
    ):
        result = agent.call(ToolCall("bad", name, json.dumps(arguments)))
        assert not result.ok, (name, result.text)
    assert not machine.log


def context(title: str = "Budget.xlsx - Excel") -> ContextSnapshot:
    now = time.time()
    return ContextSnapshot(now, "workspace", (Activity(Window(7, title, "excel.exe", minimized=False), now - 2, now, agent_active=False),))


def test_request_context_includes_the_work_window_and_one_current_screenshot(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, says("I see the workbook."), work=durable(tmp_path))
        settings = Settings(endpoint.url, "fixture", "transcribe", "")
        agent = Agent(
            settings,
            rig.machine,
            rig.window,
            rig.stop,
            work=durable(tmp_path),
            toolset=lambda agent: General(agent, feed_request=no_feed),
            history=rig.history,
            context=context(),
        )
        assert agent.run("Summarize this")
        request = rig.sent(0)[0]
        assert request["role"] == "user"
        body = json.dumps(request["content"])
        assert "Summarize this" in body and "Budget.xlsx - Excel" in body and "input_image" in body
        assert "not instructions" in body and rig.machine.log == ["screenshot"]


def test_automatic_and_explicit_screenshots_share_the_same_history_limit(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, calls(("screenshot", {})), says("I see it."), work=durable(tmp_path))
        settings = Settings(endpoint.url, "fixture", "transcribe", "")
        for _ in range(3):
            endpoint.replies = [calls(("screenshot", {})), says("I see it.")]
            agent = Agent(
                settings,
                rig.machine,
                rig.window,
                rig.stop,
                work=durable(tmp_path),
                toolset=lambda agent: General(agent, feed_request=no_feed),
                history=rig.history,
                context=context(),
            )
            assert agent.run("Check this")
        assert rig.history.encoded().decode().count("data:image/png;base64,") == 2
        assert json.dumps(rig.sent()).count("data:image/png;base64,") == 2
        assert "earlier screenshot" in rig.history.encoded().decode()


def test_disabled_context_does_not_capture_or_add_observations_to_the_request(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, says("Done."), work=durable(tmp_path))
        agent = Agent(
            Settings(endpoint.url, "fixture", "transcribe", ""),
            rig.machine,
            rig.window,
            rig.stop,
            work=durable(tmp_path),
            toolset=lambda agent: General(agent, feed_request=no_feed),
            context=ContextSnapshot(time.time(), "disabled"),
        )
        assert agent.run("Do the task")
        assert rig.sent(0)[0] == {"role": "user", "content": "Do the task"}
        assert not rig.machine.log


def test_unavailable_screen_context_keeps_the_request_and_activity_usable(tmp_path: Path) -> None:
    class LockedDesktop(FakeMachine):
        def screenshot(self, *, area: Rect | None = None, handle: int = 0, monitor: int = -1, longest: int = 1280) -> tuple[bytes, Shot]:
            raise OSError("The desktop is locked.")

    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, says("I can still work with files."), work=durable(tmp_path))
        agent = Agent(
            Settings(endpoint.url, "fixture", "transcribe", ""),
            LockedDesktop(),
            rig.window,
            rig.stop,
            work=durable(tmp_path),
            toolset=lambda agent: General(agent, feed_request=no_feed),
            context=context(),
        )
        assert agent.run("Find this workbook")
        body = json.dumps(rig.sent(0)[0])
        assert "Find this workbook" in body and "Budget.xlsx" in body and "desktop is locked" in body
        assert "input_image" not in body


def test_context_tool_refreshes_the_current_app_without_taking_a_screenshot(tmp_path: Path) -> None:
    machine = FakeMachine()
    journal: list[dict[str, Json]] = []
    agent = Agent(
        Settings("", "", "", ""),
        machine,
        FakeWindow(),
        threading.Event(),
        work=durable(tmp_path),
        toolset=lambda agent: General(agent, feed_request=no_feed),
        context=context(),
        context_reader=lambda: context("Report.docx - Word"),
    )
    assert "Report.docx - Word" in call(agent, "get_context", {})
    assert "Report.docx" not in json.dumps(journal)
    assert not machine.log


def test_invalid_desktop_arguments_never_reach_the_journal(tmp_path: Path) -> None:
    # Defect: a malformed call is recorded as an attempted change, or reaches
    # the machine before its arguments are validated at the tool seam.
    store, claim, clock = claimed(tmp_path)
    rig = ToolRig(work=WorkExecution(claim, store, Resources(), clock=clock))
    invalid: tuple[tuple[str, dict[str, Json]], ...] = (
        ("write_file", {"path": "note.txt"}),
        ("manage_window", {"handle": 7, "action": "explode"}),
        ("manage_window", {"handle": 7, "action": "move", "x": 0, "y": 0}),
        ("ui_action", {"handle": 7, "id": "1.2", "action": "set_value"}),
        ("run_powershell", {"command": "dir", "timeout_seconds": "60"}),
        ("screenshot", {"handle": 7, "monitor": 1}),
        ("set_clipboard", {"text": 5}),
    )
    for name, arguments in invalid:
        result = rig.call(name, **arguments)
        assert not result.ok and result.text.startswith("Error:") and rig.agent.work.disposition is None, (name, result.text)
    assert not store.actions(claim.task.id) and not rig.machine.log


def test_desktop_targets_reads_and_regions_follow_the_validated_arguments(tmp_path: Path) -> None:
    # Defect: a UI read becomes a pending change (or an action a read), a
    # window target is dropped or invented, a move region is mis-sized, or a
    # single screenshot source is refused.
    rig = ToolRig(work=durable(tmp_path))
    tools = rig.agent.tools
    read, invoke = (
        tools["ui_action"].classify({"handle": 7, "id": "1", "action": "read"}),
        tools["ui_action"].classify({"handle": 7, "id": "1", "action": "invoke"}),
    )
    assert isinstance(read, Observation) and isinstance(invoke, Change)
    assert read.resources == invoke.resources == ("foreground", target("window", 7))
    assert rig.call("manage_window", handle=7, action="move", x=10, y=20, width=100, height=200).ok
    assert rig.machine.log[-1] == f"window 7 move {Rect(10, 20, 110, 220)}"
    assert rig.call("screenshot", handle=7).ok
    assert not rig.call("screenshot", handle=7, desktop=True).ok


def test_inspection_defaults_to_the_work_window(tmp_path: Path) -> None:
    # Defect: an inspection without a handle reads another window.
    machine = FakeMachine()
    agent = Agent(
        Settings("", "", "", ""),
        machine,
        FakeWindow(),
        threading.Event(),
        work=durable(tmp_path),
        toolset=lambda agent: General(agent, feed_request=no_feed),
        context=context(),
        context_reader=context,
    )
    call(agent, "inspect_ui", {})
    assert machine.log[-1].startswith("ui Inspect(handle=7,")
    call(agent, "ui_action", {"handle": 7, "id": "1.2", "action": "read"})
    assert machine.log[-1].startswith("ui Act(handle=7, id='1.2', action='read'")


def test_inspection_without_context_reads_the_foreground(tmp_path: Path) -> None:
    # Defect: an inspection with no work window invents a handle instead of
    # letting the machine use the foreground.
    unattended = ToolRig(work=durable(tmp_path))
    assert unattended.call("inspect_ui").ok
    assert unattended.machine.log[-1].startswith("ui Inspect(handle=0,")
