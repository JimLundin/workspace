"""The agent: its loop, what it may do without asking, and its tools. Against a
fake endpoint playing the model, and a fake machine."""

import json
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Final, cast

from assistant.agent import Agent
from assistant.agent_history import History
from assistant.agent_session import activity_text
from assistant.agent_tools import Output
from assistant.agent_toolsets import General
from assistant.browser_requests import BrowserRequest, Screenshot
from assistant.browser_values import BrowserError
from assistant.desktop_tools import allowed, key_strokes
from assistant.feed_agent_tools import request
from assistant.geometry import Shot
from assistant.llm import Json, Settings, ToolCall, settings_from
from assistant.uia import UiRequest
from assistant.web_apps import Located, WebAppOperation
from assistant.work_bridge_contracts import BridgeCommand
from assistant.workspace import Workspace
from automation.actions import Resources
from automation.execution import ApprovalReview, WorkExecution
from automation.presentation import LiveMessage, Succeeded, ToolActivity, ToolStatus
from automation.store import TaskStore
from automation.task import RequestSource
from tests.fake_endpoint import FakeEndpoint, Received, Reply, fake_endpoint, sse
from tests.test_workspace import live_tree
from winapi.shapes import Rect, Window


def dumps(value: Json) -> str:
    return json.dumps(value)


def response(*output: Json) -> Reply:
    """A complete Responses SSE event; quick chat fixtures use Chat Completions."""
    return sse(
        dumps(
            {
                "type": "response.completed",
                "sequence_number": 0,
                "response": {
                    "id": f"resp_{uuid.uuid4().hex}",
                    "object": "response",
                    "created_at": 1,
                    "model": "gpt-6-astra",
                    "status": "completed",
                    "output": list(output),
                    "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
                },
            }
        )
    )


def message(text: str) -> Json:
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def calls(*tools: tuple[str, Mapping[str, Json]]) -> Reply:
    """The model asking for tools."""
    tool_calls: list[Json] = [
        {
            "id": f"fc_{uuid.uuid4().hex}",
            "call_id": f"call_{uuid.uuid4().hex}_{i}",
            "type": "function_call",
            "name": name,
            "arguments": dumps(dict(args)),
            "status": "completed",
        }
        for i, (name, args) in enumerate(tools)
    ]
    return response(message("On it."), *tool_calls)


def says(text: str) -> Reply:
    return response(message(text))


def durable(folder: Path, *, review: Callable[[ApprovalReview], bool] | None = None) -> WorkExecution:
    """Every agent run executes one claimed durable task."""
    identity = uuid.uuid4().hex
    store = TaskStore(folder / "agent-work" / identity / "work.sqlite3")
    store.submit(identity, "Agent fixture", "do it", RequestSource("chat"), at=1)
    claim = store.claim("worker", identity, at=2)
    assert claim is not None
    return WorkExecution(claim, store, Resources(), review=review)


def observed(output: object) -> str:
    """Durable observations append their evidence identifier to the model's result."""
    assert isinstance(output, str)
    text, marker, identity = output.rpartition("\n[observation_id: ")
    assert marker and identity.endswith("]"), output
    return text


class FakeMachine:
    __slots__ = ("commands", "executed", "log")

    def __init__(self) -> None:
        self.log: list[str] = []
        self.commands: dict[str, tuple[int, str]] = {}
        self.executed: list[tuple[str, float, str | None, threading.Event | None]] = []

    def run_powershell(
        self,
        command: str,
        timeout_s: float,
        *,
        cwd: str | None = None,
        cancel: threading.Event | None = None,
    ) -> tuple[int, str]:
        self.log.append(f"ran {command}")
        self.executed.append((command, timeout_s, cwd, cancel))
        return self.commands.get(command, (0, "ok"))

    def screenshot(self, *, area: Rect | None = None, handle: int = 0, monitor: int = -1, longest: int = 1280) -> tuple[bytes, Shot]:
        self.log.append("screenshot")
        return b"\x89PNG", Shot(Rect(0, 0, 2560, 1440), 1280, 720)

    def click(self, x: int, y: int, button: str, count: int) -> None:
        self.log.append(f"click {button} x{count} at {x},{y}")

    def desktop_state(self) -> str:
        return '{"foreground":7,"coordinates":"physical screen pixels"}'

    def window_action(self, handle: int, action: str, bounds: Rect | None = None) -> str:
        self.log.append(f"window {handle} {action} {bounds}")
        return "Done."

    def inspect_ui(self, request: UiRequest, cancel: threading.Event) -> tuple[int, str]:
        self.log.append(f"ui {request}")
        return 0, '{"controls":[{"id":"1.2.3","name":"Save","actions":["invoke"]}]}'

    def browse(self, request: BrowserRequest, cancel: threading.Event) -> tuple[str, bytes | None]:
        self.log.append(f"browser {request}")
        match request:
            case Screenshot():
                return "Browser operation completed.", b"\x89PNG"
            case _:
                return "Browser operation completed.", None

    def web_app[Q: Located, R](self, operation: WebAppOperation[Q, R], query: Q, cancel: threading.Event) -> R:
        self.log.append("web_app " + query.target_id)
        raise BrowserError("This machine has no captured web-app results.")

    def close_background(self) -> None:
        pass

    def meeting(self, operation: str, source: str = "both", title: str = "Meeting") -> str:
        self.log.append(f"meeting {operation} {source} {title}")
        return "Meeting state supplied."

    def move_mouse(self, x: int, y: int) -> None:
        self.log.append(f"move {x},{y}")

    def mouse_button(self, button: str, *, down: bool) -> None:
        self.log.append(f"button {button} {down}")

    def type_text(self, text: str) -> None:
        self.log.append(f"type {text}")

    def paste_text(self, text: str) -> None:
        self.log.append(f"paste {text}")

    def press_keys(self, strokes: list[tuple[int, bool]]) -> None:
        self.log.append(f"keys {strokes}")

    def scroll(self, x: int, y: int, clicks: int, *, horizontal: bool = False) -> None:
        self.log.append(f"scroll {clicks} at {x},{y}" + (" horizontal" if horizontal else ""))

    def windows(self) -> list[Window]:
        return [Window(7, "Inbox - Outlook", "olk.exe", minimized=False)]

    def focus(self, handle: int) -> bool:
        self.log.append(f"focus {handle}")
        return True

    def get_clipboard(self) -> str | None:
        return "clipped"

    def set_clipboard(self, text: str) -> None:
        self.log.append(f"clipboard {text}")

    def open(self, target: str) -> None:
        self.log.append(f"open {target}")

    def install(self, summary: str) -> None:
        self.log.append(f"install {summary}")


class FakeWindow:
    __slots__ = ("live", "log")

    def __init__(self) -> None:
        self.log: list[str] = []
        self.live: list[LiveMessage] = []

    def updates(self) -> Callable[[LiveMessage], None]:
        return self.live.append

    def step(self, text: str, /) -> None:
        self.log.append(f"step {text}")

    def say(self, text: str, /) -> None:
        self.log.append(f"say {text}")

    def problem(self, text: str, /) -> None:
        self.log.append(f"problem {text}")

    def done(self, text: str, /) -> None:
        self.log.append(f"done {text}")

    def queued(self, task: str) -> None:
        self.log.append(f"queued {task}")

    def stopping(self) -> None:
        self.log.append("stopping")

    def finish(self) -> None:
        self.log.append("finished")

    def reset(self) -> None:
        self.log.clear()
        self.live.clear()


class Rig:
    __slots__ = ("endpoint", "history", "machine", "stop", "window", "work", "workspace")

    def __init__(self, endpoint: FakeEndpoint, *replies: Reply, work: WorkExecution, workspace: Workspace | None = None) -> None:
        self.work, self.workspace = work, workspace
        endpoint.replies = list(replies)
        self.endpoint = endpoint
        self.machine = FakeMachine()
        self.window = FakeWindow()
        self.stop = threading.Event()
        self.history = History()

    def run(
        self,
        task: str = "do it",
        max_steps: int = 10,
        *,
        after_step: Callable[[], None] | None = None,
        approvals: bool = False,
        effort: str = "max",
    ) -> None:
        settings = Settings(
            self.endpoint.url,
            "k",
            "transcribe",
            "chat",
            "gpt-6-astra",
            "",
            "",
            agent_reasoning_effort=effort,
            agent_approvals=approvals,
        )
        agent = Agent(
            settings,
            self.machine,
            self.window,
            self.stop,
            work=self.work,
            toolset=lambda agent: General(agent, workspace=self.workspace),
            max_steps=max_steps,
            after_step=after_step,
            history=self.history,
        )
        agent.run(task)

    def sent(self, index: int = -1) -> list[dict[str, object]]:
        data: object = json.loads(self.endpoint.received[index].body)
        assert isinstance(data, dict)
        return cast("list[dict[str, object]]", cast("dict[str, object]", data)["input"])

    def results(self, index: int = -1) -> list[str]:
        """The tool results the model saw in request `index`, from its latest step."""
        messages = self.sent(index)
        last = max((i for i, m in enumerate(messages) if m.get("role") == "assistant"), default=len(messages))
        return [str(m["output"]) for m in messages[last:] if m.get("type") == "function_call_output"]


class ToolRig:
    """Exercise the public tool boundary; SDK transport has its own scenarios below."""

    __slots__ = ("agent", "machine", "window")

    def __init__(
        self,
        *,
        work: WorkExecution,
        approvals: bool = False,
        workspace: Workspace | None = None,
        machine: FakeMachine | None = None,
        clock: Callable[[], datetime] = datetime.now,
        feed_request: Callable[[BridgeCommand], str] = request,
    ) -> None:
        self.machine = machine if machine is not None else FakeMachine()
        self.window = FakeWindow()
        self.agent = Agent(
            Settings("", "", "", "", "", "", "", agent_approvals=approvals),
            self.machine,
            self.window,
            threading.Event(),
            work=work,
            toolset=lambda agent: General(agent, workspace=workspace, clock=clock, feed_request=feed_request),
        )

    def call(self, name: str, **arguments: Json) -> Output:
        return self.agent.call(ToolCall("fixture", name, dumps(arguments)))


# ---- the loop --------------------------------------------------------------------------


def test_the_agent_uses_tools_then_answers(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, calls(("list_directory", {"path": str(tmp_path)})), says("There is one file: notes.txt."), work=durable(tmp_path))
        rig.run("what's in my folder?")
        assert "notes.txt" in rig.results()[0]
        assert rig.window.log[-1] == "done There is one file: notes.txt."
        assert rig.sent(0)[0] == {"role": "user", "content": "what's in my folder?"}
        assert cast(dict[str, Json], json.loads(endpoint.received[0].body))["model"] == "gpt-6-astra"


def test_tool_replay_omits_absent_namespace_and_retains_reasoning_across_follow_ups(tmp_path: Path) -> None:
    # Workspace must adapt nullable output metadata before validating replay input;
    # otherwise the second model turn and subsequent requests fail before research.
    reasoning: Json = {
        "id": "rs_namespace",
        "type": "reasoning",
        "summary": [],
        "encrypted_content": "opaque-test-reasoning",
    }
    call: Json = {
        "id": "fc_namespace",
        "call_id": "call_namespace",
        "type": "function_call",
        "name": "get_clipboard",
        "arguments": "{}",
        "namespace": None,
        "status": "completed",
    }
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, response(reasoning, call), says("Read the clipboard."), work=durable(tmp_path))
        rig.run()
        assert rig.window.log[-1] == "done Read the clipboard."
        endpoint.replies = [says("The earlier result is retained.")]
        rig.run("What did you find?")
        assert rig.window.log[-1] == "done The earlier result is retained."
        for index in (1, 2):
            replay = rig.sent(index)
            assert next(item for item in replay if item.get("id") == "rs_namespace") == reasoning
            assert next(item for item in replay if item.get("id") == "fc_namespace") == {
                "id": "fc_namespace",
                "call_id": "call_namespace",
                "type": "function_call",
                "name": "get_clipboard",
                "arguments": "{}",
                "status": "completed",
            }
            outputs = [item.get("output") for item in replay if item.get("call_id") == "call_namespace" and "output" in item]
            assert [observed(output) for output in outputs] == ["clipped"]


def test_default_agent_uses_sol_with_low_reasoning_across_tool_turns(tmp_path: Path) -> None:
    """The speed-focused defaults must reach the SDK on every tool turn."""
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, calls(("get_clipboard", {})), says("Read it."), work=durable(tmp_path))
        settings = settings_from({"OPENAI_BASE_URL": endpoint.url, "OPENAI_API_KEY": "k"})
        assert isinstance(settings, Settings)
        agent = Agent(settings, rig.machine, rig.window, rig.stop, work=durable(tmp_path), toolset=General)
        agent.run("Read the clipboard.")
        assert len(endpoint.received) == 2
        for request in endpoint.received:
            body = cast("dict[str, Json]", json.loads(request.body))
            assert request.path == "/v1/responses"
            assert body["model"] == "gpt-6.1-sol"
            assert body["reasoning"] == {"effort": "low", "summary": "auto"}
            assert body["stream"] is True
        assert [observed(result) for result in rig.results()] == ["clipped"]
        assert rig.window.log[-1] == "done Read it."


def test_agent_uses_responses_with_max_reasoning_and_opens_without_approval(tmp_path: Path) -> None:
    """Astra needs Responses for tools; compatible endpoints reject extra parameters."""
    target = r"C:\Users\Jim\Downloads\budget.xlsx"
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, calls(("open", {"target": target})), says("Opened the workbook."), work=durable(tmp_path))

        def respond(request: Received) -> Reply:
            assert rig.window.log[-1] == "step Waiting for the model..."
            body = cast("dict[str, Json]", json.loads(request.body))
            assert request.path == "/v1/responses"
            assert body["reasoning"] == {"effort": "max", "summary": "auto"}
            assert body["store"] is False
            assert body["include"] == ["reasoning.encrypted_content"]
            if unsupported := set(body) - {"model", "input", "instructions", "tools", "reasoning", "store", "include", "stream"}:
                return Reply(dumps({"error": {"message": f"Unrecognized fields: {sorted(unsupported)}"}}).encode(), status=400)
            return rig.endpoint.replies.pop(0)

        endpoint.respond = respond
        rig.run(f"Open {target}")
        assert rig.machine.log == [f"open {target}"]
        assert rig.window.log[-1] == "done Opened the workbook."


def test_agent_preserves_reasoning_between_tool_calls_and_follow_ups(tmp_path: Path) -> None:
    reasoning: Json = {"id": "rs_test", "type": "reasoning", "summary": [], "encrypted_content": "opaque-reasoning"}
    call: Json = {"type": "function_call", "call_id": "call_test", "name": "get_clipboard", "arguments": "{}"}
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, response(reasoning, message("Reading."), call), says("Read it."), work=durable(tmp_path))
        rig.run(effort="high")
        assert reasoning in rig.sent()
        assert cast(dict[str, Json], json.loads(endpoint.last.body))["reasoning"] == {"effort": "high", "summary": "auto"}
        endpoint.replies = [says("It said clipped.")]
        rig.run("What did it say?", effort="high")
        assert reasoning in rig.sent()


def test_invalid_reasoning_effort_is_reported_without_a_request(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, says("unused"), work=durable(tmp_path))
        rig.run(effort="typo")
        assert not endpoint.received
        assert rig.window.log == ["problem Invalid WORKSPACE_AGENT_REASONING_EFFORT: 'typo'."]


def test_follow_up_keeps_the_prompt_answer_and_tool_results(tmp_path: Path) -> None:
    (tmp_path / "budget.xlsx").touch()
    with fake_endpoint() as endpoint:
        rig = Rig(
            endpoint, calls(("find_files", {"folder": str(tmp_path), "pattern": "*.xlsx"})), says("I found budget.xlsx."), work=durable(tmp_path)
        )
        rig.run("Find my workbook.")
        endpoint.replies = [calls(("open", {"target": str(tmp_path / "budget.xlsx")})), says("Opened it.")]
        rig.run("Open that one.")
        follow_up = rig.sent(2)
        assert [m["content"] for m in follow_up if m.get("role") == "user"] == ["Find my workbook.", "Open that one."]
        assert "I found budget.xlsx." in json.dumps(follow_up[-2])
        assert any(m.get("type") == "function_call_output" and observed(m["output"]) == str(tmp_path / "budget.xlsx") for m in follow_up)
        assert f"open {tmp_path / 'budget.xlsx'}" in rig.machine.log


def test_failed_turn_keeps_completed_actions_for_the_follow_up(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, calls(("get_clipboard", {})), Reply(b'{"error": {"message": "unavailable"}}', status=503), work=durable(tmp_path))
        rig.run("Read the clipboard.")
        endpoint.replies = [says("It said clipped.")]
        rig.run("What did it say?")
        assert [m["content"] for m in rig.sent() if m.get("role") == "user"] == ["Read the clipboard.", "What did it say?"]
        assert any(m.get("type") == "function_call_output" and observed(m["output"]) == "clipped" for m in rig.sent())


def test_stopped_turn_keeps_completed_actions_and_accepts_a_follow_up(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, calls(("get_clipboard", {})), work=durable(tmp_path))
        rig.run("Read the clipboard.", after_step=rig.stop.set)
        assert rig.window.log[-1] == "done Stopped."
        rig.stop.clear()
        endpoint.replies = [says("It said clipped.")]
        rig.run("What did it say?")
        assert any(m.get("type") == "function_call_output" and observed(m["output"]) == "clipped" for m in rig.sent())


def test_desktop_requests_do_not_prepare_a_source_workspace(tmp_path: Path) -> None:
    workspace = source(tmp_path)
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, calls(("list_windows", {})), says("Outlook is open."), workspace=workspace, work=durable(tmp_path))
        rig.run("What is open?")
        assert rig.window.log[-1] == "done Outlook is open."
    assert not workspace.root.exists()


def test_every_call_gets_a_result_even_bad_ones(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, calls(("no_such_tool", {}), ("read_file", {})), says("Sorry."), work=durable(tmp_path))
        rig.run()
        assert "Error: read_file arguments are invalid: path: Field required." in rig.results()
        assert any("no_such_tool" in result for result in rig.results())


def test_stop_ends_the_task_before_the_next_step(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, calls(("get_clipboard", {})), calls(("get_clipboard", {})), says("never"), work=durable(tmp_path))
        rig.run(after_step=rig.stop.set)
        assert len(endpoint.received) == 1
        assert rig.window.log[-1] == "done Stopped."


def test_the_agent_stops_after_its_step_limit(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, *(calls(("get_clipboard", {})) for _ in range(4)), work=durable(tmp_path))
        rig.run(max_steps=3)
        assert len(endpoint.received) == 3
        assert rig.window.log[-1] == "done Stopped after 3 steps, not finished."


def test_model_failures_end_the_task(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, Reply(b'{"error": {"message": "model overloaded"}}', status=503), work=durable(tmp_path))
        rig.run()
        assert "503" in rig.window.log[-1] and "model overloaded" in rig.window.log[-1]


def test_effects_are_recorded_as_durable_actions(tmp_path: Path) -> None:
    # Defect: a tool performs its effect without the durable action record that recovery reads.
    work = durable(tmp_path)
    rig = ToolRig(work=work)
    assert rig.call("set_clipboard", text="hi").ok
    assert rig.machine.log == ["clipboard hi"]
    assert [action.specification.tool for action in work.store.actions(work.claim.task.id)] == ["set_clipboard"]


def test_tool_publishes_readable_previews_without_changing_the_model_result(tmp_path: Path) -> None:
    rig = ToolRig(work=durable(tmp_path))
    result = rig.call("inspect_ui", query="Budget " * 60)
    started, completed = rig.window.live
    assert isinstance(started, ToolActivity) and isinstance(completed, ToolActivity)
    assert started.outcome is ToolStatus.RUNNING and isinstance(completed.outcome, Succeeded)
    assert started.detail.startswith("Find controls matching “Budget") and started.detail.endswith("…")
    assert completed.identity == started.identity and completed.detail == started.detail
    assert "• Save" in activity_text(completed) and '"controls"' not in activity_text(completed)
    assert result.ok and observed(result.text) == '{"controls":[{"id":"1.2.3","name":"Save","actions":["invoke"]}]}'


# ---- what needs permission -------------------------------------------------------------


def test_commands_need_confirmation(tmp_path: Path) -> None:
    rig = ToolRig(approvals=True, work=durable(tmp_path))
    result = rig.call("run_powershell", command="Remove-Item C:\\temp\\x")
    assert not result.ok and result.text == "The user declined: don't run this. Ask them, or try something else."
    assert not rig.machine.executed


def test_commands_run_and_report_their_output(tmp_path: Path) -> None:
    rig = ToolRig(work=durable(tmp_path))
    rig.machine.commands = {"Stop-Process -Name notepad": (1, "no such process")}
    result = rig.call("run_powershell", command="Stop-Process -Name notepad")
    assert not result.ok and result.text == "Exit code 1.\nno such process"
    assert rig.machine.executed == [("Stop-Process -Name notepad", 120, None, rig.agent.stop)]


def test_allowed_commands_run_without_asking(tmp_path: Path) -> None:
    rig = ToolRig(approvals=True, work=durable(tmp_path))
    for timeout in (1, 600):
        result = rig.call("run_powershell", command="git status", timeout_seconds=timeout, cwd="work folder")
        assert result.ok and result.text == "Exit code 0.\nok"
        assert rig.machine.executed[-1] == ("git status", timeout, "work folder", rig.agent.stop)
    assert rig.machine.log == ["ran git status", "ran git status"]
    for timeout in (0, 601):
        assert not rig.call("run_powershell", command="git status", timeout_seconds=timeout).ok
    assert len(rig.machine.executed) == 2


def test_allowed_means_nothing_can_be_chained_on() -> None:
    assert allowed("Get-ChildItem C:\\Users -Recurse")
    assert allowed("git log --oneline -5")
    for sneaky in ("git status; Remove-Item x", "Get-Content a | Set-Content b", "git log && del x", "Get-Date $(rm x)", "git log > out.txt"):
        assert not allowed(sneaky), sneaky
    assert not allowed("Get-ChildItemX")
    assert not allowed("Remove-Item x")


def test_clicks_before_any_screenshot_are_refused(tmp_path: Path) -> None:
    rig = ToolRig(work=durable(tmp_path))
    result = rig.call("click", x=1, y=1)
    assert not result.ok and result.text == "Error: take a screenshot first; coordinates are in the latest screenshot."
    assert not rig.machine.log


# ---- screenshots -----------------------------------------------------------------------


def test_screenshots_go_to_the_model_as_images_and_only_recent_ones_are_kept(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        shots = [calls(("screenshot", {})) for _ in range(4)]
        rig = Rig(endpoint, *shots, says("ok"), work=durable(tmp_path))
        rig.run()
        last = rig.sent()
        images = [m for m in last if "input_image" in json.dumps(m.get("output"))]
        assert len(images) == 2
        tool_calls = [item["call_id"] for item in last if item.get("type") == "function_call"]
        results = [item["call_id"] for item in last if item.get("type") == "function_call_output"]
        assert results == tool_calls
        assert "[an earlier screenshot, removed to save space]" in json.dumps(last)
        assert "1280x720" in rig.results()[0]


def test_follow_ups_keep_only_recent_screenshots_in_memory_and_in_requests(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, calls(("screenshot", {})), calls(("screenshot", {})), says("I see the screen."), work=durable(tmp_path))
        rig.run("Look at the screen.")
        endpoint.replies = [calls(("screenshot", {})), says("It changed.")]
        rig.run("Look again.")
        assert rig.history.encoded().decode().count("data:image/png") == 2
        assert len([m for m in rig.sent() if "input_image" in json.dumps(m.get("output"))]) == 2
        tool_calls = [item["call_id"] for item in rig.sent() if item.get("type") == "function_call"]
        results = [item["call_id"] for item in rig.sent() if item.get("type") == "function_call_output"]
        assert results == tool_calls


# ---- files -----------------------------------------------------------------------------


def test_read_file_returns_text_and_says_when_it_was_cut(tmp_path: Path) -> None:
    big = tmp_path / "big.log"
    rig = ToolRig(work=durable(tmp_path))
    for length in (19_999, 20_000, 20_001, 50_000):
        big.write_text("x" * length, encoding="utf-8")
        result = rig.call("read_file", path=str(big))
        suffix = f"\n[cut: showing 20000 of {length} characters]" if length > 20_000 else ""
        assert result.ok and observed(result.text) == "x" * min(length, 20_000) + suffix


def test_find_files_matches_names_under_a_folder(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "report.xlsx").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    rig = ToolRig(work=durable(tmp_path))
    result = rig.call("find_files", folder=str(tmp_path), pattern="*.xlsx")
    assert result.ok and observed(result.text) == str(tmp_path / "a" / "report.xlsx")
    for name in ("second.xlsx", "third.xlsx"):
        (tmp_path / name).touch()
    bounded = rig.call("find_files", folder=str(tmp_path), pattern="*.xlsx", limit=2)
    lines = observed(bounded.text).splitlines()
    assert bounded.ok and "[stopped at 2 files]" in lines
    assert len(lines) == 3 and len(set(lines)) == 3


def test_approval_mode_writes_no_file_before_a_durable_approval(tmp_path: Path) -> None:
    # Defect: write_file performs its effect without consulting the approval gate.
    target = tmp_path / "out" / "reports" / "summary.md"
    rig = ToolRig(approvals=True, work=durable(tmp_path))
    declined = rig.call("write_file", path=str(target), content="not approved")
    assert not declined.ok and not target.exists()
    assert rig.agent.work.disposition is not None


def test_default_tools_write_run_and_control_the_desktop_without_approval(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    command = "Get-Location; Write-Output done"
    with fake_endpoint() as endpoint:
        rig = Rig(
            endpoint,
            calls(("write_file", {"path": str(target), "content": "Done"}), ("run_powershell", {"command": command})),
            calls(("screenshot", {})),
            calls(("click", {"x": 10, "y": 20}), ("type_text", {"text": "hello"}), ("press_keys", {"keys": "enter"})),
            says("Done."),
            work=durable(tmp_path),
        )
        rig.run()
        assert target.read_text(encoding="utf-8") == "Done"
        assert f"ran {command}" in rig.machine.log
        assert "click left x1 at 20,40" in rig.machine.log
        assert "type hello" in rig.machine.log
        assert any(entry.startswith("keys ") for entry in rig.machine.log)


def test_stop_prevents_actions_even_with_approvals_disabled(tmp_path: Path) -> None:
    stopped = threading.Event()
    stopped.set()
    machine = FakeMachine()
    agent = Agent(Settings("", "", "", "", "", "", ""), machine, FakeWindow(), stopped, work=durable(tmp_path), toolset=General)
    target = tmp_path / "not-written.txt"
    for name, args in (
        ("write_file", {"path": str(target), "content": "no"}),
        ("run_powershell", {"command": "Get-Date"}),
        ("open", {"target": str(target)}),
        ("type_text", {"text": "no"}),
        ("set_clipboard", {"text": "no"}),
    ):
        result = agent.call(ToolCall("stopped", name, json.dumps(args)))
        assert not result.ok and result.text == "Stopped by the user."
    assert not target.exists()
    assert not machine.log


# ---- keys ------------------------------------------------------------------------------


def test_key_combinations() -> None:
    ctrl, shift, s = 0xA2, 0xA0, 0x53
    assert key_strokes("ctrl+shift+s") == [(ctrl, True), (shift, True), (s, True), (s, False), (shift, False), (ctrl, False)]
    assert key_strokes("Enter") == [(0x0D, True), (0x0D, False)]
    assert key_strokes("alt+f4") == [(0xA4, True), (0x73, True), (0x73, False), (0xA4, False)]
    assert key_strokes("ctrl+banana") is None


# ---- changing Workspace itself -------------------------------------------------------


def source(tmp_path: Path) -> Workspace:
    return Workspace(live_tree(tmp_path / "live"), tmp_path / "workspace")


EDIT: Final = ("edit_source", {"path": "config.py", "old": "'hej'", "new": "'hello'"})


def test_the_agent_edits_checks_and_applies_a_change(tmp_path: Path) -> None:
    workspace = source(tmp_path)
    with fake_endpoint() as endpoint:
        apply = ("apply_changes", {"summary": "Say hello"})
        rig = Rig(endpoint, calls(EDIT), calls(("check_changes", {})), calls(apply), says("never asked"), workspace=workspace, work=durable(tmp_path))
        rig.run("greet in English")
        assert rig.machine.log == ["install Say hello"]
        assert "1 passed, 0 failed" in rig.results(2)[0]
        assert rig.window.log[-1] == "done Installing: Say hello. Workspace restarts in a moment."
        assert len(endpoint.received) == 3  # the task ends with the install


def test_apply_needs_a_passing_check_of_exactly_these_changes(tmp_path: Path) -> None:
    workspace = source(tmp_path)
    second = ("edit_source", {"path": "config.py", "old": "'hello'", "new": "'hi'"})
    apply = ("apply_changes", {"summary": "x"})
    with fake_endpoint() as endpoint:
        rig = Rig(
            endpoint,
            calls(EDIT),
            calls(apply),
            calls(("check_changes", {})),
            calls(second),
            calls(apply),
            says("ok"),
            workspace=workspace,
            work=durable(tmp_path),
        )
        rig.run()
        assert rig.results(2) == ["Error: run check_changes first; only checked changes can be installed."]
        assert rig.results(5) == ["Error: the changes have changed since they were checked; run check_changes again."]
        assert rig.machine.log == []


def test_failing_checks_are_reported_and_block_apply(tmp_path: Path) -> None:
    workspace = source(tmp_path)
    breaking = ("write_source", {"path": "config.py", "content": "GREETING = (\n"})
    with fake_endpoint() as endpoint:
        rig = Rig(
            endpoint,
            calls(breaking),
            calls(("check_changes", {})),
            calls(("apply_changes", {"summary": "x"})),
            says("ok"),
            workspace=workspace,
            work=durable(tmp_path),
        )
        rig.run()
        assert "doesn't compile" in rig.results(2)[0]
        assert rig.results(3) == ["Error: the last check failed; fix the changes and check again."]
        assert not any(entry.startswith("install") for entry in rig.machine.log)


def test_protected_files_cant_be_edited(tmp_path: Path) -> None:
    workspace = source(tmp_path)
    result = ToolRig(workspace=workspace, work=durable(tmp_path)).call("write_source", path="keeper.py", content="x")
    assert not result.ok and result.text.startswith("Error: keeper.py is protected")


def test_first_source_use_starts_from_the_running_version(tmp_path: Path) -> None:
    workspace = source(tmp_path)
    workspace.root.mkdir()
    (workspace.root / "leftover.py").write_text("x = 1\n", encoding="utf-8")
    result = ToolRig(workspace=workspace, work=durable(tmp_path)).call("show_changes")
    assert result.ok and observed(result.text) == "No changes yet."
    assert not (workspace.root / "leftover.py").exists()


def test_source_edits_survive_follow_up_requests(tmp_path: Path) -> None:
    workspace = source(tmp_path)
    with fake_endpoint() as endpoint:
        rig = Rig(
            endpoint,
            calls(("write_source", {"path": "draft.py", "content": "x = 1\n"})),
            says("Drafted."),
            workspace=workspace,
            work=durable(tmp_path),
        )
        rig.run("Make a draft.")
        endpoint.replies = [calls(("read_source", {"path": "draft.py"})), says("The draft is still here.")]
        rig.run("Read the draft back.")
        assert [observed(result) for result in rig.results()] == ["x = 1\n"]
        assert not (workspace.live / "draft.py").exists()


def test_reading_and_listing_the_source(tmp_path: Path) -> None:
    rig = ToolRig(workspace=source(tmp_path), work=durable(tmp_path))
    listing = rig.call("list_source")
    text = rig.call("read_source", path="config.py")
    assert listing.ok and "config.py" in observed(listing.text).splitlines()
    assert text.ok and observed(text.text) == "GREETING = 'hej'\n"


def test_without_a_workspace_there_are_no_source_tools(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, says("ok"), work=durable(tmp_path))
        rig.run()
        assert b"read_source" not in endpoint.last.body


def test_git_external_execution_options_require_confirmation() -> None:
    for command in ("git diff --ext-diff", "git log --textconv", "git diff --output=out.txt", "git diff --o=out.txt"):
        assert not allowed(command), command


def test_approval_mode_runs_no_candidate_code_before_approval(tmp_path: Path) -> None:
    workspace = source(tmp_path)
    marker = tmp_path / "outside-workspace"
    content = f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n'
    rig = ToolRig(approvals=True, workspace=workspace, work=durable(tmp_path))
    assert rig.call("write_source", path="candidate.py", content=content).ok
    assert not rig.call("check_changes").ok
    assert not marker.exists(), "unapproved code executed during checks"


def test_fast_editing_checks_leave_native_failures_for_the_full_install_gate(tmp_path: Path) -> None:
    workspace = source(tmp_path)
    (workspace.live / "tests/test_windows_native.py").write_text("def test_native():\n    assert False, 'native failure'\n")
    rig = ToolRig(workspace=workspace, work=durable(tmp_path))
    assert rig.call("edit_source", path="config.py", old="'hej'", new="'hello'").ok
    checked = rig.call("check_changes")
    assert checked.ok and "1 native module deferred" in checked.text
    passed, report = workspace.check()
    assert not passed and "FAILED tests.test_windows_native.test_native" in report


def test_runtime_failure_returns_to_the_agent_to_fix_before_installing(tmp_path: Path) -> None:
    workspace = source(tmp_path)
    check: tuple[str, Mapping[str, Json]] = ("check_changes", {})
    apply = ("apply_changes", {"summary": "Fix greeting"})
    with fake_endpoint() as endpoint:
        rig = Rig(
            endpoint,
            calls(("write_source", {"path": "config.py", "content": "GREETING = ''\n"})),
            calls(check),
            calls(apply),
            calls(("write_source", {"path": "config.py", "content": "GREETING = 'hello'\n"})),
            calls(check),
            calls(apply),
            workspace=workspace,
            work=durable(tmp_path),
        )
        rig.run("Fix the greeting")
        assert "FAILED tests.test_config.test_greeting" in rig.results(2)[0]
        assert "the last check failed" in rig.results(3)[0]
        assert "1 passed, 0 failed" in rig.results(5)[0]
        assert rig.machine.log == ["install Fix greeting"]
