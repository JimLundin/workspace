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
from assistant.agent_tools import Output
from assistant.browser_requests import BrowserRequest, Screenshot
from assistant.browser_values import BrowserError
from assistant.llm import Settings, ToolCall, settings_from
from assistant.meeting_tools import MeetingOperation
from assistant.task_profiles import General
from assistant.uia import UiRequest
from assistant.web_apps import Located, WebAppOperation
from assistant.work_bridge_contracts import BridgeCommand
from assistant.workspace import Workspace
from automation.actions import Resources
from automation.execution import WorkExecution
from automation.store import TaskStore
from contracts.agent_session import activity_text
from contracts.geometry import Shot
from contracts.json_value import Json
from contracts.presentation import LiveMessage, Succeeded, ToolActivity, ToolStatus
from contracts.task import RequestSource
from tests.fake_endpoint import FakeEndpoint, Received, Reply, fake_endpoint, sse
from tests.test_workspace import live_tree
from winapi.shapes import Rect


def no_feed(_command: BridgeCommand) -> str:
    raise OSError("No feed bridge in this test.")


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


def durable(folder: Path) -> WorkExecution:
    """Every agent run executes one claimed durable task."""
    identity = uuid.uuid4().hex
    store = TaskStore(folder / "agent-work" / identity / "work.sqlite3")
    store.submit(identity, "Agent fixture", "do it", RequestSource("chat"), at=1)
    claim = store.claim("worker", identity, at=2)
    assert claim is not None
    return WorkExecution(claim, store, Resources())


def observed(output: object) -> str:
    """Durable observations append their evidence identifier to the model's result."""
    assert isinstance(output, str)
    text, marker, identity = output.rpartition("\n[observation_id: ")
    assert marker and identity.endswith("]"), output
    return text


class FakeMachine:
    __slots__ = ("commands", "executed", "log", "meetings")

    def __init__(self) -> None:
        self.log: list[str] = []
        self.meetings: list[MeetingOperation] = []
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

    def close_background(self, *, keep_browser: bool = False) -> None:
        pass

    def meeting(self, operation: MeetingOperation) -> str:
        self.meetings.append(operation)
        return "Meeting state supplied."

    def get_clipboard(self) -> str | None:
        return "clipped"

    def set_clipboard(self, text: str) -> None:
        self.log.append(f"clipboard {text}")

    def open(self, target: str) -> None:
        self.log.append(f"open {target}")

    def install(self, summary: str, digest: str, checked: str | None) -> None:
        self.log.append(f"install {summary}" + (" after its fast check" if checked is not None else ""))


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
        effort: str = "max",
    ) -> None:
        settings = Settings(
            self.endpoint.url,
            "k",
            "transcribe",
            "",
            agent_reasoning_effort=effort,
        )
        agent = Agent(
            settings,
            self.machine,
            self.window,
            self.stop,
            work=self.work,
            toolset=lambda agent: General(agent, workspace=self.workspace, feed_request=no_feed),
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
        workspace: Workspace | None = None,
        machine: FakeMachine | None = None,
        clock: Callable[[], datetime] = datetime.now,
        feed_request: Callable[[BridgeCommand], str] = no_feed,
    ) -> None:
        self.machine = machine if machine is not None else FakeMachine()
        self.window = FakeWindow()
        self.agent = Agent(
            Settings("", "", "", ""),
            self.machine,
            self.window,
            threading.Event(),
            work=work,
            toolset=lambda agent: General(agent, workspace=workspace, clock=clock, feed_request=feed_request),
        )

    def call(self, name: str, **arguments: Json) -> Output:
        return self.agent.call(ToolCall("fixture", name, dumps(arguments)))


# ---- the loop --------------------------------------------------------------------------


def test_general_agent_receives_shared_work_grouping_and_local_evidence_tools(tmp_path: Path) -> None:
    # Defect: profile composition drops the canvas grouping/research policy or
    # omits the tools needed to collect local evidence from the model request.
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, says("Research complete."), work=durable(tmp_path))
        rig.run("Research this work on my canvas.")
        request = cast("dict[str, Json]", json.loads(endpoint.last.body))
        assert "Group contributions by their shared outcome" in str(request)
        assert "relevant evidence on the user's machine" in str(request)
        assert "resolve meaningful ambiguity" in str(request)
        assert "ask_user pauses this task" in str(request)
        tools = cast("list[dict[str, Json]]", request["tools"])
        offered = frozenset(tool["name"] for tool in tools)
        assert {
            "find_files",
            "read_file",
            "run_powershell",
            "work_items_add_document",
            "work_items_list",
            "work_canvas_update",
            "ask_user",
        } <= offered


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


def test_default_agent_model_with_low_reasoning_reaches_every_tool_turn(tmp_path: Path) -> None:
    # Defect: the default agent model fails to reach the SDK on every turn.
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, calls(("get_clipboard", {})), says("Read it."), work=durable(tmp_path))
        settings = settings_from({"OPENAI_BASE_URL": endpoint.url, "OPENAI_API_KEY": "k"})
        assert isinstance(settings, Settings)
        agent = Agent(settings, rig.machine, rig.window, rig.stop, work=durable(tmp_path), toolset=lambda agent: General(agent, feed_request=no_feed))
        agent.run("Read the clipboard.")
        assert len(endpoint.received) == 2
        for request in endpoint.received:
            body = cast("dict[str, Json]", json.loads(request.body))
            assert request.path == "/v1/responses"
            assert body["model"] == "gpt-6-astra"
            assert body["reasoning"] == {"effort": "low", "summary": "auto"}
            assert body["stream"] is True
        assert [observed(result) for result in rig.results()] == ["clipped"]
        assert rig.window.log[-1] == "done Read it."


def test_agent_uses_responses_with_max_reasoning_and_opens_directly(tmp_path: Path) -> None:
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
        rig = Rig(endpoint, calls(("desktop_state", {})), says("Outlook is open."), workspace=workspace, work=durable(tmp_path))
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


def test_transient_endpoint_failures_resume_without_repeating_completed_effects(tmp_path: Path) -> None:
    # Defect: disabling request retries blocks recoverable work; restarting the run repeats effects.
    for status in (429, 503):
        with fake_endpoint() as endpoint:
            rig = Rig(
                endpoint,
                calls(("set_clipboard", {"text": "saved"})),
                Reply(b'{"error": {"message": "temporarily unavailable"}}', status=status),
                says("Saved."),
                work=durable(tmp_path),
            )
            rig.run("Save this text to the clipboard.")
            assert rig.window.log[-1] == "done Saved."
            assert rig.machine.log == ["clipboard saved"]
            assert len(endpoint.received) == 3
            assert endpoint.received[1].body == endpoint.received[2].body
            assert rig.results() == ["Copied."]


def test_permanent_and_exhausted_endpoint_failures_end_the_turn(tmp_path: Path) -> None:
    # Defect: retrying invalid/auth requests or unlimited retries leaves the task running.
    # One permanent and one transient status; the SDK owns the rest of its classification.
    for status, attempts in ((401, 1), (503, 3)):
        with fake_endpoint() as endpoint:
            rig = Rig(endpoint, Reply(b'{"error": {"message": "request refused"}}', status=status), work=durable(tmp_path))
            rig.run()
            assert len(endpoint.received) == attempts
            assert rig.window.log[-1].startswith("problem Endpoint request failed:")
            assert str(status) in rig.window.log[-1] and "request refused" in rig.window.log[-1]
            assert not rig.machine.log


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


def test_a_failing_command_finishes_but_an_interrupted_one_waits_for_reconciliation(tmp_path: Path) -> None:
    # Detect a nonzero exit blocking later changes again (a failing test run ended
    # self-modification), or an interrupted command ending the task before the
    # model can reconcile it.
    rig = ToolRig(work=durable(tmp_path))
    rig.machine.commands = {"pytest": (1, "1 failed"), "sleep": (-1, "Timed out")}
    assert rig.call("run_powershell", command="pytest").text == "Exit code 1.\n1 failed"
    assert rig.call("run_powershell", command="git status").ok
    assert not rig.call("run_powershell", command="sleep").ok
    refused = rig.call("run_powershell", command="git status")
    assert not refused.ok and "reconcile_action" in refused.text
    assert rig.agent.work.disposition is None
    assert [entry[0] for entry in rig.machine.executed] == ["pytest", "git status", "sleep"]


def test_commands_run_only_within_their_timeout_bounds(tmp_path: Path) -> None:
    rig = ToolRig(work=durable(tmp_path))
    for timeout in (1, 600):
        result = rig.call("run_powershell", command="git status", timeout_seconds=timeout, cwd="work folder")
        assert result.ok and result.text == "Exit code 0.\nok"
        assert rig.machine.executed[-1] == ("git status", timeout, "work folder", rig.agent.stop)
    assert rig.machine.log == ["ran git status", "ran git status"]
    rig.call("run_powershell", command="git status")
    assert rig.machine.executed[-1] == ("git status", 120, None, rig.agent.stop)  # the default timeout
    for timeout in (0, 601):
        assert not rig.call("run_powershell", command="git status", timeout_seconds=timeout).ok
    assert len(rig.machine.executed) == 3


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


def test_default_tools_write_run_and_capture_the_desktop_directly(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    command = "Get-Location; Write-Output done"
    with fake_endpoint() as endpoint:
        rig = Rig(
            endpoint,
            calls(("write_file", {"path": str(target), "content": "Done"}), ("run_powershell", {"command": command})),
            calls(("screenshot", {})),
            says("Done."),
            work=durable(tmp_path),
        )
        rig.run()
        assert target.read_text(encoding="utf-8") == "Done"
        assert f"ran {command}" in rig.machine.log
        assert "screenshot" in rig.machine.log


def test_stop_prevents_actions(tmp_path: Path) -> None:
    stopped = threading.Event()
    stopped.set()
    machine = FakeMachine()
    agent = Agent(
        Settings("", "", "", ""),
        machine,
        FakeWindow(),
        stopped,
        work=durable(tmp_path),
        toolset=lambda agent: General(agent, feed_request=no_feed),
    )
    target = tmp_path / "not-written.txt"
    for name, args in (
        ("write_file", {"path": str(target), "content": "no"}),
        ("run_powershell", {"command": "Get-Date"}),
        ("open", {"target": str(target)}),
        ("set_clipboard", {"text": "no"}),
    ):
        result = agent.call(ToolCall("stopped", name, json.dumps(args)))
        assert not result.ok and result.text == "Stopped by the user."
    assert not target.exists()
    assert not machine.log


# ---- changing Workspace itself -------------------------------------------------------


def source(tmp_path: Path) -> Workspace:
    return Workspace(live_tree(tmp_path / "live"), tmp_path / "workspace")


EDIT: Final = ("edit_source", {"path": "config.py", "old": "'hej'", "new": "'hello'"})


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


def test_invalid_task_and_source_arguments_never_reach_the_journal_or_source(tmp_path: Path) -> None:
    # Defect: a malformed self-change or task call reaches an action record or
    # the workspace before its arguments are validated at the seam.
    work = durable(tmp_path)
    workspace = source(tmp_path)
    rig = ToolRig(workspace=workspace, work=work)
    invalid: tuple[tuple[str, dict[str, Json]], ...] = (
        ("write_source", {"path": "draft.py"}),
        ("edit_source", {"path": "config.py", "old": "'hej'"}),
        ("apply_changes", {"summary": 5}),
        ("reconcile_action", {"action_id": "a", "observation_id": "o", "applied": "yes"}),
        ("ask_user", {"question": 5}),
    )
    for name, arguments in invalid:
        result = rig.call(name, **arguments)
        assert not result.ok and result.text.startswith(f"Error: {name} arguments are invalid"), (name, result.text)
    assert work.disposition is None and not work.store.actions(work.claim.task.id)
    assert not workspace.root.exists() or "draft.py" not in workspace.files()


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


def test_editing_checks_report_affected_native_failures_before_install(tmp_path: Path) -> None:
    # Defect: check_changes defers native modules, so their failures surface only as keeper refusals.
    workspace = source(tmp_path)
    native = "import config\n\n\ndef test_native():\n    assert config.GREETING == 'hej', 'native failure'\n"
    (workspace.live / "tests/test_windows_native.py").write_text(native)
    rig = ToolRig(workspace=workspace, work=durable(tmp_path))
    assert rig.call("edit_source", path="config.py", old="'hej'", new="'hello'").ok
    checked = rig.call("check_changes")
    assert not checked.ok and "FAILED tests.test_windows_native.test_native" in checked.text


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
        assert rig.machine.log == ["install Fix greeting after its fast check"]
        assert rig.window.log[-1] == "done Installing: Fix greeting. Workspace restarts in a moment."
        assert len(endpoint.received) == 6  # the task ends with the install
