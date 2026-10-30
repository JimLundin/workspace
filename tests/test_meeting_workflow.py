"""Meeting follow-through through real archives, requests, work, and package files."""

import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from unittest import TestCase

from assistant.meeting_followup import (
    ActionContent,
    ActionItem,
    ActionStatus,
    AssignedDue,
    AssignedOwner,
    CitedText,
    DraftContent,
    EmailDraft,
    Followup,
    TranscriptBundle,
    Unspecified,
    resolve_citation,
)
from assistant.meeting_followup_store import FollowupStore, PublishedFollowup, observe_transcript
from assistant.meeting_preparation import Preparations, PreparedFollowup
from assistant.meeting_store import MeetingArchive, MeetingStore
from assistant.meeting_workflow import (
    MAX_LISTED,
    ActionChange,
    ActionSaved,
    ActionSaveProblem,
    AvailablePackages,
    DraftChange,
    DraftSaved,
    DraftSaveProblem,
    MeetingSnapshot,
    MeetingWorkflow,
    ObservedWork,
    OpenedFollowup,
    OpenProblem,
    PackagesUnavailable,
    PrepareProblem,
    RecoveryProblem,
    WorkPending,
    WorkUnavailable,
)
from assistant.work_window import WorkSnapshot
from automation.task import Completed, MeetingFollowup, Profile, RequestSource, RoutineSource, Running
from tests.test_meeting_events import saved_meeting
from tests.test_meetings import SPEECH
from tests.test_work_agent import WorkRig


class WorkflowRig:
    __slots__ = ("archive", "errors", "followups", "preparations", "snapshots", "work", "workflow")

    def __init__(
        self,
        folder: Path,
        *,
        work: WorkRig | None = None,
        submit: Callable[[str, str, Profile], None] | None = None,
        read_work: Callable[[], WorkSnapshot] | None = None,
        start: bool = True,
    ) -> None:
        self.archive = MeetingArchive(folder / "meetings")
        self.preparations = Preparations(folder / "followups" / "preparations")
        self.followups = FollowupStore(folder / "followups" / "packages")
        self.work = work or WorkRig(folder / "work")
        self.errors: list[str] = []
        self.snapshots: list[MeetingSnapshot] = []
        self.workflow = MeetingWorkflow(
            self.archive,
            self.preparations,
            self.followups,
            submit_identified=submit or self.work.agent.submit_identified,
            read_work=read_work or self.work.agent.snapshot,
            journal=self.work.tasks.meeting_followups,
            publish=self.snapshots.append,
            report_error=self.errors.append,
            clock=self.work.clock,
        )
        if start:
            self.workflow.start()

    def refresh(self) -> MeetingSnapshot:
        assert self.workflow.refresh().wait(10), "The meeting observer did not finish its queued storage work."
        return self.workflow.snapshot()

    def settle(self) -> MeetingSnapshot:
        self.refresh()
        # The work queue is a different owner. Neither its row absence nor the
        # meeting observer's barrier can acknowledge that owner's commands.
        self.work.refresh()
        return self.refresh()

    def close(self) -> None:
        self.workflow.close()
        assert self.workflow.wait_closed(10)
        self.work.close()


class ObservationHold:
    __slots__ = ("armed", "entered", "read_work", "release")

    def __init__(self, read_work: Callable[[], WorkSnapshot]) -> None:
        self.read_work = read_work
        self.armed, self.entered, self.release = threading.Event(), threading.Event(), threading.Event()

    def __call__(self) -> WorkSnapshot:
        if self.armed.is_set():
            self.armed.clear()
            self.entered.set()
            assert self.release.wait(10)
        return self.read_work()


def opened(snapshot: MeetingSnapshot) -> OpenedFollowup:
    assert isinstance(snapshot.opened, OpenedFollowup), snapshot.opened
    return snapshot.opened


def prepare_meeting_from(rig: WorkflowRig, meeting: MeetingStore) -> OpenedFollowup:
    source = observe_transcript(meeting).source
    rig.workflow.prepare((source,))
    progress = rig.settle().preparations[0]
    assert isinstance(progress.work, ObservedWork)
    rig.workflow.open(progress.followup.task_id)
    result = opened(rig.refresh())
    assert tuple(item.source for item in result.request.bundle.transcripts) == (source,)
    return result


def prepare_meeting(rig: WorkflowRig) -> OpenedFollowup:
    return prepare_meeting_from(rig, saved_meeting(rig.archive, "Shipping review"))


def followup_for(bundle: TranscriptBundle, *, title: str = "Shipping review") -> Followup:
    quote = "The team decided to ship on Friday."
    citation = resolve_citation(bundle, bundle.transcripts[0].source.id, quote)
    return Followup(
        bundle,
        title,
        (CitedText(quote, (citation,)),),
        (),
        (ActionItem("ship", "Ship the reviewed release.", (citation,), Unspecified.NOT_STATED, Unspecified.NOT_STATED),),
        (EmailDraft("followup", "Shipping follow-up", quote, (), (citation,), ("ship",)),),
    )


def publish_package(rig: WorkflowRig, request: PreparedFollowup, *, title: str = "Shipping review") -> PublishedFollowup:
    return rig.followups.publish(rig.followups.plan(request.task_id, followup_for(request.bundle, title=title)))


def test_catalog_waits_for_capture_transcription_and_current_export_without_automatically_grouping(tmp_path: Path) -> None:
    rig = WorkflowRig(tmp_path)
    try:
        meeting = rig.archive.create("microphone", "Still recording")
        meeting.append(SPEECH)
        assert rig.refresh().transcripts == ()
        meeting.finish_capture()
        meeting.export()
        assert rig.refresh().transcripts == ()
        batch = meeting.batch()
        assert batch is not None
        meeting.complete(batch, "The team decided to ship on Friday.")
        assert rig.refresh().transcripts == ()
        meeting.export()
        source = observe_transcript(meeting).source
        assert rig.refresh().transcripts == (source,)
        unrelated = saved_meeting(rig.archive, "An unrelated customer call")
        assert {item.id for item in rig.refresh().transcripts} == {source.id, unrelated.folder.name}
        assert not rig.preparations.root.exists() and rig.work.tasks.list_tasks() == ()
        meeting.transcript.unlink()
        assert [item.id for item in rig.refresh().transcripts] == [unrelated.folder.name]
        assert not rig.errors
    finally:
        rig.close()


def test_multiple_segments_are_saved_before_queue_acceptance_and_duplicate_prepare_reuses_one_task(tmp_path: Path) -> None:
    # Defect: a task enters the queue before the recordings its profile names
    # are saved, or preparing the same selection twice creates a second task.
    work = WorkRig(tmp_path / "work", start=False)
    preparations = Preparations(tmp_path / "followups" / "preparations")
    accepted: list[PreparedFollowup] = []

    def submit(identity: str, prompt: str, profile: Profile) -> None:
        assert isinstance(profile, MeetingFollowup)
        prepared = preparations.read(identity, profile)
        assert prepared.prompt == prompt
        accepted.append(prepared)
        work.agent.submit_identified(identity, prompt, profile)

    rig = WorkflowRig(tmp_path, work=work, submit=submit)
    try:
        recordings = tuple(saved_meeting(rig.archive, f"Selected segment {index}") for index in range(3))
        selected = tuple(observe_transcript(meeting).source for meeting in recordings)
        rig.workflow.prepare(selected)
        rig.workflow.prepare(selected)
        pending = rig.refresh().preparations
        assert len(pending) == 1 and {prepared.task_id for prepared in accepted} == {pending[0].followup.task_id}
        assert pending[0].followup.title == "Meeting follow-up: Selected segment 0 + Selected segment 1 + Selected segment 2"
        rig.workflow.open(pending[0].followup.task_id)
        assert tuple(item.source for item in opened(rig.refresh()).request.bundle.transcripts) == selected
        assert pending[0].work is WorkPending.OBSERVATION and work.tasks.list_tasks() == ()
        work.agent.start_worker()
        progress = rig.settle().preparations[0]
        assert isinstance(progress.work, ObservedWork) and progress.work.task.id == pending[0].followup.task_id
        assert len(work.tasks.list_tasks()) == 1
        assert not rig.errors
    finally:
        rig.close()


def test_restart_lists_journaled_followups_from_their_saved_recordings_without_resubmitting(tmp_path: Path) -> None:
    # Defect: a failed submission is listed as pending work, or a restart loses
    # follow-ups whose original transcripts are gone or resubmits them.
    def unavailable(_identity: str, _prompt: str, _profile: Profile) -> None:
        raise OSError("The work queue is unavailable.")

    first = WorkflowRig(tmp_path, submit=unavailable)
    try:
        meeting = saved_meeting(first.archive, "Before restart")
        first.workflow.prepare((observe_transcript(meeting).source,))
        refused = first.settle()
        assert refused.preparations == () and any(isinstance(item, PrepareProblem) for item in refused.problems)
    finally:
        first.close()
    second = WorkflowRig(tmp_path)
    try:
        saved = prepare_meeting_from(second, meeting)
    finally:
        second.close()
    meeting.transcript.unlink()
    submitted: list[str] = []
    third = WorkflowRig(tmp_path, submit=lambda identity, _prompt, _profile: submitted.append(identity))
    try:
        recovered = third.settle()
        assert [item.followup.task_id for item in recovered.preparations] == [saved.request.task_id]
        assert isinstance(recovered.preparations[0].work, ObservedWork) and not submitted
        third.workflow.open(saved.request.task_id)
        assert opened(third.refresh()).request == saved.request
    finally:
        third.close()


def test_listing_many_followups_reads_no_recordings_and_opening_one_verifies_its_bundle(tmp_path: Path) -> None:
    # Defect: listing loads every follow-up's recordings, or opening one skips
    # verifying that its saved recordings still exist unchanged.
    rig = WorkflowRig(tmp_path)
    try:
        recordings = tuple(saved_meeting(rig.archive, f"Planning part {index}") for index in range(6))
        for meeting in recordings:
            rig.workflow.prepare((observe_transcript(meeting).source,))
        listed = rig.settle().preparations
        assert len(listed) == len(recordings) and all(isinstance(item.work, ObservedWork) for item in listed)
    finally:
        rig.close()
    retained = rig.preparations.root.with_name("retained-preparations")
    rig.preparations.root.rename(retained)
    reopened = WorkflowRig(tmp_path)
    try:
        relisted = reopened.settle()
        assert [item.followup for item in relisted.preparations] == [item.followup for item in listed]
        assert all(isinstance(item.work, ObservedWork) for item in relisted.preparations) and not relisted.problems
        newest = relisted.preparations[0].followup
        assert newest.title == "Meeting follow-up: Planning part 5"
        reopened.workflow.open(newest.task_id)
        missing = reopened.refresh().opened
        assert isinstance(missing, OpenProblem) and "Prepare the meeting follow-up again." in missing.reason
        retained.rename(reopened.preparations.root)
        reopened.workflow.open(relisted.preparations[1].followup.task_id)
        part_four = opened(reopened.refresh()).request
        assert part_four.bundle.transcripts[0].source.title == "Planning part 4"
        (reopened.preparations.root / f"{part_four.profile.bundle}.json").unlink()
        reopened.workflow.open(part_four.task_id)
        assert opened(reopened.refresh()).request == part_four, "Reopening the open follow-up must not read its bundle again."
        reopened.workflow.open(relisted.preparations[2].followup.task_id)
        assert opened(reopened.refresh()).request.bundle.transcripts[0].source.title == "Planning part 3"
    finally:
        reopened.close()


def test_followups_beyond_the_listed_bound_are_announced_instead_of_silently_dropped(tmp_path: Path) -> None:
    # Defect: older follow-ups disappear from the view without saying where they are.
    rig = WorkflowRig(tmp_path)
    try:
        for index in range(MAX_LISTED + 1):
            if index == MAX_LISTED:
                complete = rig.settle()
                assert len(complete.preparations) == MAX_LISTED and not complete.problems
            profile = MeetingFollowup(f"{index:064x}")
            rig.work.tasks.submit(f"meeting-{index}", f"Follow-up {index}", "Prepare notes.", RequestSource("chat", profile), at=index)
        snapshot = rig.settle()
        assert len(snapshot.preparations) == MAX_LISTED and snapshot.preparations[0].followup.title == f"Follow-up {MAX_LISTED}"
        assert any(isinstance(item, RecoveryProblem) and "older ones remain in Work" in item.reason for item in snapshot.problems)
    finally:
        rig.close()


def test_changed_transcripts_reject_stale_selection_and_create_a_distinct_source_version(tmp_path: Path) -> None:
    rig = WorkflowRig(tmp_path)
    try:
        original = prepare_meeting(rig)
        source = original.request.bundle.transcripts[0].source
        transcript = Path(source.path)
        transcript.write_bytes(transcript.read_bytes() + b"\nA correction was added after the first preparation.\n")
        rig.workflow.prepare((source,))
        stale = rig.settle()
        problem = next(item for item in stale.problems if isinstance(item, PrepareProblem))
        assert problem.selected == (source,) and "changed" in problem.reason
        assert [item.followup.task_id for item in stale.preparations] == [original.request.task_id] and len(rig.work.tasks.list_tasks()) == 1
        current = stale.transcripts[0]
        assert current.sha256 != source.sha256
        rig.workflow.prepare((current,))
        updated = rig.settle()
        assert len(updated.preparations) == 2 and len(rig.work.tasks.list_tasks()) == 2
        assert updated.preparations[0].followup.task_id != original.request.task_id
        assert updated.preparations[1].followup.task_id == original.request.task_id
        assert not any(isinstance(item, PrepareProblem) for item in updated.problems)
    finally:
        rig.close()


def test_failed_preparation_storage_retains_known_progress_and_submits_nothing_new(tmp_path: Path) -> None:
    rig = WorkflowRig(tmp_path)
    try:
        original = prepare_meeting(rig)
        second = saved_meeting(rig.archive, "A second selected meeting")
        selected = (observe_transcript(second).source,)
        root = rig.preparations.root
        retained = root.with_suffix(".retained")
        root.rename(retained)
        root.write_bytes(b"")
        try:
            rig.workflow.prepare(selected)
            snapshot = rig.settle()
            assert any(isinstance(item, PrepareProblem) and item.selected == selected for item in snapshot.problems)
            assert [item.followup.task_id for item in snapshot.preparations] == [original.request.task_id]
            assert isinstance(snapshot.preparations[0].work, ObservedWork)
            assert len(rig.work.tasks.list_tasks()) == 1
        finally:
            root.unlink()
            retained.rename(root)
        rig.workflow.prepare(selected)
        recovered = rig.settle()
        assert len(recovered.preparations) == 2 and len(rig.work.tasks.list_tasks()) == 2
        assert not recovered.problems
    finally:
        rig.close()


def test_progress_is_observed_by_task_and_narrative_completion_does_not_create_artifacts(tmp_path: Path) -> None:
    rig = WorkflowRig(tmp_path)
    try:
        prepared = prepare_meeting(rig)
        claim = rig.work.tasks.claim("meeting-worker", "meeting-run", at=rig.work.clock())
        assert claim is not None
        rig.work.tasks.progress(claim.run, "Read the selected recording.", at=rig.work.clock())
        progress = rig.settle().preparations[0]
        assert isinstance(progress.work, ObservedWork) and isinstance(progress.work.task.state, Running)
        assert progress.work.task.checkpoint is not None and progress.work.task.checkpoint.summary == "Read the selected recording."
        rig.work.tasks.finish(
            claim.run,
            Completed("The notes are ready in a claimed path, and the email draft is complete.", ()),
            at=rig.work.clock(),
        )
        finished = opened(rig.settle())
        assert isinstance(finished.packages, PackagesUnavailable) and not finished.packages.previous
        publication = publish_package(rig, prepared.request)
        verified = opened(rig.refresh()).packages
        assert isinstance(verified, AvailablePackages)
        assert [item.publication for item in verified.values] == [publication]
        assert verified.values[0].drafts[0].content.body == "The team decided to ship on Friday."
    finally:
        rig.close()


def test_foreign_task_and_source_packages_cannot_attach_to_a_meeting_preparation(tmp_path: Path) -> None:
    rig = WorkflowRig(tmp_path)
    try:
        meeting = saved_meeting(rig.archive, "The selected meeting")
        bundle = TranscriptBundle((observe_transcript(meeting),))
        prepared = Preparations(tmp_path / "elsewhere").prepare(bundle)
        identity = prepared.task_id
        foreign = rig.work.tasks.submit(identity, "Routine work", prepared.prompt, RoutineSource("routine", 0, "occurrence"), at=rig.work.clock())
        rig.workflow.prepare(tuple(item.source for item in bundle.transcripts))
        rejected = rig.settle().preparations[0]
        assert isinstance(rejected.work, WorkUnavailable) and rejected.work.previous is None
        assert "already belongs to a different request" in rejected.work.reason
        assert rig.work.tasks.get(identity) == foreign
        unrelated = saved_meeting(rig.archive, "Different source evidence")
        wrong_bundle = TranscriptBundle((observe_transcript(unrelated),))
        wrong = rig.followups.publish(rig.followups.plan(identity, followup_for(wrong_bundle)))
        rig.workflow.open(identity)
        observed = opened(rig.refresh())
        assert isinstance(observed.packages, PackagesUnavailable) and not observed.packages.previous
        change = DraftChange(identity, wrong.version, "followup", DraftContent("User draft", "User text", ()), 0, "foreign-draft-attempt")
        rig.workflow.save_draft(change)
        failed = rig.refresh().changes[-1]
        assert isinstance(failed, DraftSaveProblem) and failed.change == change
        assert rig.followups.drafts(identity, wrong.version)[0].revision == 0
    finally:
        rig.close()


def test_saved_edits_survive_late_packages_and_conflicts_retain_exact_unsaved_content(tmp_path: Path) -> None:
    rig = WorkflowRig(tmp_path)
    try:
        prepared = prepare_meeting(rig)
        published = publish_package(rig, prepared.request)
        rig.refresh()
        content = DraftContent("Edited subject", "My complete edited follow-up.\n\nPlease review the release.", ())
        draft_change = DraftChange(prepared.request.task_id, published.version, "followup", content, 0, "first-draft-edit")
        action_content = ActionContent("Ship the reviewed release.", AssignedOwner("Jim"), AssignedDue("Next Monday"), ActionStatus.DONE)
        action_change = ActionChange(prepared.request.task_id, published.version, "ship", action_content, 0, "first-action-edit")
        rig.workflow.save_draft(draft_change)
        rig.workflow.save_action(action_change)
        saved = rig.refresh()
        assert any(isinstance(item, DraftSaved) and item.change == draft_change and item.revision.revision == 1 for item in saved.changes)
        assert any(isinstance(item, ActionSaved) and item.change == action_change and item.revision.revision == 1 for item in saved.changes)
        competing = rig.followups.save_draft(
            prepared.request.task_id,
            published.version,
            "followup",
            replace(content, body="A newer saved edit."),
            expected_revision=1,
            at=rig.work.clock(),
        )
        unsaved = DraftChange(
            prepared.request.task_id,
            published.version,
            "followup",
            replace(content, body="Keep my unsaved draft intact."),
            1,
            "conflicting-draft-edit",
        )
        rig.workflow.save_draft(unsaved)
        conflict = rig.refresh()
        failed = next(item for item in conflict.changes if isinstance(item, DraftSaveProblem))
        assert failed.change == unsaved and "changed" in failed.reason
        late = publish_package(rig, prepared.request, title="A later generated package")
        refreshed = rig.refresh()
        packages = opened(refreshed).packages
        assert isinstance(packages, AvailablePackages) and len(packages.values) == 2
        original = next(item for item in packages.values if item.publication.version == published.version)
        newer = next(item for item in packages.values if item.publication.version == late.version)
        assert original.drafts == (competing,) and original.actions[0].content == action_content
        assert original.actions[0].revision == 1 and newer.drafts[0].revision == 0
        assert next(item for item in refreshed.changes if isinstance(item, DraftSaveProblem)).change == unsaved
        assert rig.followups.read(prepared.request.task_id, published.version).followup.drafts[0].body != content.body
    finally:
        rig.close()


def test_missing_package_files_keep_previous_artifacts_and_a_failed_edit_for_recovery(tmp_path: Path) -> None:
    rig = WorkflowRig(tmp_path)
    try:
        prepared = prepare_meeting(rig)
        published = publish_package(rig, prepared.request)
        previous = opened(rig.refresh()).packages
        assert isinstance(previous, AvailablePackages)
        retained = published.directory.with_name(".temporarily-unavailable")
        published.directory.rename(retained)
        try:
            change = DraftChange(
                prepared.request.task_id,
                published.version,
                "followup",
                DraftContent("My subject", "My unsaved body.", ()),
                0,
                "missing-draft-edit",
            )
            rig.workflow.save_draft(change)
            unavailable = rig.refresh()
            package = opened(unavailable).packages
            assert isinstance(package, PackagesUnavailable) and package.previous == previous.values
            assert isinstance(unavailable.changes[-1], DraftSaveProblem) and unavailable.changes[-1].change == change
        finally:
            retained.rename(published.directory)
        recovered = rig.refresh()
        assert opened(recovered).packages == previous
        assert isinstance(recovered.changes[-1], DraftSaveProblem) and recovered.changes[-1].change == change
    finally:
        rig.close()


def test_repeated_failed_saves_publish_distinct_attempts_and_keep_queued_outcomes_for_each_artifact(tmp_path: Path) -> None:
    work = WorkRig(tmp_path / "work")
    hold = ObservationHold(work.agent.snapshot)
    rig = WorkflowRig(tmp_path, work=work, read_work=hold)
    try:
        prepared = prepare_meeting(rig)
        published = publish_package(rig, prepared.request)
        rig.refresh()
        first_draft = DraftChange(
            prepared.request.task_id,
            published.version,
            "followup",
            DraftContent("My subject", "Keep this draft intact.", ()),
            0,
            "draft-first",
        )
        first_action = ActionChange(
            prepared.request.task_id,
            published.version,
            "ship",
            ActionContent("Ship the release.", Unspecified.NOT_STATED, Unspecified.NOT_STATED, ActionStatus.OPEN),
            0,
            "action-first",
        )
        retained = published.directory.with_name(".persistent-save-failure")
        published.directory.rename(retained)
        try:
            rig.workflow.save_draft(first_draft)
            rig.workflow.save_action(first_action)
            initial = rig.refresh()
            draft_failure = next(item for item in initial.changes if isinstance(item, DraftSaveProblem))
            action_failure = next(item for item in initial.changes if isinstance(item, ActionSaveProblem))
            assert draft_failure.change == first_draft and action_failure.change == first_action
            second_draft, third_draft = replace(first_draft, attempt_id="draft-second"), replace(first_draft, attempt_id="draft-third")
            second_action, third_action = replace(first_action, attempt_id="action-second"), replace(first_action, attempt_id="action-third")
            assert draft_failure.change != second_draft and action_failure.change != second_action

            # Hold the public observation seam so all retries enter the queue
            # before its next batch. No receipt may stand in for another attempt.
            hold.armed.set()
            rig.workflow.refresh()
            assert hold.entered.wait(5)
            published_count = len(rig.snapshots)
            rig.workflow.save_draft(second_draft)
            rig.workflow.save_draft(third_draft)
            rig.workflow.save_action(second_action)
            rig.workflow.save_action(third_action)
            completed = rig.workflow.refresh()
            assert rig.workflow.snapshot().changes == initial.changes
            hold.release.set()
            assert completed.wait(10)
            expected: tuple[DraftChange | ActionChange, ...] = (
                first_draft,
                first_action,
                second_draft,
                third_draft,
                second_action,
                third_action,
            )
            current = rig.workflow.snapshot()
            assert tuple(item.change for item in current.changes) == expected
            assert all(isinstance(item, (DraftSaveProblem, ActionSaveProblem)) for item in current.changes)
            assert {item.reason for item in current.changes if isinstance(item, DraftSaveProblem)} == {draft_failure.reason}
            assert {item.reason for item in current.changes if isinstance(item, ActionSaveProblem)} == {action_failure.reason}
            retry_ids = {item.attempt_id for item in expected[2:]}
            updates = tuple(
                snapshot for snapshot in rig.snapshots[published_count:] if any(item.change.attempt_id in retry_ids for item in snapshot.changes)
            )
            assert updates and all(tuple(item.change for item in snapshot.changes) == expected for snapshot in updates)
        finally:
            hold.release.set()
            retained.rename(published.directory)
    finally:
        hold.release.set()
        rig.close()


def test_save_attempt_identity_is_required_for_drafts_and_actions() -> None:
    with TestCase().assertRaisesRegex(ValueError, "draft save attempt identity"):
        DraftChange("task", "a" * 64, "draft", DraftContent("Subject", "Body", ()), 0, "")
    with TestCase().assertRaisesRegex(ValueError, "action save attempt identity"):
        ActionChange(
            "task",
            "a" * 64,
            "action",
            ActionContent("Finish it.", Unspecified.NOT_STATED, Unspecified.NOT_STATED, ActionStatus.OPEN),
            0,
            "",
        )


def test_work_observation_failure_retains_the_last_matching_task(tmp_path: Path) -> None:
    work = WorkRig(tmp_path / "work")
    unavailable = threading.Event()

    def read() -> WorkSnapshot:
        if unavailable.is_set():
            raise OSError("The current work observation is unavailable.")
        return work.agent.snapshot()

    rig = WorkflowRig(tmp_path, work=work, read_work=read)
    try:
        prepare_meeting(rig)
        observed = rig.refresh().preparations[0].work
        assert isinstance(observed, ObservedWork)
        unavailable.set()
        lost = rig.refresh().preparations[0].work
        assert isinstance(lost, WorkUnavailable) and lost.previous == observed.task
        assert len(rig.work.tasks.list_tasks()) == 1
        unavailable.clear()
        assert isinstance(rig.settle().preparations[0].work, ObservedWork)
    finally:
        unavailable.clear()
        rig.close()


def test_ui_commands_remain_nonblocking_and_shutdown_drains_the_bounded_accepted_queue(tmp_path: Path) -> None:
    work = WorkRig(tmp_path / "work")
    entered, release, held = threading.Event(), threading.Event(), threading.Event()

    def read() -> WorkSnapshot:
        if not held.is_set():
            held.set()
            entered.set()
            assert release.wait(10)
        return work.agent.snapshot()

    rig = WorkflowRig(tmp_path, work=work, read_work=read, start=False)
    try:
        meeting = saved_meeting(rig.archive, "Queued while the observer is busy")
        selected = (observe_transcript(meeting).source,)
        rig.workflow.start()
        assert entered.wait(5)
        for _ in range(64):
            rig.workflow.prepare(selected)
        with TestCase().assertRaisesRegex(ValueError, "queue is full"):
            rig.workflow.prepare(selected)
        assert rig.workflow.snapshot().preparations == ()
        rig.workflow.close()
        assert not rig.workflow.wait_closed(0)
        with TestCase().assertRaisesRegex(ValueError, "closing"):
            rig.workflow.prepare(selected)
        release.set()
        assert rig.workflow.wait_closed(10)
        work.refresh()
        assert len(tuple(rig.preparations.root.glob("*.json"))) == 1 and len(work.tasks.list_tasks()) == 1
    finally:
        release.set()
        rig.close()
