"""Durable SDK turns, source checks and installation through application seams."""

import json
import threading
import time
from pathlib import Path

from assistant.agent import Agent
from assistant.agent_execution import AgentExecution
from assistant.llm import Settings, ToolCall
from assistant.task_profiles import General, GeneralEffects, Profiles, unseen
from automation.actions import Resources
from automation.execution import WorkExecution
from automation.store import TaskStore
from contracts.task import (
    Blocked,
    Claim,
    Completed,
    Question,
    RequestSource,
    TextAnswer,
    Waiting,
)
from tests.fake_endpoint import Reply, fake_endpoint
from tests.test_agent import FakeMachine, FakeWindow, calls, no_feed, says
from tests.test_work_actions import claimed


def request(store: TaskStore, identity: str, prompt: str, source: RequestSource | None = None) -> Claim:
    store.submit(identity, "Requested work", prompt, source or RequestSource("chat"), at=time.time())
    claim = store.claim("worker", identity + "-run", at=time.time())
    assert claim is not None
    return claim


def execution(settings: Settings, errors: list[str]) -> AgentExecution:
    machine = FakeMachine()
    return AgentExecution(
        settings,
        machine,
        Profiles.of(GeneralEffects(unseen, no_feed)),
        record=lambda record: None,
        report_error=errors.append,
        close_background=machine.close_background,
    )


class BrokenResultLog(FakeWindow):
    def done(self, text: str, /) -> None:
        raise ValueError("Private mail content must stay out of operational diagnostics")


def test_every_execution_releases_research_pages_and_stop_releases_the_browser(tmp_path: Path) -> None:
    # Defect: only Stop invokes cleanup, leaving completed, suspended or failed
    # tasks' research pages alive in the shared worker's browser.
    store = TaskStore(tmp_path / "work.sqlite3")
    cleaned: tuple[bool, ...] = ()
    errors: list[str] = []

    def cleanup(*, keep_browser: bool) -> None:
        nonlocal cleaned
        cleaned += (keep_browser,)

    with fake_endpoint() as endpoint:
        adapter = AgentExecution(
            Settings(endpoint.url, "fixture", "transcribe", ""),
            FakeMachine(),
            Profiles.of(GeneralEffects(unseen, no_feed)),
            record=lambda record: None,
            report_error=errors.append,
            close_background=cleanup,
        )
        for identity, log in (("completed", FakeWindow()), ("suspended", FakeWindow()), ("failed", BrokenResultLog()), ("stopped", FakeWindow())):
            endpoint.replies = [calls(("ask_user", {"question": "Which source?"}))] if identity == "suspended" else [says("Result")]
            stop = threading.Event()
            if identity == "stopped":
                stop.set()
            claim = request(store, identity, "Research this work", RequestSource(identity))
            outcome = adapter.run_work(claim, store, log, stop)
            assert store.finish(claim.run, outcome, at=time.time()) is not None
        assert cleaned == (True, True, True, False)
        assert len(errors) == 1 and "ValueError" in errors[0]


def test_durable_execution_failure_preserves_safe_fault_locations(tmp_path: Path) -> None:
    # Defect: the execution owner discards the actionable fault location or
    # writes private source/exception content into the automation worker log.
    store = TaskStore(tmp_path / "work.sqlite3")
    errors: list[str] = []
    with fake_endpoint() as endpoint:
        endpoint.replies = [says("Result")]
        settings = Settings(endpoint.url, "fixture", "transcribe", "")
        claim = request(store, "task", "Research this work")
        result = execution(settings, errors).run_work(claim, store, BrokenResultLog(), threading.Event())
    assert isinstance(result, Waiting) and isinstance(result.reason, Blocked)
    assert len(errors) == 1 and "ValueError" in errors[0] and "test_work_execution.py:" in errors[0]
    assert "Private mail" not in errors[0] and "raise ValueError" not in errors[0]


def test_question_suspends_and_recorded_answer_survives_a_fresh_sdk_process_owner(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "work.sqlite3")
    errors: list[str] = []
    with fake_endpoint() as endpoint:
        settings = Settings(endpoint.url, "fixture", "transcribe", "")
        endpoint.replies = [calls(("ask_user", {"question": "Which report folder?"}))]
        first = request(store, "task", "Prepare the report.")
        outcome = execution(settings, errors).run_work(first, store, FakeWindow(), threading.Event())
        assert isinstance(outcome, Waiting) and isinstance(outcome.reason, Question)
        assert len(endpoint.received) == 1
        assert store.finish(first.run, outcome, at=time.time()) is not None
        assert store.answer("task", outcome.reason.id, TextAnswer("Use the Finance reports folder."), at=time.time()) is not None
        reopened = TaskStore(tmp_path / "work.sqlite3")
        resumed = reopened.claim("restarted-worker", "resumed-run", at=time.time())
        assert resumed is not None
        endpoint.replies = [calls(("ask_user", {"question": "Which report folder?"})), says("The report folder is resolved.")]
        result = execution(settings, errors).run_work(resumed, reopened, FakeWindow(), threading.Event())
        assert isinstance(result, Completed), (result, errors)
        assert "Use the Finance reports folder." in endpoint.received[-1].body.decode("utf-8")
        assert not errors


def test_endpoint_failure_and_step_limit_never_report_completion(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "work.sqlite3")
    errors: list[str] = []
    with fake_endpoint() as endpoint:
        settings = Settings(endpoint.url, "fixture", "transcribe", "")
        first = request(store, "unavailable", "Inspect the computer.")
        endpoint.replies = [Reply(b'{"error":{"message":"model unavailable"}}', status=503)]
        outcome = execution(settings, errors).run_work(first, store, FakeWindow(), threading.Event())
        assert isinstance(outcome, Waiting) and isinstance(outcome.reason, Blocked)
        assert "Endpoint request failed" in outcome.reason.reason and len(endpoint.received) == 3
        assert store.finish(first.run, outcome, at=time.time()) is not None
        second = request(store, "limited", "Inspect the computer.")
        work = WorkExecution.begin(second, store, Resources())
        endpoint.replies = [calls(("get_clipboard", {}))]
        stop = threading.Event()
        agent = Agent(
            settings, FakeMachine(), FakeWindow(), stop, work=work, toolset=lambda agent: General.of(agent, feed_request=no_feed), max_steps=1
        )
        assert not agent.run(second.task.prompt)
        result = work.outcome(agent.report, stop)
        assert isinstance(result, Waiting) and isinstance(result.reason, Blocked)
        assert "not finished" in result.reason.reason and len(endpoint.received) == 4


def test_nonfinite_tool_arguments_never_enter_effect_storage(tmp_path: Path) -> None:
    store, claim, _ = claimed(tmp_path)
    work = WorkExecution.begin(claim, store, Resources())
    destination = tmp_path / "forbidden.txt"
    payload: dict[str, object] = {"path": str(destination), "content": "not written", "unexpected": float("nan")}
    args = json.dumps(payload)
    agent = Agent(
        Settings("", "", "", ""),
        FakeMachine(),
        FakeWindow(),
        threading.Event(),
        work=work,
        toolset=lambda agent: General.of(agent, feed_request=no_feed),
    )
    result = agent.call(ToolCall("invalid", "write_file", args))
    assert not result.ok and not destination.exists() and not store.actions("task")
