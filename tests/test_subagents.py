"""Workspace's delegation policy through real SDK runs and a local endpoint."""

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from assistant.agent import Agent
from assistant.agent_tools import Tool
from assistant.llm import Settings, settings_from
from assistant.task_profiles import General
from automation.execution import Reported, ReportStatus
from automation.json_value import Json
from automation.presentation import Answer, Failed, Succeeded, ToolActivity, ToolStatus
from automation.task import Question, Waiting
from desktop_ui.agent_session import Begin, Session, transition
from tests.fake_endpoint import FakeEndpoint, Received, Reply, fake_endpoint
from tests.test_agent import FakeMachine, FakeWindow, calls, durable, no_feed, says


def body(request: Received) -> dict[str, Json]:
    return cast(dict[str, Json], json.loads(request.body))


def inputs(request: Received) -> list[dict[str, Json]]:
    return cast(list[dict[str, Json]], body(request)["input"])


def prompt(request: Received) -> str:
    return str(inputs(request)[0]["content"])


def outputs(request: Received) -> list[str]:
    return [str(item["output"]) for item in inputs(request) if item.get("type") == "function_call_output"]


def task(name: str, agent_class: str = "small") -> dict[str, Json]:
    return {"name": name, "prompt": name, "agent_class": agent_class}


def make_agent(endpoint: FakeEndpoint, folder: Path, machine: FakeMachine, window: FakeWindow) -> Agent:
    # Transport, local resources and observers vary independently in this fixture.
    return Agent(
        Settings(endpoint.url, "k", "transcribe", "chat", "manager", "", ""),
        machine,
        window,
        threading.Event(),
        work=durable(folder),
        toolset=lambda agent: General(agent, feed_request=no_feed),
        max_steps=15,
    )


def test_main_selects_four_configured_classes_and_receives_parallel_results(tmp_path: Path) -> None:
    # Defects: class choices use the manager model, overrides are ignored, child
    # requests run serially, or child conversations overwrite the manager's history.
    classes = ("small", "medium", "large", "extra_large")
    barrier = threading.Barrier(4)
    with fake_endpoint() as endpoint:
        settings = settings_from(
            {
                "OPENAI_BASE_URL": endpoint.url,
                "OPENAI_API_KEY": "k",
                "WORKSPACE_AGENT_MODEL": "manager",
                "WORKSPACE_AGENT_REASONING_EFFORT": "medium",
                **{f"WORKSPACE_SUBAGENT_{name.upper()}_MODEL": "model-" + name for name in classes},
            }
        )
        assert isinstance(settings, Settings)

        def respond(request: Received) -> Reply:
            if prompt(request) == "main":
                return (
                    says("Combined and verified.")
                    if outputs(request)
                    else calls(("delegate_subtasks", {"tasks": [task(name, name) for name in classes]}))
                )
            barrier.wait(timeout=5)
            return says("Private result for " + prompt(request))

        endpoint.respond = respond
        window = FakeWindow()
        agent = Agent(
            settings,
            FakeMachine(),
            window,
            threading.Event(),
            work=durable(tmp_path),
            toolset=lambda agent: General(agent, feed_request=no_feed),
        )
        assert agent.run("main")
        assert agent.report == Reported("Combined and verified.")
        children = [request for request in endpoint.received if prompt(request) != "main"]
        assert len(children) == 4
        for request in children:
            data = body(request)
            assert data["model"] == "model-" + prompt(request)
            assert data["reasoning"] == {"effort": "medium", "summary": "auto"}
            offered = cast(list[dict[str, Json]], data["tools"])
            assert "delegate_subtasks" not in {str(tool["name"]) for tool in offered}
        results = cast(list[dict[str, Json]], json.loads(outputs(endpoint.last)[0]))
        assert [(result["name"], result["agent_class"], result["kind"]) for result in results] == [(name, name, "completed") for name in classes]
        assert all(result["output"] == "Private result for " + str(result["name"]) for result in results)
        assert {str(item["name"]) for item in cast(list[dict[str, Json]], agent.history.read()) if item.get("type") == "function_call"} == {
            "delegate_subtasks"
        }
        assert not any(isinstance(item, Answer) and "Private result" in item.text for item in window.live)
        session = transition(Session(), Begin("main", 0))
        for event in window.live:
            session = transition(session, event)
        children_shown = [item for item in session.messages if isinstance(item, ToolActivity) and item.name == "subagent"]
        assert len(children_shown) == 4 and all(item.outcome == Succeeded("Completed.") for item in children_shown)


class HeldClipboard(FakeMachine):
    """A concrete machine whose first clipboard read needs external release."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.second = threading.Event()
        self.release = threading.Event()
        self.reads = 0

    def get_clipboard(self) -> str:
        self.reads += 1
        if self.reads == 1:
            self.entered.set()
            assert self.release.wait(timeout=5)
        else:
            self.second.set()
        return "Clipboard evidence."


def test_children_share_serialized_tools_and_the_durable_evidence_owner(tmp_path: Path) -> None:
    # Defect: resource-free tool decisions run while another complete tool call
    # owns the session, or child evidence is recorded outside the current claim.
    machine, window = HeldClipboard(), FakeWindow()
    barrier, queued = threading.Barrier(2), threading.Event()
    with fake_endpoint() as endpoint:

        def respond(request: Received) -> Reply:
            if prompt(request) == "main":
                return says("Verified both.") if outputs(request) else calls(("delegate_subtasks", {"tasks": [task("first"), task("second")]}))
            if outputs(request):
                assert "[observation_id: " in outputs(request)[0]
                return says("Verified " + prompt(request))
            barrier.wait(timeout=5)
            if prompt(request) == "first":
                return calls(("get_clipboard", {}))
            assert machine.entered.wait(timeout=5)
            queued.set()
            # Time observations intentionally acquire no journal resources.
            # They must still wait for the full tool/session owner to exit.
            return calls(("get_current_time", {}))

        def clock() -> datetime:
            machine.second.set()
            return datetime(2026, 11, 2, tzinfo=UTC)

        endpoint.respond = respond
        agent = Agent(
            Settings(endpoint.url, "k", "", "", "manager", "", ""),
            machine,
            window,
            threading.Event(),
            work=durable(tmp_path),
            toolset=lambda agent: General(agent, clock=clock, feed_request=no_feed),
        )
        worker = threading.Thread(target=lambda: agent.run("main"))
        worker.start()
        try:
            assert machine.entered.wait(timeout=5)
            assert queued.wait(timeout=5)
            assert not machine.second.wait(timeout=0.5), "A second machine call overlapped the first."
        finally:
            machine.release.set()
            worker.join(timeout=5)
        assert not worker.is_alive() and machine.reads == 1 and machine.second.is_set()
        assert agent.report == Reported("Verified both.")
        assert {item.tool for item in agent.work.observations} == {"get_clipboard", "get_current_time"}
        assert b'"name":"get_clipboard"' not in agent.history.encoded()


def test_stop_waits_for_an_active_effect_and_prevents_queued_child_effects(tmp_path: Path) -> None:
    # Defect: queued subagent calls act after Stop, or a run releases ownership
    # while a native operation is still running in its worker thread.
    machine, window = HeldClipboard(), FakeWindow()
    barrier = threading.Barrier(2)
    with fake_endpoint() as endpoint:

        def respond(request: Received) -> Reply:
            if prompt(request) == "main":
                return calls(("delegate_subtasks", {"tasks": [task("first"), task("second")]}))
            barrier.wait(timeout=5)
            return calls(("get_clipboard", {}))

        endpoint.respond = respond
        agent = make_agent(endpoint, tmp_path, machine, window)
        worker = threading.Thread(target=lambda: agent.run("main"))
        worker.start()
        try:
            assert machine.entered.wait(timeout=5)
            agent.stop.set()
            worker.join(timeout=0.2)
            assert worker.is_alive(), "An active native effect was abandoned."
        finally:
            machine.release.set()
            worker.join(timeout=5)
        assert not worker.is_alive() and machine.reads == 1
        assert agent.report is ReportStatus.STOPPED
        retained = cast(list[dict[str, Json]], json.loads(outputs_from_history(agent)[0]))
        assert len(retained) == 2 and all(result["kind"] == "failed" for result in retained)


def outputs_from_history(agent: Agent) -> list[str]:
    return [str(item["output"]) for item in cast(list[dict[str, Json]], agent.history.read()) if item.get("type") == "function_call_output"]


def test_stop_closes_all_stalled_child_streams_without_waiting_for_provider(tmp_path: Path) -> None:
    # Defect: only the manager observes Stop, leaving nested model streams alive.
    barrier, release = threading.Barrier(3), threading.Event()
    with fake_endpoint() as endpoint:

        def stream(request: Received) -> Iterator[bytes]:
            if prompt(request) == "main":
                yield calls(("delegate_subtasks", {"tasks": [task("first"), task("second")]})).body
                return
            yield b": waiting\n\n"
            barrier.wait(timeout=5)
            release.wait(timeout=5)
            yield says("Too late.").body

        endpoint.stream = stream
        window = FakeWindow()
        agent = make_agent(endpoint, tmp_path, FakeMachine(), window)
        worker = threading.Thread(target=lambda: agent.run("main"))
        worker.start()
        try:
            barrier.wait(timeout=5)
            agent.stop.set()
            worker.join(timeout=2)
            assert not worker.is_alive(), "Stop left a nested stream waiting for the provider."
            assert not release.is_set() and agent.report is ReportStatus.STOPPED
            assert len(endpoint.received) == 3
            children = [item for item in window.live if isinstance(item, ToolActivity) and item.name == "subagent"]
            assert sum(item.outcome is ToolStatus.CANCELLED for item in children) == 2
        finally:
            release.set()
            worker.join(timeout=5)


def test_invalid_batches_are_rejected_before_any_child_starts(tmp_path: Path) -> None:
    # Defect: malformed/oversized delegation partially starts children or an
    # unknown class falls back to a different, potentially expensive model.
    invalid: tuple[Json, ...] = (
        [task("a", "unknown")],
        [task(str(index)) for index in range(5)],
        [],
        [{"name": "a", "prompt": "  ", "agent_class": "small"}],
    )
    with fake_endpoint() as endpoint:
        endpoint.replies = [calls(*(("delegate_subtasks", {"tasks": tasks}) for tasks in invalid)), says("Corrected the request.")]
        window = FakeWindow()
        agent = make_agent(endpoint, tmp_path, FakeMachine(), window)
        assert agent.run("main")
        assert len(endpoint.received) == 2
        assert len(outputs(endpoint.last)) == 4 and all("arguments are invalid" in output for output in outputs(endpoint.last))
        assert not any(isinstance(item, ToolActivity) and item.name == "subagent" for item in window.live)


def test_child_clarification_suspends_the_task_and_closes_a_waiting_sibling(tmp_path: Path) -> None:
    # Defect: a child suspends the durable task while another child continues
    # waiting for a provider, preventing the clarification from reaching its owner.
    barrier, release = threading.Barrier(2), threading.Event()
    with fake_endpoint() as endpoint:

        def stream(request: Received) -> Iterator[bytes]:
            if prompt(request) == "main":
                yield calls(("delegate_subtasks", {"tasks": [task("question"), task("waiting")]})).body
                return
            if prompt(request) == "question":
                barrier.wait(timeout=5)
                yield calls(("ask_user", {"question": "Which document?"})).body
                return
            yield b": waiting\n\n"
            barrier.wait(timeout=5)
            release.wait(timeout=5)
            yield says("Too late.").body

        endpoint.stream = stream
        agent = make_agent(endpoint, tmp_path, FakeMachine(), FakeWindow())
        worker = threading.Thread(target=lambda: agent.run("main"))
        worker.start()
        try:
            worker.join(timeout=3)
            assert not worker.is_alive(), "Suspension left a sibling waiting for the provider."
            assert not release.is_set()
            disposition = agent.work.disposition
            assert isinstance(disposition, Waiting) and isinstance(disposition.reason, Question)
            assert disposition.reason.text == "Which document?" and not agent.stop.is_set()
            assert len(endpoint.received) == 3
        finally:
            release.set()
            worker.join(timeout=5)


def test_failed_child_returns_its_class_and_successful_siblings_to_the_manager(tmp_path: Path) -> None:
    # Defect: one provider failure discards other child results or is reported as
    # successful completion instead of allowing the manager to recover.
    with fake_endpoint() as endpoint:

        def respond(request: Received) -> Reply:
            if prompt(request) == "main":
                return (
                    says("Recovered the failed work.")
                    if outputs(request)
                    else calls(("delegate_subtasks", {"tasks": [task("good"), task("bad", "extra_large")]}))
                )
            return says("Good evidence.") if prompt(request) == "good" else Reply(b'{"error":{"message":"unavailable class"}}', status=400)

        endpoint.respond = respond
        window = FakeWindow()
        agent = make_agent(endpoint, tmp_path, FakeMachine(), window)
        assert agent.run("main")
        results = cast(list[dict[str, Json]], json.loads(outputs(endpoint.last)[0]))
        assert results[0] == {"name": "good", "agent_class": "small", "output": "Good evidence.", "kind": "completed"}
        assert results[1]["agent_class"] == "extra_large" and results[1]["kind"] == "failed" and "unavailable class" in str(results[1]["reason"])
        assert agent.report == Reported("Recovered the failed work.") and agent.work.disposition is None
        assert any(isinstance(item, ToolActivity) and item.name == "subagent" and isinstance(item.outcome, Failed) for item in window.live)


def test_child_turn_budget_is_bounded_and_does_not_finish_the_main_task(tmp_path: Path) -> None:
    # Defect: a child loops indefinitely, inherits the manager's larger budget,
    # or its limit ends the manager before it can handle the incomplete work.
    with fake_endpoint() as endpoint:

        def respond(request: Received) -> Reply:
            if prompt(request) == "main":
                return says("Handled the limit.") if outputs(request) else calls(("delegate_subtasks", {"tasks": [task("loop")]}))
            return calls(("get_clipboard", {}))

        endpoint.respond = respond
        agent = make_agent(endpoint, tmp_path, FakeMachine(), FakeWindow())
        assert agent.run("main")
        assert len([request for request in endpoint.received if prompt(request) == "loop"]) == 12
        result = cast(list[dict[str, Json]], json.loads(outputs(endpoint.last)[0]))[0]
        assert result["kind"] == "failed" and "turn limit" in str(result["reason"])
        assert agent.report == Reported("Handled the limit.")


def test_children_keep_the_profiles_tool_boundary_and_cannot_delegate(tmp_path: Path) -> None:
    # Defect: a restricted task gains general desktop/self-change tools through
    # delegation, or a child can recursively start more agents.
    class Restricted:
        def __init__(self, agent: Agent) -> None:
            self.tools: tuple[Tool, ...] = tuple(tool for tool in General(agent, feed_request=no_feed).tools if tool.spec.name == "get_clipboard")

        def instructions(self) -> str:
            return "Read only the selected evidence."

    with fake_endpoint() as endpoint:

        def respond(request: Received) -> Reply:
            if prompt(request) == "main":
                return says("Inspected the boundary.") if outputs(request) else calls(("delegate_subtasks", {"tasks": [task("restricted")]}))
            offered = cast(list[dict[str, Json]], body(request)["tools"])
            assert {str(tool["name"]) for tool in offered} == {"get_clipboard"}
            assert "Read only the selected evidence." in str(body(request)["instructions"])
            if not outputs(request):
                return calls(("open", {"target": "unapproved.txt"}), ("delegate_subtasks", {"tasks": [task("recursive")]}))
            assert len(outputs(request)) == 2 and all("not found" in output for output in outputs(request))
            return says("Kept the boundary.")

        endpoint.respond = respond
        machine, window = FakeMachine(), FakeWindow()
        agent = Agent(
            Settings(endpoint.url, "k", "", "", "manager", "", ""), machine, window, threading.Event(), work=durable(tmp_path), toolset=Restricted
        )
        assert agent.run("main") and machine.log == []
        assert len(endpoint.received) == 4
