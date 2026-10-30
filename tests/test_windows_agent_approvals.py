"""Tool approvals belong to the session; they must not open foreground dialogs."""

import json
import queue
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

if sys.platform != "win32":
    raise unittest.SkipTest("Windows tool UI")

from assistant.agent import Agent
from assistant.agent_input import Inputs
from assistant.agent_session import Approval, Event, InputCancelled
from assistant.llm import Settings, ToolCall
from assistant.machine import WinMachine
from tests.test_agent import FakeWindow
from tests.test_windows_machine import Browser, Desktop, Teams


class InlineUi:
    __slots__ = ("requests",)

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, bool]] = []

    def agent_input(
        self,
        title: str,
        detail: str = "",
        *,
        question: bool = False,
        cancel: threading.Event | None = None,
    ) -> str | None:
        self.requests.append((title, detail, question))
        return "The budget workbook" if question else "approve"


class WaitingUi:
    __slots__ = ("events", "inputs")

    def __init__(self) -> None:
        self.events: queue.Queue[Event] = queue.Queue()
        self.inputs = Inputs(self.events.put)

    def agent_input(
        self,
        title: str,
        detail: str = "",
        *,
        question: bool = False,
        cancel: threading.Event | None = None,
    ) -> str | None:
        return self.inputs.ask(title, detail, question=question, cancel=cancel)


def test_open_tool_runs_without_approval_by_default() -> None:
    ui = InlineUi()
    opened: list[str] = []
    machine = WinMachine(Desktop(), ui, browser=Browser(), teams=Teams(), open_target=opened.append)
    agent = Agent(Settings("", "", "", "", "", "", ""), machine, FakeWindow(), threading.Event(), journal=lambda entry: None)
    arguments: dict[str, str] = {"target": r"C:\example\budget.xlsx"}
    result = agent.call(ToolCall("open-1", "open", json.dumps(arguments)))
    assert ui.requests == []
    assert opened == [r"C:\example\budget.xlsx"]
    assert result.ok


def test_agent_question_uses_the_session_without_a_separate_text_prompt() -> None:
    ui = InlineUi()
    opened: list[str] = []
    machine = WinMachine(Desktop(), ui, browser=Browser(), teams=Teams(), open_target=opened.append)
    agent = Agent(Settings("", "", "", "", "", "", ""), machine, FakeWindow(), threading.Event(), journal=lambda entry: None)
    result = agent.call(ToolCall("question-1", "ask_user", '{"question":"Which workbook?"}'))
    assert result.text == "The budget workbook"
    assert ui.requests == [("Which workbook?", "", True)]
    assert opened == []


def test_stop_cancels_an_open_tool_while_its_inline_approval_is_waiting() -> None:
    ui = WaitingUi()
    stopped = threading.Event()
    opened: list[str] = []
    machine = WinMachine(Desktop(), ui, browser=Browser(), teams=Teams(), open_target=opened.append)
    agent = Agent(
        Settings("", "", "", "", "", "", "", agent_approvals=True),
        machine,
        FakeWindow(),
        stopped,
        journal=lambda entry: None,
    )

    with ThreadPoolExecutor(max_workers=1) as worker:
        result = worker.submit(agent.call, ToolCall("open-1", "open", '{"target":"budget.xlsx"}'))
        try:
            assert isinstance(ui.events.get(timeout=2), Approval)
            stopped.set()
            assert not result.result(timeout=2).ok, "Stop must unblock a waiting tool without a user click."
            assert opened == []
            assert isinstance(ui.events.get(timeout=2), InputCancelled)
        finally:
            stopped.set()
            ui.inputs.cancel_all()
