"""Prepared meeting execution and exact artifact/mail recovery, outside the UI."""

import threading
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, assert_never

from pydantic import Field, TypeAdapter

from assistant import outlook
from assistant.meeting_followup import (
    CaptureNotice,
    DraftContent,
    EmailAddress,
    FollowupClaims,
    NoCaptureNotice,
    Transcript,
    followup_claims,
    resolve_followup,
)
from assistant.meeting_followup_store import FollowupStore, Publication, PublishedFollowup
from assistant.meeting_preparation import Preparations, PreparedFollowup
from automation.actions import ActionError
from automation.execution import WorkExecution
from automation.task import (
    Action,
    ActionUncertain,
    ActionVerified,
    Blocked,
    Completed,
    FileDigest,
    MailTarget,
    MeetingFollowup,
    NoVerification,
    Outcome,
    Waiting,
    digest,
    identifier,
    integer,
)

SOURCE_PAGE = 32_000


def _absent(value: object) -> bool:
    return value is None


@dataclass(frozen=True, slots=True)
class SourceSummary:
    source_id: str
    title: str
    sha256: str
    started_at: float
    duration_seconds: float
    capture_notice: str | None
    characters: int


@dataclass(frozen=True, slots=True)
class SourceListing:
    source_digest: str
    sources: tuple[SourceSummary, ...]


@dataclass(frozen=True, slots=True)
class SourcePage:
    """One bounded page of a selected transcript; `next_offset` continues it."""

    source_digest: str
    source_id: str
    sha256: str
    offset: int
    text: str
    next_offset: int | None


@dataclass(frozen=True, slots=True)
class DraftView:
    draft_id: str
    revision: int
    content: DraftContent
    email_file: str
    markdown_file: str


@dataclass(frozen=True, slots=True)
class PackageView:
    """A verified package as the meeting worker inspects it: its claims, files and current draft revisions."""

    version: str
    source_digest: str
    notes_path: str
    actions_path: str
    followup: FollowupClaims
    drafts: tuple[DraftView, ...]
    verified: Literal[True] = True


@dataclass(frozen=True, slots=True)
class VersionSummary:
    version: str
    title: str
    source_digest: str


@dataclass(frozen=True, slots=True)
class VersionListing:
    versions: tuple[VersionSummary, ...]
    source_digest: str


@dataclass(frozen=True, slots=True)
class SavedMail:
    version: str
    draft_id: str
    revision: int
    destination: Literal["outlook", "email_file"]
    message: str
    path: Annotated[str | None, Field(exclude_if=_absent)] = None
    saved: Literal[True] = True


@dataclass(frozen=True, slots=True)
class UnsavedMail:
    version: str
    draft_id: str
    revision: int
    problem: str
    saved: Literal[False] = False


type MeetingResult = SourceListing | SourcePage | PackageView | VersionListing | SavedMail | UnsavedMail
_RESULT = TypeAdapter(MeetingResult)


def encoded(result: MeetingResult) -> str:
    """The tool output the meeting worker reads; each result's record is its shape."""
    return _RESULT.dump_json(result).decode()


def _summary(transcript: Transcript) -> SourceSummary:
    source = transcript.source
    match source.notice:
        case CaptureNotice(text=notice):
            capture_notice: str | None = notice
        case NoCaptureNotice.NONE:
            capture_notice = None
        case _:
            assert_never(source.notice)
    return SourceSummary(source.id, source.title, source.sha256, source.started_at, source.duration_seconds, capture_notice, len(transcript.text))


class Drafts(Protocol):
    def save(self, request: outlook.DraftRequest, cancel: threading.Event) -> outlook.DraftResult: ...
    def inspect(self, request: outlook.DraftRequest, cancel: threading.Event) -> outlook.DraftResult | outlook.Missing: ...


def verified_mail(request: outlook.DraftRequest, result: outlook.DraftResult | outlook.Missing) -> ActionVerified | ActionUncertain:
    match result:
        case outlook.SavedOutlookDraft() | outlook.SavedEmlDraft():
            if result.key != outlook.draft_key(request) or result.fingerprint != outlook.fingerprint(request):
                return ActionUncertain("The saved mail result belongs to a different draft or content revision.")
            destination = "Outlook draft" if isinstance(result, outlook.SavedOutlookDraft) else "complete email draft file"
            return ActionVerified(f"The {destination} was read back with the exact subject, body and recipients; no message was sent.")
        case outlook.DraftConflict(reason) | outlook.DraftUncertain(reason):
            return ActionUncertain(reason)
        case outlook.Cancelled.BEFORE_EFFECT:
            return ActionVerified("The draft adapter stopped before saving a message.")
        case outlook.Missing.DRAFT:
            return ActionUncertain("The draft has no saved delivery binding to inspect.")
        case _:
            assert_never(result)


class MeetingWork:
    __slots__ = ("drafts", "packages", "preparations")

    def __init__(self, preparations: Preparations, packages: FollowupStore, drafts: Drafts) -> None:
        self.preparations, self.packages, self.drafts = preparations, packages, drafts

    def session(self, task_id: str, profile: MeetingFollowup) -> MeetingRun:
        """The run sees exactly the recordings its profile names; a missing or changed bundle raises."""
        return MeetingRun(self.preparations.read(task_id, profile), self.packages, self.drafts)


class MeetingRun:
    __slots__ = ("drafts", "mail_results", "packages", "request", "selected")

    def __init__(self, request: PreparedFollowup, packages: FollowupStore, drafts: Drafts) -> None:
        self.request, self.packages, self.drafts = request, packages, drafts
        self.selected: PublishedFollowup | None = None
        self.mail_results: dict[MailTarget, outlook.DraftResult] = {}

    def sources(self, source_id: str = "", offset: int = 0) -> SourceListing | SourcePage:
        integer(offset, "transcript offset", maximum=2 * 1024 * 1024)
        bundle = self.request.bundle
        if not source_id:
            if offset:
                raise ValueError("Choose a source before requesting a text offset.")
            return SourceListing(bundle.fingerprint, tuple(_summary(transcript) for transcript in bundle.transcripts))
        source_id = identifier(source_id, "selected recording identity")
        selected = next((value for value in bundle.transcripts if value.source.id == source_id), None)
        if selected is None:
            raise ValueError("That recording is outside this task's selected sources.")
        if offset > len(selected.text):
            raise ValueError("The requested text offset is outside the selected recording.")
        end = min(len(selected.text), offset + SOURCE_PAGE)
        following = end if end < len(selected.text) else None
        return SourcePage(bundle.fingerprint, source_id, selected.source.sha256, offset, selected.text[offset:end], following)

    def publication(self, claims: FollowupClaims) -> Publication:
        # Validation precedes action registration and any artifact writes.
        return self.packages.plan(self.request.task_id, resolve_followup(self.request.bundle, claims))

    def publish(self, publication: Publication) -> PackageView:
        if publication.task_id != self.request.task_id or publication.followup.sources != self.request.bundle:
            raise ValueError("The prepared artifacts belong to different meeting work.")
        self.selected = self.packages.publish(publication)
        return self._package(self.selected)

    def _read(self, version: str) -> PublishedFollowup:
        package = self.packages.read(self.request.task_id, digest(version, "package version"))
        if package.followup.sources != self.request.bundle:
            raise ValueError("The saved package belongs to different recording snapshots.")
        return package

    def _package(self, package: PublishedFollowup) -> PackageView:
        drafts = tuple(
            DraftView(value.id, value.revision, value.content, str(value.files.eml), str(value.files.markdown))
            for value in self.packages.drafts(package.task_id, package.version)
        )
        return PackageView(
            package.version,
            package.followup.sources.fingerprint,
            str(package.notes_path),
            str(package.actions_path),
            followup_claims(package.followup),
            drafts,
        )

    def result(self, version: str = "") -> VersionListing | PackageView:
        if not version:
            versions = tuple(
                VersionSummary(package.version, package.followup.title, package.followup.sources.fingerprint)
                for package in self.packages.versions(self.request.task_id)
            )
            return VersionListing(versions, self.request.bundle.fingerprint)
        self.selected = self._read(version)
        return self._package(self.selected)

    def _draft(self, version: str, draft_id: str, revision: int) -> outlook.DraftRequest:
        self._read(version)
        content = self.packages.draft_revision(self.request.task_id, version, draft_id, revision).content
        recipients = tuple(outlook.Recipient(value.email.value) for value in content.recipients if isinstance(value.email, EmailAddress))
        return outlook.DraftRequest(self.request.task_id, draft_id, outlook.DraftContent(content.subject, content.body, to=recipients))

    def prepare_mail(self, version: str, draft_id: str, revision: int) -> tuple[MailTarget, outlook.DraftRequest]:
        version, draft_id = digest(version, "package version"), identifier(draft_id, "draft identity")
        revision = integer(revision, "draft revision")
        current = next((value for value in self.packages.drafts(self.request.task_id, version) if value.id == draft_id), None)
        if current is None or current.revision != revision:
            raise ValueError("The draft changed after it was selected. Inspect its current revision before saving to mail.")
        request = self._draft(version, draft_id, revision)
        return MailTarget(version, draft_id, revision, outlook.fingerprint(request)), request

    def save_mail(self, target: MailTarget, request: outlook.DraftRequest, stop: threading.Event) -> outlook.DraftResult:
        if outlook.fingerprint(request) != target.fingerprint or request.workflow_id != self.request.task_id or request.draft_id != target.draft_id:
            raise ValueError("The mail save does not match its exact selected draft.")
        result = self.drafts.save(request, stop)
        self.mail_results[target] = result
        return result

    def mail_result(self, target: MailTarget, result: outlook.DraftResult) -> SavedMail | UnsavedMail:
        version, draft_id, revision = target.version, target.draft_id, target.revision
        match result:
            case outlook.SavedOutlookDraft():
                return SavedMail(version, draft_id, revision, "outlook", "Saved an unsent Outlook draft and verified its complete contents.")
            case outlook.SavedEmlDraft(path=path, unavailable=unavailable):
                return SavedMail(version, draft_id, revision, "email_file", unavailable.reason, str(path))
            case outlook.DraftConflict(reason) | outlook.DraftUncertain(reason):
                return UnsavedMail(version, draft_id, revision, reason)
            case outlook.Cancelled.BEFORE_EFFECT:
                return UnsavedMail(version, draft_id, revision, "Stopped before the mail draft was saved.")
            case _:
                assert_never(result)

    def recover(self, work: WorkExecution, stop: threading.Event) -> None:
        """An uncertain native Save can only be resolved by its exact readback."""
        with work.actions.resources.hold(("outlook",), stop):
            for action in work.store.unverified_actions(self.request.task_id):
                self._recover_mail(work, action, stop)

    def _recover_mail(self, work: WorkExecution, action: Action, stop: threading.Event) -> None:
        target = action.specification.verification
        match target:
            case NoVerification() | FileDigest():
                return
            case MailTarget():
                pass
            case _:
                assert_never(target)
        request = self._draft(target.version, target.draft_id, target.revision)
        if outlook.fingerprint(request) != target.fingerprint:
            raise ActionError("The recorded mail attempt does not match the saved draft revision.")
        result = self.drafts.inspect(request, stop)
        observed = verified_mail(request, result)
        if not isinstance(observed, ActionVerified) or result is outlook.Cancelled.BEFORE_EFFECT:
            reason = observed.reason if isinstance(observed, ActionUncertain) else "Mail inspection was stopped."
            raise ActionError(reason)
        if work.store.finish_action(action.id, observed, at=work.clock()) is None:
            raise ActionError("The draft was verified, but its action acknowledgement could not be saved.")
        if result is not outlook.Missing.DRAFT:
            self.mail_results[target] = result

    def _deliveries(
        self,
        package: PublishedFollowup,
    ) -> dict[str, tuple[MailTarget, outlook.SavedOutlookDraft | outlook.SavedEmlDraft]]:
        delivered: dict[str, tuple[MailTarget, outlook.SavedOutlookDraft | outlook.SavedEmlDraft]] = {}
        for target, result in self.mail_results.items():
            if target.version != package.version or not isinstance(result, (outlook.SavedOutlookDraft, outlook.SavedEmlDraft)):
                continue
            request = self._draft(target.version, target.draft_id, target.revision)
            if target.fingerprint != outlook.fingerprint(request) or not isinstance(verified_mail(request, result), ActionVerified):
                raise ValueError("The saved mail receipt does not match its selected draft revision.")
            previous = delivered.get(target.draft_id)
            if previous is None or target.revision > previous[0].revision:
                delivered[target.draft_id] = target, result
        missing = tuple(draft.id for draft in package.followup.drafts if draft.id not in delivered)
        if missing:
            raise ValueError("These meeting drafts have no verified saved mail destination: " + ", ".join(missing) + ". Resume to save them.")
        return delivered

    def completed(self, outcome: Outcome) -> Outcome:
        if not isinstance(outcome, Completed):
            return outcome
        if self.selected is None:
            return Waiting(Blocked("A meeting result must be published and inspected before this task is complete. Resume to finish it."))
        try:
            package = self._read(self.selected.version)
            delivered = self._deliveries(package)
            local_drafts = self.packages.drafts(package.task_id, package.version)
        except (OSError, ValueError) as error:
            return Waiting(Blocked(f"The saved meeting artifacts could not be verified: {error}"[:4000]))
        result = (
            f"Prepared {package.followup.title} from {len(package.followup.sources.transcripts)} recording(s).\n\n"
            f"Notes: {package.notes_path}\nActions ({len(package.followup.actions)}): {package.actions_path}\n"
        )
        for draft in local_drafts:
            target, saved = delivered[draft.id]
            destination = str(saved.path) if isinstance(saved, outlook.SavedEmlDraft) else "unsent Outlook draft"
            result += f"\nSaved mail draft {draft.id} (revision {target.revision}): {destination}\nLocal draft: {draft.files.eml}"
            if draft.revision > target.revision:
                result += f"\nA newer local edit (revision {draft.revision}) is retained and was not copied to the saved mail draft."
        native = sum(isinstance(value[1], outlook.SavedOutlookDraft) for value in delivered.values())
        if native:
            result += f"\nVerified unsent Outlook drafts: {native}."
        result += "\nNo follow-up messages were sent."
        evidence = (
            *outcome.evidence,
            f"Verified meeting package SHA-256 {package.version}.",
            f"Selected recording bundle SHA-256 {self.request.bundle.fingerprint}.",
        )
        return Completed(result, evidence[-64:])
