"""Native meeting identity, conversation and automatic canvas intake through real journals."""

from dataclasses import replace
from pathlib import Path
from unittest import TestCase

from assistant.meeting_events import TranscriptEvents
from assistant.meeting_store import MeetingArchive, MeetingStore
from assistant.meetings import Meetings
from assistant.personal_work_service import PersonalWork
from assistant.personal_work_store import PersonalStore
from assistant.work_bridge import WorkOwners
from assistant.work_bridge_contracts import BRIDGE_COMMAND, BRIDGE_RESPONSE
from assistant.work_canvas import pending
from assistant.work_canvas_commands import MoveBubble, UpdateCanvas, edited, revision
from assistant.work_canvas_context import context_path
from assistant.work_canvas_model import CanvasDocument, caption
from automation.meetings import Ended, InProgress, MeetingConversation, TranscriptState, UnknownEnd
from automation.personal_work import Association, ListSources, MeetingSource, ReadMeeting, SaveWork, WorkDefinition
from automation.routines import RoutineStore
from automation.store import TaskStore
from tests.feed_fixture import feed_unavailable
from tests.personal_work_fixture import CapturedSources
from tests.test_llm import settings
from tests.test_meetings import SPEECH, GeneratedCapture, wait_for
from tests.test_work_canvas import local_canvas


def test_meeting_stop_preserves_wall_clock_time_and_ordered_conversation(tmp_path: Path) -> None:
    # Defect: end time is inferred from sample counts/export time, a retry moves it,
    # or journal reads lose ordered transcript spans, silence gaps or meeting identity.
    store = MeetingStore.create(tmp_path, "both", "Supplier approval")
    started = store.state().started
    assert isinstance(store.meeting().period, InProgress)
    for _ in range(30):
        store.append(SPEECH)
    first = store.batch()
    assert first is not None
    store.complete(first, "Approval SA-42 was accepted.")
    store.append(bytes(len(SPEECH)))
    store.finish_capture(at=started + 120)
    silent = store.batch()
    assert silent is not None
    store.complete(silent, "")
    store.finish_capture(at=started + 180)
    store.export()
    reopened = MeetingStore(store.folder)
    page = reopened.conversation(limit=1)
    assert page.meeting.identity == store.folder.name and page.meeting.title == "Supplier approval"
    assert page.meeting.period == Ended(started, started + 120)
    assert page.meeting.captured_seconds == 31 and page.meeting.pending_seconds == 0
    assert page.meeting.transcript_state is TranscriptState.COMPLETE
    assert page.total == 1 and page.next_offset is None
    assert [(entry.start_seconds, entry.end_seconds, entry.text, entry.speaker) for entry in page.entries] == [
        (0, 30, "Approval SA-42 was accepted.", "unknown")
    ]
    assert "Ended " in store.transcript.read_text(encoding="utf-8")


def test_interrupted_meeting_does_not_invent_an_end_at_recovery(tmp_path: Path) -> None:
    # Defect: the recovery owner uses restart time as the capture end, restarts
    # capture, or a subsequent stop changes the unknown end.
    store = MeetingStore.create(tmp_path, "microphone")
    store.append(SPEECH)
    capture = GeneratedCapture(1)

    def transcribe(audio: bytes, *, context: str) -> str:
        return "Recovered speech."

    recorder = Meetings(
        settings("https://fixture.invalid/v1"),
        lambda source: capture,
        archive=MeetingArchive(tmp_path),
        transcribe_audio=transcribe,
    )
    try:
        recorder.start_worker()
        wait_for(lambda: store.state().complete)
    finally:
        recorder.close()
    store.finish_capture(at=store.state().started + 3600)
    meeting = MeetingStore(store.folder).meeting()
    assert meeting.period == UnknownEnd(store.state().started)
    assert "Workspace closed" in meeting.problem and meeting.transcript_state is TranscriptState.COMPLETE
    assert not capture.opened.is_set()


def test_meeting_intake_is_durable_idempotent_and_independent_of_notes_routine(tmp_path: Path) -> None:
    # Defect: disabled routines prevent native intake, recovery duplicates meetings,
    # or rereading an unchanged journal unnecessarily changes the catalog revision.
    archive = MeetingArchive(tmp_path / "meetings")
    store = archive.create("both", "Planning")
    tasks = TaskStore(tmp_path / "work.sqlite3")
    personal_store = PersonalStore(tasks.path)
    personal = PersonalWork(personal_store, CapturedSources(), lambda view: None, clock=lambda: 20)
    routines = RoutineStore(personal_store.path)
    routines.ensure_meeting_notes(at=10)
    errors: list[str] = []
    events = TranscriptEvents(archive, routines, on_error=errors.append, on_meeting=personal.observe_meeting)
    events.recover(archive.journals())
    first = personal_store.read()
    assert len(first.sources) == 1 and isinstance(first.sources[0], MeetingSource)
    store.append(SPEECH)
    store.finish_capture()
    batch = store.batch()
    assert batch is not None
    store.complete(batch, "Ship on Friday.")
    store.export()
    # Defect: a clock correction makes newer journal state look older and leaves
    # the meeting permanently recording on the canvas. Journal revisions own freshness.
    corrected_clock = PersonalWork(personal_store, CapturedSources(), lambda view: None, clock=lambda: 10)
    corrected_clock.observe_meeting(store)
    corrected = personal_store.read().sources[0]
    assert isinstance(corrected, MeetingSource) and corrected.meeting.transcript_state is TranscriptState.COMPLETE
    events.completed(store)
    observed = personal_store.read()
    personal_store.observe((replace(first.sources[0], observed_at=100),))
    assert personal_store.read() == observed, "A delayed capture snapshot replaced its newer completed event."
    events.completed(store)
    events.recover(archive.journals())
    assert personal_store.read() == observed
    assert observed.sources[0].id == first.sources[0].id and "Ship on Friday" in observed.sources[0].excerpt
    assert not routines.pending(30) and not errors


def test_capture_publishes_native_event_and_completed_conversation_to_intake(tmp_path: Path) -> None:
    # Defect: composition publishes only the recorder animation, never inserts
    # the native event, or starts repeated research before transcription finishes.
    archive = MeetingArchive(tmp_path / "meetings")
    tasks = TaskStore(tmp_path / "work.sqlite3")
    store = PersonalStore(tasks.path)
    personal = PersonalWork(store, CapturedSources(), lambda view: None)
    errors: list[str] = []
    events = TranscriptEvents(archive, RoutineStore(store.path), on_error=errors.append, on_meeting=personal.observe_meeting)
    capture = GeneratedCapture(1, hold=True)

    def transcribe(audio: bytes, *, context: str) -> str:
        return "Supplier approval SA-42."

    recorder = Meetings(
        settings("https://fixture.invalid/v1"),
        lambda source: capture,
        archive=archive,
        transcribe_audio=transcribe,
        on_meeting=events.observe,
        on_complete=events.completed,
        on_recovery=events.recover,
    )
    try:
        recorder.start(title="Planning event")
        assert capture.opened.wait(5)
        active = store.read()
        assert len(active.sources) == 1 and isinstance(active.sources[0], MeetingSource)
        assert isinstance(active.sources[0].meeting.period, InProgress)
        assert not pending(active, CanvasDocument(), ())
        recorder.stop()
        wait_for(lambda: recorder.snapshot().phase == "saved")
        complete = store.read()
        assert len(complete.sources) == 1 and complete.sources[0].id == active.sources[0].id
        assert len(pending(complete, CanvasDocument(), ())) == 1 and not errors
    finally:
        recorder.close()


def test_agent_reads_meeting_pages_and_links_one_event_to_multiple_threads(tmp_path: Path) -> None:
    # Defect: native meetings are flattened into documents, lost through the owner
    # bridge, duplicated across contexts, or return only the preview as conversation.
    archive = MeetingArchive(tmp_path / "meetings")
    meeting = archive.create("both", "Decisions")
    for text in ("Approval SA-42.", "The rollout is Friday."):
        for _ in range(30):
            meeting.append(SPEECH)
        batch = meeting.batch()
        assert batch is not None
        meeting.complete(batch, text)
    meeting.finish_capture()
    meeting.export()
    personal_store = PersonalStore(tmp_path / "work.sqlite3")
    personal = PersonalWork(personal_store, CapturedSources(), lambda view: None)
    personal.observe_meeting(meeting)
    source = personal_store.read().sources[0]
    for title in ("Supplier approval", "Friday rollout"):
        personal_store.handle(SaveWork(WorkDefinition(title, title), (Association(source.id, title + " discussed in this meeting."),)), 10)
    owners = WorkOwners(feed_unavailable, personal.handle, local_canvas(tmp_path).command)
    request = BRIDGE_COMMAND.validate_json(BRIDGE_COMMAND.dump_json(ReadMeeting(source.id, limit=1)))
    page = BRIDGE_RESPONSE.validate_json(BRIDGE_RESPONSE.dump_json(owners.handle(request)))
    assert isinstance(page, MeetingConversation) and page.meeting.identity == meeting.folder.name
    assert page.total == 2 and page.next_offset == 1 and page.entries[0].text == "Approval SA-42."
    next_page = personal_store.handle(ReadMeeting(source.id, offset=1, limit=1), 10)
    assert isinstance(next_page, MeetingConversation) and next_page.entries[0].start_seconds == 30 and next_page.next_offset is None
    with TestCase().assertRaisesRegex(ValueError, "native meeting"):
        personal_store.handle(ReadMeeting("unknown"), 10)
    catalog = personal_store.read()
    assert len(catalog.sources) == 1 and all(work.links[0].source_id == source.id for work in catalog.works)
    assert caption(source).startswith("Meeting · ")
    document = CanvasDocument()
    moved = edited(document, UpdateCanvas(revision(document), (MoveBubble(source.id, catalog.works[0].id),)), catalog)
    assert context_path(source.id, catalog, moved) == (catalog.works[0].id, source.id)
    assert personal_store.handle(ListSources(), 10).kind == "work_sources"
