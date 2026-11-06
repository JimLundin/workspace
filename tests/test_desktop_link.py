"""The messages between the desktop and the assistant survive the wire exactly."""

from pathlib import Path

from contracts import desktop_link
from contracts.agent_session import ChatMessage, Session
from contracts.canvas_activity import CanvasRun, SessionRequest
from contracts.desktop_link import (
    AnswerCanvas,
    AutomaticChanged,
    CanvasChanged,
    CanvasNoticed,
    ContinueWork,
    EditCanvas,
    JobChanged,
    NoticesObserved,
    Notify,
    OpenReference,
    Record,
    RecordingChanged,
    ReplyFailed,
    RouteSpeech,
    SelectAttention,
    SessionChanged,
    ShowWork,
    SpeakToAgent,
    StartRun,
    ToAssistant,
    ToDesktop,
    UseTool,
    VoiceChanged,
    WireError,
    WorkChanged,
    WorkCommand,
    WorkShown,
    from_assistant,
    from_desktop,
    state_key,
    to_assistant,
    to_desktop,
)
from contracts.meeting_detection import AutomaticStatus
from contracts.personal_work import PersonalView
from contracts.recording_state import RecordingState
from contracts.status import Job, State
from contracts.task import Question, TaskStatus, TextAnswer, Waiting
from contracts.work_canvas_context import CanvasScope
from contracts.work_canvas_contracts import CanvasPublication
from contracts.work_canvas_edits import RenameGroup, UserEdit
from contracts.work_commands import RefreshPersonalWork
from contracts.work_snapshot import WorkSnapshot
from protocol import Tool
from tests.agent_requests import asked
from tests.test_work_canvas import catalog, local_canvas
from tests.test_work_window import work_task
from winapi.system_notices import Notice, NoticeKey, Observed


def publication(tmp_path: Path) -> CanvasPublication:
    published: list[CanvasPublication] = []
    canvas = local_canvas(tmp_path, published.append)
    canvas.observe_catalog(catalog())
    return published[-1]


def test_every_message_survives_the_wire_exactly(tmp_path: Path) -> None:
    # Defect: a message (or a value inside one: an enum, a union, a frozendict, a
    # nested question) changes or fails on its way between the processes.
    session = Session(identity="session", messages=(asked("chat", "Which supplier?", "", 10), ChatMessage("You", "Compare them", 11)))
    tasks = (work_task(), work_task(Waiting(Question("ask", "Which sheet?", "")), identity="waiting"))
    work = WorkSnapshot(tasks=tasks, personal=PersonalView(catalog()))
    to_the_desktop: tuple[ToDesktop, ...] = (
        SessionChanged(session),
        WorkChanged(work),
        CanvasChanged(publication(tmp_path)),
        VoiceChanged(State.LISTENING, agent_speaking=True),
        JobChanged(Job.TRANSCRIBING),
        JobChanged(None),
        RecordingChanged(RecordingState(phase="recording", seconds=12)),
        AutomaticChanged(AutomaticStatus.READY),
        ShowWork(focus=True),
        RouteSpeech("Move it to Friday"),
        Notify("Workspace", "The microphone is busy.", warning=True),
        OpenReference("https://example.com/report"),
        ReplyFailed(),
    )
    for message in to_the_desktop:
        assert from_assistant(to_desktop(message)) == message, message
    request = SessionRequest("session", "chat")
    to_the_assistant: tuple[ToAssistant, ...] = (
        UseTool(Tool.STOP),
        Record("start"),
        WorkCommand(RefreshPersonalWork.REFRESH),
        EditCanvas(UserEdit(CanvasScope(), RenameGroup("group:archive", "Archived work"))),
        StartRun(CanvasRun("canvas:1", "work:one")),
        ContinueWork("work:one"),
        AnswerCanvas(request, TextAnswer("Supplier B")),
        SelectAttention(request),
        SelectAttention(None),
        CanvasNoticed("New finding", "work:one"),
        SpeakToAgent("Summarise the thread"),
        NoticesObserved(Observed((Notice(NoticeKey(1, 2), "teams", "Teams", "Anna", "Are you joining?"),))),
        WorkShown(),
    )
    for command in to_the_assistant:
        assert from_desktop(to_assistant(command)) == command, command
    assert TaskStatus.READY is tasks[0].state


def test_a_frame_from_the_wrong_direction_or_a_broken_peer_is_refused() -> None:
    # Defect: a frame meant for the other side, or a garbled one, is acted on as
    # some message instead of being refused.
    for frame in (to_assistant(WorkShown()), b"Nonsense\n{}", b"SessionChanged\n{not json", b""):
        try:
            from_assistant(frame)
        except WireError:
            continue
        raise AssertionError(f"{frame!r} was accepted.")


def test_only_states_are_kept_and_replayed() -> None:
    # Defect: an event (a notification) is replayed to every desktop that connects,
    # or a state (the session) isn't, so a restarted desktop shows nothing current.
    assert state_key(SessionChanged(Session())) == "SessionChanged"
    assert state_key(Notify("Workspace", "Done")) is None
    assert desktop_link.state_key(JobChanged(None)) != state_key(VoiceChanged(State.READY, agent_speaking=False))
