"""What the island reads of the agent's live session."""

from assistant.agent_session import ChatMessage, Session
from automation.presentation import ReasoningSummary, Succeeded, ToolActivity
from desktop_ui.island_agent import activity
from desktop_ui.island_model import Agent
from tests.agent_requests import asked

REQUEST = ChatMessage("You", "Compare the budget sheets", 1)


def test_the_phase_is_the_running_tool_or_the_latest_summary_heading() -> None:
    # Defects: a finished tool still reads as the phase, or a summary's whole paragraph reaches the bar.
    summary = ReasoningSummary("s", "**Comparing both sheets**\n\nRevenue first, then costs.", 2)
    assert activity(Session(phase="running", messages=(REQUEST, summary))) == Agent("Comparing both sheets", waiting=False)
    running = ToolActivity("t", "run_powershell", "Get-Content budget.csv", 3)
    assert activity(Session(phase="running", messages=(REQUEST, summary, running))) == Agent("PowerShell", waiting=False)
    done = ToolActivity("t", "run_powershell", "Get-Content budget.csv", 3, Succeeded("12 rows"))
    assert activity(Session(phase="running", messages=(REQUEST, summary, done))) == Agent("Comparing both sheets", waiting=False)


def test_rest_stopping_and_a_waiting_question_read_as_the_bar_needs() -> None:
    # Defects: an idle agent keeps a capsule, Stop reads as work, or a waiting question is missed.
    assert activity(Session(messages=(REQUEST,))) is None
    assert activity(Session(phase="stopping", messages=(REQUEST,))) == Agent("Stopping…", waiting=False)
    assert activity(Session(phase="running", messages=(REQUEST,))) == Agent("Thinking", waiting=False)
    question = asked("q", "Which sheet?", "", 4)
    waiting = activity(Session(messages=(REQUEST, question)))
    assert waiting is not None and waiting.waiting
