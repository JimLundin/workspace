"""Readable work labels and details for the work and meeting panels."""

from datetime import datetime
from typing import assert_never

from automation.task import (
    Blocked,
    Completed,
    Failed,
    Interrupted,
    Question,
    Running,
    Task,
    TaskStatus,
    Until,
    Waiting,
    phase,
)


def when(at: float | None) -> str:
    if at is None:
        return "—"
    try:
        return datetime.fromtimestamp(at).strftime("%Y-%m-%d %H:%M")
    except OverflowError, OSError, ValueError:
        return "Outside the local calendar"


def task_label(task: Task) -> str:
    match task.state:
        case Waiting(Question()):
            return "Your reply"
        case Waiting(Blocked()):
            return "Needs attention"
        case _:
            return phase(task.state).capitalize()


def task_detail(task: Task) -> str:
    sections = [
        task.title,
        f"{task_label(task)} · Your request\nCreated {when(task.created_at)} · Updated {when(task.updated_at)}",
        f"Instructions\n{task.prompt}",
    ]
    if task.checkpoint is not None:
        sections.append(f"Progress · {when(task.checkpoint.at)}\n{task.checkpoint.summary}")
    match task.state:
        case Completed(result, evidence):
            sections.append(f"Result\n{result}")
            if evidence:
                sections.append("Evidence\n" + "\n".join(f"• {item}" for item in evidence))
        case Failed(reason):
            sections.append(f"Needs attention\n{reason}")
        case Interrupted(_, reason):
            sections.append(f"Recovery\n{reason}\n\nResume checks the interrupted work before continuing.")
        case Waiting(reason):
            match reason:
                case Question(_, question, detail):
                    sections.append(f"Your reply\n{question}" + (f"\n\n{detail}" if detail else ""))
                case Until(at, explanation):
                    sections.append(f"Waiting until {when(at)}\n{explanation}")
                case Blocked(explanation):
                    sections.append(f"Waiting\n{explanation}")
                case _:
                    assert_never(reason)
        case TaskStatus.PAUSED:
            sections.append("Paused\nResume continues this saved task.")
        case TaskStatus.CANCELLED:
            sections.append("Cancelled\nThe task and its saved progress remain available.")
        case TaskStatus.READY | Running():
            pass
        case _:
            assert_never(task.state)
    return "\n\n".join(sections)
