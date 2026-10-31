"""Evidence-bound meeting follow-through values and the model's follow-up claims.

This module performs no file or network operations. `FollowupClaims` is the one
wire shape of a proposed follow-up: its adapter generates the offered tool schema,
validates the model's payload and stores the canonical package data. A quote
resolves against an observed transcript's exact text; generation never supplies
its own evidence offsets. Publication and editable draft revisions belong to
meeting_followup_store.
"""

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path, PureWindowsPath
from typing import Annotated, Literal, assert_never

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError

from automation.task import digest, identifier, integer, text, timestamp, variant

RECIPE_VERSION = 1
MAX_TRANSCRIPT_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 2 * 1024 * 1024
MAX_SOURCES = 8
MAX_MODEL_BYTES = 512 * 1024
MAX_CITATIONS = 8
MAX_QUOTE = 4000
MAX_QUOTE_OCCURRENCES = 1024
MAX_STATEMENTS = 64
MAX_ACTIONS = 100
MAX_DRAFTS = 24
MAX_RECIPIENTS = 30
MAX_BODY = 32_000
_EMAIL_TOKEN = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?")


def _text(value: object, field: str, maximum: int, *, empty: bool = False) -> str:
    result = text(value, field, maximum=maximum, empty=empty)
    if any(ord(char) < 32 and char not in "\t\n\r" for char in result):
        raise ValueError(f"Invalid control character in {field}.")
    result.encode("utf-8")
    return result


def _header(value: object, field: str, maximum: int, *, empty: bool = False) -> str:
    result = _text(value, field, maximum, empty=empty)
    if any(char in result for char in "\r\n\t"):
        raise ValueError(f"{field} must occupy one line.")
    return result


def _literal(value: str, quote: str) -> bool:
    before = r"(?<!\w)" if value[0].isalnum() or value[0] == "_" else ""
    after = r"(?!\w)" if value[-1].isalnum() or value[-1] == "_" else ""
    return re.search(before + re.escape(value) + after, quote) is not None


def _email_literal(value: str, quote: str) -> bool:
    return any(value == match.group().strip("'\"`") for match in _EMAIL_TOKEN.finditer(quote))


# A record's collections must be tuples; validation refuses lists and other iterables.
_ITEMS = TypeAdapter(tuple[object, ...])


def _tuple(value: object, kind: type[object], field: str, maximum: int, *, empty: bool = True) -> None:
    try:
        items = _ITEMS.validate_python(value, strict=True)
    except ValidationError:
        raise ValueError(f"Invalid {field}.") from None
    if len(items) > maximum or (not empty and not items) or any(not isinstance(item, kind) for item in items):
        raise ValueError(f"Invalid {field}.")


class NoCaptureNotice(Enum):
    NONE = auto()


@dataclass(frozen=True, slots=True)
class CaptureNotice:
    text: str

    def __post_init__(self) -> None:
        _text(self.text, "capture notice", 4000)


@dataclass(frozen=True, slots=True)
class TranscriptSource:
    id: str
    title: str
    path: str
    sha256: str
    started_at: float
    duration_seconds: float
    capture: Literal["both", "microphone"]
    notice: CaptureNotice | NoCaptureNotice

    def __post_init__(self) -> None:
        identifier(self.id, "transcript identity")
        _header(self.title, "transcript title", 240)
        _text(self.path, "transcript path", 4096)
        if not (Path(self.path).is_absolute() or PureWindowsPath(self.path).is_absolute()):
            raise ValueError("A transcript source path must be absolute.")
        digest(self.sha256, "transcript digest")
        observed_at = timestamp(self.started_at, "recording start")
        if observed_at > 253_402_300_799:
            raise ValueError("Recording timestamps must be before year 10000.")
        object.__setattr__(self, "started_at", observed_at)
        object.__setattr__(self, "duration_seconds", timestamp(self.duration_seconds, "recording duration"))
        if self.capture not in ("both", "microphone"):
            raise ValueError("Invalid transcript capture observation.")
        variant(self.notice, (CaptureNotice, NoCaptureNotice), "capture notice")


@dataclass(frozen=True, slots=True)
class Transcript:
    source: TranscriptSource
    content: bytes
    text: str = field(init=False)

    def __post_init__(self) -> None:
        variant(self.source, TranscriptSource, "transcript source")
        variant(self.content, bytes, "transcript bytes")
        if not self.content or len(self.content) > MAX_TRANSCRIPT_BYTES:
            raise ValueError("The transcript exceeds its supported size or is empty.")
        observed = _text(self.content.decode("utf-8"), "transcript text", MAX_TRANSCRIPT_BYTES)
        object.__setattr__(self, "text", observed)
        if hashlib.sha256(self.content).hexdigest() != self.source.sha256:
            raise ValueError("The transcript bytes do not match their source digest.")


_SELECTION = TypeAdapter(tuple[tuple[str, str], ...])


@dataclass(frozen=True, slots=True)
class TranscriptBundle:
    transcripts: tuple[Transcript, ...]

    def __post_init__(self) -> None:
        _tuple(self.transcripts, Transcript, "selected transcripts", MAX_SOURCES, empty=False)
        identities = tuple(item.source.id for item in self.transcripts)
        if len(set(identities)) != len(identities):
            raise ValueError("A selected transcript identity occurs more than once.")
        if sum(len(item.content) for item in self.transcripts) > MAX_BUNDLE_BYTES:
            raise ValueError("The selected transcripts exceed their combined size limit.")

    @property
    def fingerprint(self) -> str:
        # Selection order is intentional: successive recordings retain their order.
        selected = tuple((item.source.id, item.source.sha256) for item in self.transcripts)
        return hashlib.sha256(_SELECTION.dump_json(selected)).hexdigest()


@dataclass(frozen=True, slots=True)
class Citation:
    source_id: str
    source_sha256: str
    start: int
    end: int
    line: int
    quote: str

    def __post_init__(self) -> None:
        identifier(self.source_id, "citation source")
        digest(self.source_sha256, "citation source digest")
        integer(self.start, "citation start", maximum=MAX_TRANSCRIPT_BYTES)
        integer(self.end, "citation end", minimum=self.start + 1, maximum=MAX_TRANSCRIPT_BYTES)
        integer(self.line, "citation line", minimum=1, maximum=MAX_TRANSCRIPT_BYTES)
        _text(self.quote, "source quote", MAX_QUOTE)
        if self.end - self.start != len(self.quote):
            raise ValueError("Citation offsets must span the quoted text.")


def resolve_citation(bundle: TranscriptBundle, source_id: str, quote: str, *, occurrence: int | None = None) -> Citation:
    """Resolve a literal source quote; repeated text needs an explicit occurrence."""
    identifier(source_id, "citation source")
    _text(quote, "source quote", MAX_QUOTE)
    if occurrence is not None:
        integer(occurrence, "quote occurrence", maximum=MAX_QUOTE_OCCURRENCES - 1)
    transcript = next((item for item in bundle.transcripts if item.source.id == source_id), None)
    if transcript is None:
        raise ValueError("A citation refers to a transcript outside the selected sources.")
    content = transcript.text
    start = content.find(quote)
    if start < 0:
        raise ValueError("A citation quote does not occur in its observed transcript.")
    if occurrence is None:
        if content.find(quote, start + 1) >= 0:
            raise ValueError("An ambiguous source quote requires its zero-based occurrence.")
    else:
        for _ in range(occurrence):
            start = content.find(quote, start + 1)
            if start < 0:
                raise ValueError("The requested quote occurrence does not exist.")
    return Citation(source_id, transcript.source.sha256, start, start + len(quote), content.count("\n", 0, start) + 1, quote)


def _citations(value: object, *, empty: bool = False) -> None:
    _tuple(value, Citation, "source citations", MAX_CITATIONS, empty=empty)


@dataclass(frozen=True, slots=True)
class CitedText:
    text: str
    citations: tuple[Citation, ...]

    def __post_init__(self) -> None:
        _text(self.text, "meeting statement", 4000)
        _citations(self.citations)


class Unspecified(Enum):
    NOT_STATED = "not_stated"


@dataclass(frozen=True, slots=True)
class NamedOwner:
    name: str
    evidence: Citation

    def __post_init__(self) -> None:
        _header(self.name, "action owner", 240)
        variant(self.evidence, Citation, "owner evidence")
        if not _literal(self.name, self.evidence.quote):
            raise ValueError("A named owner must occur literally in its source evidence.")


@dataclass(frozen=True, slots=True)
class StatedDue:
    text: str
    evidence: Citation

    def __post_init__(self) -> None:
        _header(self.text, "action due text", 240)
        variant(self.evidence, Citation, "due-date evidence")
        if not _literal(self.text, self.evidence.quote):
            raise ValueError("A due date must preserve the literal source wording.")


type Owner = NamedOwner | Unspecified
type Due = StatedDue | Unspecified


@dataclass(frozen=True, slots=True)
class ActionItem:
    id: str
    text: str
    citations: tuple[Citation, ...]
    owner: Owner
    due: Due

    def __post_init__(self) -> None:
        identifier(self.id, "action identity")
        _text(self.text, "action text", 4000)
        _citations(self.citations)
        variant(self.owner, (NamedOwner, Unspecified), "action owner")
        variant(self.due, (StatedDue, Unspecified), "action due date")
        if isinstance(self.owner, NamedOwner) and self.owner.evidence not in self.citations:
            raise ValueError("An owner must cite evidence attached to that action.")
        if isinstance(self.due, StatedDue) and self.due.evidence not in self.citations:
            raise ValueError("A due date must cite evidence attached to that action.")

    @property
    def content(self) -> ActionContent:
        owner = AssignedOwner(self.owner.name) if isinstance(self.owner, NamedOwner) else Unspecified.NOT_STATED
        due = AssignedDue(self.due.text) if isinstance(self.due, StatedDue) else Unspecified.NOT_STATED
        return ActionContent(self.text, owner, due, ActionStatus.OPEN)


class ActionStatus(Enum):
    OPEN = "open"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class AssignedOwner:
    name: str

    def __post_init__(self) -> None:
        _header(self.name, "assigned owner", 240)


@dataclass(frozen=True, slots=True)
class AssignedDue:
    text: str

    def __post_init__(self) -> None:
        _header(self.text, "assigned due text", 240)


@dataclass(frozen=True, slots=True)
class ActionContent:
    text: str
    owner: AssignedOwner | Unspecified
    due: AssignedDue | Unspecified
    status: ActionStatus

    def __post_init__(self) -> None:
        _text(self.text, "edited action text", 4000)
        variant(self.owner, (AssignedOwner, Unspecified), "assigned owner")
        variant(self.due, (AssignedDue, Unspecified), "assigned due date")
        variant(self.status, ActionStatus, "action completion state")


@dataclass(frozen=True, slots=True)
class EmailAddress:
    value: str

    def __post_init__(self) -> None:
        _header(self.value, "email address", 320)
        if re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", self.value) is None:
            raise ValueError("The email address is incomplete or unsupported.")
        local, domain = self.value.split("@")
        if local.startswith(".") or local.endswith(".") or ".." in local or ".." in domain or len(local) > 64:
            raise ValueError("The email address is invalid.")


@dataclass(frozen=True, slots=True)
class Addressee:
    name: str
    email: EmailAddress | Unspecified

    def __post_init__(self) -> None:
        _header(self.name, "recipient name", 240)
        variant(self.email, (EmailAddress, Unspecified), "recipient email")


@dataclass(frozen=True, slots=True)
class SourceRecipient:
    addressee: Addressee
    citations: tuple[Citation, ...]

    def __post_init__(self) -> None:
        variant(self.addressee, Addressee, "generated recipient")
        _citations(self.citations)
        if not any(_literal(self.addressee.name, citation.quote) for citation in self.citations):
            raise ValueError("A generated recipient name must occur in its source evidence.")
        email = self.addressee.email
        if isinstance(email, EmailAddress) and not any(_email_literal(email.value, citation.quote) for citation in self.citations):
            raise ValueError("A generated email address must occur literally in its source evidence.")


@dataclass(frozen=True, slots=True)
class DraftContent:
    subject: str
    body: str
    recipients: tuple[Addressee, ...]

    def __post_init__(self) -> None:
        _header(self.subject, "draft subject", 500)
        _text(self.body, "draft body", MAX_BODY)
        _tuple(self.recipients, Addressee, "draft recipients", MAX_RECIPIENTS)


@dataclass(frozen=True, slots=True)
class EmailDraft:
    id: str
    subject: str
    body: str
    recipients: tuple[SourceRecipient, ...]
    citations: tuple[Citation, ...]
    action_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        identifier(self.id, "draft identity")
        _header(self.subject, "draft subject", 500)
        _text(self.body, "draft body", MAX_BODY)
        _tuple(self.recipients, SourceRecipient, "source recipients", MAX_RECIPIENTS)
        _citations(self.citations)
        _tuple(self.action_ids, str, "draft action references", MAX_ACTIONS)
        if len(set(self.action_ids)) != len(self.action_ids):
            raise ValueError("A draft repeats an action reference.")
        if any(citation not in self.citations for recipient in self.recipients for citation in recipient.citations):
            raise ValueError("Generated recipients must cite evidence attached to that draft.")

    @property
    def content(self) -> DraftContent:
        return DraftContent(self.subject, self.body, tuple(item.addressee for item in self.recipients))


@dataclass(frozen=True, slots=True)
class Followup:
    sources: TranscriptBundle
    title: str
    notes: tuple[CitedText, ...]
    decisions: tuple[CitedText, ...]
    actions: tuple[ActionItem, ...]
    drafts: tuple[EmailDraft, ...]

    def __post_init__(self) -> None:
        variant(self.sources, TranscriptBundle, "follow-through sources")
        _header(self.title, "follow-through title", 240)
        _tuple(self.notes, CitedText, "meeting notes", MAX_STATEMENTS, empty=False)
        _tuple(self.decisions, CitedText, "meeting decisions", MAX_STATEMENTS)
        _tuple(self.actions, ActionItem, "meeting actions", MAX_ACTIONS)
        _tuple(self.drafts, EmailDraft, "follow-up drafts", MAX_DRAFTS)
        actions = {item.id for item in self.actions}
        if len(actions) != len(self.actions) or len({item.id for item in self.drafts}) != len(self.drafts):
            raise ValueError("Action and draft identities must be unique within their collection.")
        citations: list[Citation] = []
        for statement in (*self.notes, *self.decisions):
            citations.extend(statement.citations)
        for action in self.actions:
            citations.extend(action.citations)
            if isinstance(action.owner, NamedOwner):
                citations.append(action.owner.evidence)
            if isinstance(action.due, StatedDue):
                citations.append(action.due.evidence)
        for draft in self.drafts:
            if not set(draft.action_ids) <= actions:
                raise ValueError("A draft refers to an action outside this follow-through package.")
            citations.extend(draft.citations)
            for recipient in draft.recipients:
                citations.extend(recipient.citations)
        sources = {item.source.id: item for item in self.sources.transcripts}
        for citation in citations:
            transcript = sources.get(citation.source_id)
            if transcript is None or transcript.source.sha256 != citation.source_sha256:
                raise ValueError("A citation is bound to a different transcript observation.")
            content = transcript.text
            if content[citation.start : citation.end] != citation.quote or content.count("\n", 0, citation.start) + 1 != citation.line:
                raise ValueError("A citation does not resolve against the observed source text.")


def _absent(value: object) -> bool:
    return value is None


# The model's payload is strict JSON; unknown fields are refused, not ignored.
_CLAIMS = ConfigDict(extra="forbid", strict=True)


@dataclass(frozen=True, slots=True)
class QuoteClaim:
    """A literal quote the model cites; only the observed transcript supplies its offsets."""

    source_id: str
    quote: Annotated[str, Field(min_length=1, max_length=MAX_QUOTE)]
    occurrence: Annotated[
        Annotated[int, Field(ge=0, lt=MAX_QUOTE_OCCURRENCES)] | None,
        Field(description="Zero-based occurrence, needed only when the exact quote repeats.", exclude_if=_absent),
    ] = None
    __pydantic_config__ = _CLAIMS


type Evidence = Annotated[tuple[QuoteClaim, ...], Field(min_length=1, max_length=MAX_CITATIONS)]


@dataclass(frozen=True, slots=True)
class StatementClaim:
    text: str
    citations: Evidence
    __pydantic_config__ = _CLAIMS


@dataclass(frozen=True, slots=True)
class UnstatedClaim:
    kind: Literal["unspecified"]
    __pydantic_config__ = _CLAIMS


@dataclass(frozen=True, slots=True)
class OwnerClaim:
    kind: Literal["named"]
    name: str
    evidence: QuoteClaim
    __pydantic_config__ = _CLAIMS


@dataclass(frozen=True, slots=True)
class DueClaim:
    kind: Literal["stated"]
    text: str
    evidence: QuoteClaim
    __pydantic_config__ = _CLAIMS


@dataclass(frozen=True, slots=True)
class ActionClaim:
    id: str
    text: str
    citations: Evidence
    owner: Annotated[UnstatedClaim | OwnerClaim, Field(discriminator="kind")]
    due: Annotated[UnstatedClaim | DueClaim, Field(discriminator="kind")]
    __pydantic_config__ = _CLAIMS


@dataclass(frozen=True, slots=True)
class RecipientClaim:
    name: str
    email: str | None
    citations: Evidence
    __pydantic_config__ = _CLAIMS


@dataclass(frozen=True, slots=True)
class DraftClaim:
    id: str
    subject: str
    body: str
    recipients: Annotated[tuple[RecipientClaim, ...], Field(max_length=MAX_RECIPIENTS)]
    citations: Evidence
    action_ids: Annotated[tuple[str, ...], Field(max_length=MAX_ACTIONS)]
    __pydantic_config__ = _CLAIMS


@dataclass(frozen=True, slots=True)
class FollowupClaims:
    """What the model proposes; resolution against the frozen transcripts makes it a Followup."""

    source_digest: str
    title: str
    notes: Annotated[tuple[StatementClaim, ...], Field(min_length=1, max_length=MAX_STATEMENTS)]
    decisions: Annotated[tuple[StatementClaim, ...], Field(max_length=MAX_STATEMENTS)]
    actions: Annotated[tuple[ActionClaim, ...], Field(max_length=MAX_ACTIONS)]
    drafts: Annotated[tuple[DraftClaim, ...], Field(max_length=MAX_DRAFTS)]
    __pydantic_config__ = _CLAIMS


FOLLOWUP_CLAIMS = TypeAdapter(FollowupClaims)
DRAFT_CONTENT = TypeAdapter(DraftContent)
ACTION_CONTENT = TypeAdapter(ActionContent)


def _cite(bundle: TranscriptBundle, claim: QuoteClaim) -> Citation:
    return resolve_citation(bundle, claim.source_id, claim.quote, occurrence=claim.occurrence)


def _evidence(bundle: TranscriptBundle, claims: Iterable[QuoteClaim]) -> tuple[Citation, ...]:
    return tuple(_cite(bundle, claim) for claim in claims)


def _statement(bundle: TranscriptBundle, claim: StatementClaim) -> CitedText:
    return CitedText(claim.text, _evidence(bundle, claim.citations))


def _action(bundle: TranscriptBundle, claim: ActionClaim) -> ActionItem:
    owner: Owner
    match claim.owner:
        case OwnerClaim(name=name, evidence=evidence):
            owner = NamedOwner(name, _cite(bundle, evidence))
        case UnstatedClaim():
            owner = Unspecified.NOT_STATED
        case _:
            assert_never(claim.owner)
    due: Due
    match claim.due:
        case DueClaim(text=wording, evidence=evidence):
            due = StatedDue(wording, _cite(bundle, evidence))
        case UnstatedClaim():
            due = Unspecified.NOT_STATED
        case _:
            assert_never(claim.due)
    return ActionItem(claim.id, claim.text, _evidence(bundle, claim.citations), owner, due)


def _recipient(bundle: TranscriptBundle, claim: RecipientClaim) -> SourceRecipient:
    email = Unspecified.NOT_STATED if claim.email is None else EmailAddress(claim.email)
    return SourceRecipient(Addressee(claim.name, email), _evidence(bundle, claim.citations))


def _draft(bundle: TranscriptBundle, claim: DraftClaim) -> EmailDraft:
    recipients = tuple(_recipient(bundle, item) for item in claim.recipients)
    return EmailDraft(claim.id, claim.subject, claim.body, recipients, _evidence(bundle, claim.citations), claim.action_ids)


def resolve_followup(bundle: TranscriptBundle, claims: FollowupClaims) -> Followup:
    """Bind every claim to the observed transcripts without silently repairing claims or evidence."""
    if claims.source_digest != bundle.fingerprint:
        raise ValueError("The follow-through response belongs to a different source selection.")
    return Followup(
        bundle,
        claims.title,
        tuple(_statement(bundle, item) for item in claims.notes),
        tuple(_statement(bundle, item) for item in claims.decisions),
        tuple(_action(bundle, item) for item in claims.actions),
        tuple(_draft(bundle, item) for item in claims.drafts),
    )


def _quote(bundle: TranscriptBundle, citation: Citation) -> QuoteClaim:
    content = next(item.text for item in bundle.transcripts if item.source.id == citation.source_id)
    start = content.find(citation.quote)
    if content.find(citation.quote, start + 1) < 0:
        return QuoteClaim(citation.source_id, citation.quote)
    occurrence = 0
    while start != citation.start:
        if occurrence >= MAX_QUOTE_OCCURRENCES - 1:
            raise ValueError("A highly repeated citation needs a longer source quote.")
        start = content.find(citation.quote, start + 1)
        if start < 0:
            raise ValueError("A citation does not resolve against its source.")
        occurrence += 1
    return QuoteClaim(citation.source_id, citation.quote, occurrence)


def followup_claims(followup: Followup) -> FollowupClaims:
    """The canonical claims that resolve to exactly this follow-up; source bytes are stored separately."""
    bundle = followup.sources

    def evidence(citations: Iterable[Citation]) -> tuple[QuoteClaim, ...]:
        return tuple(_quote(bundle, item) for item in citations)

    def statement(item: CitedText) -> StatementClaim:
        return StatementClaim(item.text, evidence(item.citations))

    def action(item: ActionItem) -> ActionClaim:
        owner: UnstatedClaim | OwnerClaim
        match item.owner:
            case NamedOwner(name=name, evidence=citation):
                owner = OwnerClaim("named", name, _quote(bundle, citation))
            case Unspecified.NOT_STATED:
                owner = UnstatedClaim("unspecified")
            case _:
                assert_never(item.owner)
        due: UnstatedClaim | DueClaim
        match item.due:
            case StatedDue(text=wording, evidence=citation):
                due = DueClaim("stated", wording, _quote(bundle, citation))
            case Unspecified.NOT_STATED:
                due = UnstatedClaim("unspecified")
            case _:
                assert_never(item.due)
        return ActionClaim(item.id, item.text, evidence(item.citations), owner, due)

    def recipient(item: SourceRecipient) -> RecipientClaim:
        match item.addressee.email:
            case EmailAddress(value=email):
                address: str | None = email
            case Unspecified.NOT_STATED:
                address = None
            case _:
                assert_never(item.addressee.email)
        return RecipientClaim(item.addressee.name, address, evidence(item.citations))

    def draft(item: EmailDraft) -> DraftClaim:
        return DraftClaim(
            item.id, item.subject, item.body, tuple(recipient(value) for value in item.recipients), evidence(item.citations), item.action_ids
        )

    return FollowupClaims(
        bundle.fingerprint,
        followup.title,
        tuple(statement(item) for item in followup.notes),
        tuple(statement(item) for item in followup.decisions),
        tuple(action(item) for item in followup.actions),
        tuple(draft(item) for item in followup.drafts),
    )
