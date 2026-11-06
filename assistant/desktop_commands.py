"""What the assistant does with each of the desktop's commands.

`DesktopCommands` carries out a `contracts.desktop_link` command against the
assistant's owners: the canvas document directly, everything else through
`Controls`. The assistant's control thread runs it for the link, and tests run it
in-process with real owners.
"""

import sqlite3
from typing import Protocol, assert_never

from assistant.agent_window import AgentWindow
from assistant.desktop_port import DesktopPort
from assistant.work_canvas import WorkCanvas
from contracts.canvas_activity import CanvasRequest
from contracts.desktop_attention import ToSession, ToTask, Undeliverable, delivery
from contracts.desktop_link import (
    AnswerCanvas,
    CanvasChanged,
    CanvasNoticed,
    CanvasStatus,
    ContinueWork,
    EditCanvas,
    NoticesObserved,
    Record,
    ReplyFailed,
    RunRefused,
    SelectAttention,
    SpeakToAgent,
    StartRun,
    ToAssistant,
    UseTool,
    WorkCommand,
    WorkShown,
)
from contracts.recording_state import RecordingAction
from contracts.task import TextAnswer
from contracts.work_canvas_contracts import Investigating, NotQueued, Queued, ResumeTask
from contracts.work_commands import WorkViewCommand
from protocol import Tool
from winapi.system_notices import Observed


class Controls(Protocol):
    """The assistant's owners a desktop command reaches, besides the canvas."""

    @property
    def session(self) -> AgentWindow | None:
        """The agent session, once the work frontend has asked for it."""
        ...

    def use_tool(self, tool: Tool) -> None: ...
    def recording_action(self, action: RecordingAction) -> None: ...
    def work_command(self, command: WorkViewCommand) -> None: ...
    def voice(self, text: str) -> None: ...
    def notify_canvas(self, title: str, target: str) -> None: ...
    def notices(self, observed: Observed) -> None: ...
    def refresh(self) -> None: ...
    def resume(self, task_id: str) -> None: ...
    def notify(self, title: str, text: str) -> None: ...
    def problem(self, message: str) -> None: ...


class DesktopCommands:
    __slots__ = ("_canvas", "_controls", "_desktop")

    def __init__(self, canvas: WorkCanvas, desktop: DesktopPort, controls: Controls) -> None:
        self._canvas, self._desktop, self._controls = canvas, desktop, controls

    def handle(self, message: ToAssistant) -> None:
        """Carry out one command; an owner's OSError, ValueError or sqlite3.Error is the caller's to report."""
        controls = self._controls
        match message:
            case UseTool(tool=tool):
                controls.use_tool(tool)
            case Record(action=action):
                controls.recording_action(action)
            case WorkCommand(command=command):
                controls.work_command(command)
            case EditCanvas(edit=edit):
                try:
                    self._canvas.commit(edit)
                except OSError, ValueError, sqlite3.Error:
                    # The desktop applied the edit to its copy; give it back the record.
                    self._desktop.send(CanvasChanged(self._canvas.publication()))
                    raise
            case StartRun(run=run):
                match self._canvas.start(run):
                    case NotQueued(reason=reason):
                        self._desktop.send(RunRefused(run, reason))
                    case Queued():
                        pass
            case ContinueWork(work_id=work_id):
                self.continue_work(work_id)
            case AnswerCanvas(request=request, answer=answer):
                if not self._canvas.answer(request, answer, self.deliver_answer):
                    self._desktop.send(ReplyFailed())
            case SelectAttention(request=request):
                if controls.session is not None:
                    controls.session.select_attention(request)
            case CanvasNoticed(title=title, target=target):
                controls.notify_canvas(title, target)
            case SpeakToAgent(text=text):
                controls.voice(text)
            case NoticesObserved(observed=observed):
                controls.notices(observed)
            case WorkShown():
                controls.refresh()
            case _:
                assert_never(message)

    def continue_work(self, work_id: str) -> None:
        match self._canvas.continue_work(work_id):
            case ResumeTask(task_id=task):
                self._controls.resume(task)
            case Investigating.ALREADY:
                self._desktop.send(CanvasStatus("This work already has an investigation in progress."))
            case NotQueued(reason=reason):
                self._desktop.send(CanvasStatus("Could not queue the investigation: " + reason))
            case Queued():
                pass

    def deliver_answer(self, request: CanvasRequest, answer: TextAnswer) -> bool:
        """A canvas question's answer goes to the conversation that asked it, or to its task."""
        session = self._controls.session
        match delivery(request, answer, session.snapshot().identity if session is not None else None):
            case ToSession(session_id=identity, request_id=key):
                return session is not None and session.respond(key, answer, expected_session=identity)
            case ToTask(command=command):
                try:
                    self._controls.work_command(command)
                except (OSError, ValueError) as error:
                    self._controls.problem(str(error))
                    return False
                return True
            case Undeliverable.STALE:
                return False
