"""Workspace association, correction, review and tool ownership through real IO."""

import threading
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from unittest import TestCase

from assistant.browser_values import BrowserError
from assistant.feed_agent_tools import request
from assistant.feed_triage_service import Triage
from assistant.llm import Json, Settings
from assistant.personal_work_model import Correlator
from assistant.personal_work_service import PersonalWork, correlation_input
from assistant.personal_work_sources import BrowserSources, Tab, outlook_sources
from assistant.web_apps import (
    Board,
    BoardQuery,
    Card,
    Located,
    Mailbox,
    MailList,
    MailMessage,
    MailRow,
    SelectedMail,
    TeamsChat,
    TeamsPage,
    TeamsPost,
    TeamsQuery,
)
from assistant.work_canvas_model import caption
from automation.actions import Resources
from automation.execution import WorkExecution
from automation.personal_work import (
    PERSONAL_RESPONSE,
    WORK_PLAN,
    AddDocument,
    AddWebPage,
    Association,
    CorrelationInput,
    DismissWork,
    DocumentAdded,
    ListSources,
    ListWork,
    PersonalStore,
    PlannedWork,
    RestoreWork,
    SaveWork,
    SourceKind,
    SourcePage,
    UnlinkWork,
    WorkDefinition,
    WorkPage,
    WorkPlan,
    WorkRefused,
    WorkSaved,
    WorkState,
    WorkThread,
)
from automation.task import ActionNotApplied, ActionVerified
from automation.work_documents import LocalDocument, WebDocument
from tests.fake_endpoint import Reply, fake_endpoint
from tests.feed_fixture import open_bridge
from tests.personal_work_fixture import WIRE, CapturedBrowser, CapturedSources, source
from tests.test_feed_triage_service import MemoryStore
from tests.test_work_actions import claimed
lazy from tests.test_agent import ToolRig, message


def test_dismissal_is_durable_blocks_reclassification_and_can_be_restored(tmp_path: Path) -> None:
    # Defect: dismissed work reappears under a new model-generated identity, or
    # dismissal destroys its sources and cannot restore the user's context.
    store = PersonalStore(tmp_path / "work.sqlite3")
    evidence = source(SourceKind.KANBAN)
    store.observe((evidence,))
    saved = store.handle(SaveWork(WorkDefinition("Someone else's work", "Investigate Atlas"), (Association(evidence.id, "Tracks Atlas"),)), 20)
    assert isinstance(saved, WorkSaved)
    with TestCase().assertRaises(ValueError):
        store.handle(DismissWork(saved.work.id, saved.work.revision + 1, "Not mine"), 21)
    store.handle(DismissWork(saved.work.id, saved.work.revision, "Not my responsibility"), 22)
    reopened = PersonalStore(store.path)
    state = reopened.read()
    assert not state.works and state.dismissed[0].reason == "Not my responsibility"
    with TestCase().assertRaises(ValueError):
        reopened.handle(SaveWork(saved.work.definition, saved.work.links), 23)
    plan = WorkPlan((PlannedWork(None, WorkDefinition("Reworded", "A rephrased goal"), saved.work.links),))
    assert not reopened.reconcile(correlation_input(state), plan, 23).works
    restored = reopened.handle(RestoreWork(saved.work.id), 24)
    assert isinstance(restored, WorkSaved) and restored.work.id == saved.work.id and restored.work.links == saved.work.links
    assert not reopened.read().dismissed


def test_researched_web_reference_retains_original_url_and_captured_evidence(tmp_path: Path) -> None:
    # Defect: a researched page is mislabeled as a file, loses its URL/evidence,
    # or registering it duplicates its work context rather than connecting it.
    from_url = "https://example.test/architecture"
    store = PersonalStore(tmp_path / "work.sqlite3")
    saved = store.handle(SaveWork(WorkDefinition("Atlas", "Choose architecture")), 10)
    assert isinstance(saved, WorkSaved)
    page = store.handle(AddWebPage("Architecture guidance", WebDocument(from_url), "Verified guidance: compare schema versions.", saved.work.id), 11)
    assert isinstance(page, DocumentAdded) and page.source.kind is SourceKind.WEB_PAGE
    observed = PersonalStore(store.path).read()
    assert observed.sources[0].url == from_url and observed.sources[0].excerpt == "Verified guidance: compare schema versions."
    assert observed.works[0].id == saved.work.id and observed.works[0].links[0].source_id == page.source.id
    assert caption(page.source) == "Web reference"


def test_dismissal_cancels_research_only_after_the_correction_commits(tmp_path: Path) -> None:
    # Defect: a stale dismissal stops valid research, or cancellation runs
    # before the durable correction exists and the work gets recreated.
    store = PersonalStore(tmp_path / "work.sqlite3")
    saved = store.handle(SaveWork(WorkDefinition("Atlas", "Check ownership")), 10)
    assert isinstance(saved, WorkSaved)
    observations: list[tuple[str, bool]] = []

    def cancel_research(work: WorkThread) -> None:
        observations.append((work.id, any(item.work.id == work.id for item in PersonalStore(store.path).read().dismissed)))

    service = PersonalWork(store, CapturedSources(), lambda _view: None, clock=lambda: 11, dismissed=cancel_research)
    try:
        stale = service.handle(DismissWork(saved.work.id, saved.work.revision + 1, "Not mine"))
        assert isinstance(stale, WorkRefused) and not observations
        service.handle(DismissWork(saved.work.id, saved.work.revision, "Not mine"))
        assert observations == [(saved.work.id, True)]
    finally:
        service.close()


def test_automatic_connections_survive_restart_and_support_multiple_outcomes(tmp_path: Path) -> None:
    # Defect: reviews only publish transient groupings, duplicate work after
    # restart, or incorrectly require one source to belong to only one outcome.
    store = PersonalStore(tmp_path / "work.sqlite3")
    mail, chat, ticket = tuple(source(kind) for kind in (SourceKind.TEAMS, SourceKind.OUTLOOK, SourceKind.KANBAN))
    state = store.observe((mail, chat, ticket))
    links = tuple(Association(item.id, "The Atlas supplier review gates this migration.") for item in state.sources)
    plan = WorkPlan((PlannedWork(None, WorkDefinition("Atlas", "Deploy Atlas"), links),))
    connected = store.reconcile(correlation_input(state), plan, 20)
    first = connected.works[0]
    reopened = PersonalStore(store.path)
    connected = reopened.reconcile(correlation_input(reopened.read()), plan, 21)
    assert connected.works == (first,)
    second = reopened.handle(SaveWork(WorkDefinition("Supplier", "Approve the supplier"), (links[0],)), 22)
    assert isinstance(second, WorkSaved)
    page = reopened.handle(ListWork(query="atlas", limit=1), 23)
    assert isinstance(page, WorkPage)
    assert page.works == (first,) and {item.id for item in page.sources} == {mail.id, chat.id, ticket.id}
    assert len(reopened.read().works) == 2


def test_corrections_and_personal_completion_survive_later_automatic_reviews(tmp_path: Path) -> None:
    # Defect: the next review silently restores a removed connection, overwrites
    # the user's goal/state, or drops older links omitted from a partial review.
    store = PersonalStore(tmp_path / "work.sqlite3")
    mail, chat = source(SourceKind.OUTLOOK), source(SourceKind.TEAMS)
    state = store.observe((mail, chat))
    first = store.handle(
        SaveWork(
            WorkDefinition("My Atlas", "My outcome", state=WorkState.DONE, project="My project"),
            (Association(mail.id, "Supplier decision"), Association(chat.id, "Deployment decision")),
        ),
        20,
    )
    assert isinstance(first, WorkSaved)
    unlinked = store.handle(UnlinkWork(first.work.id, mail.id, first.work.revision), 21)
    assert isinstance(unlinked, WorkSaved)
    reopened = PersonalStore(store.path)
    plan = WorkPlan(
        (
            PlannedWork(
                first.work.id,
                WorkDefinition("Renamed", "Another goal", "Supplier still pending", "Ask for a date"),
                (Association(mail.id, "Restored by model"),),
            ),
        )
    )
    state = reopened.reconcile(correlation_input(reopened.read()), plan, 22)
    updated = state.works[0]
    assert updated.links == (Association(chat.id, "Deployment decision"),)
    assert updated.definition == replace(first.work.definition, summary="Supplier still pending", next_step="Ask for a date")
    assert state.rejected[0].source_id == mail.id
    restored = reopened.handle(
        SaveWork(updated.definition, (*updated.links, Association(mail.id, "Explicit correction")), updated.id, updated.revision), 23
    )
    assert isinstance(restored, WorkSaved) and len(restored.work.links) == 2
    assert not reopened.read().rejected


def test_concurrent_edit_or_new_evidence_rejects_the_entire_model_plan(tmp_path: Path) -> None:
    # Defect: a delayed model response overwrites edits/evidence from another
    # connection, or a malformed later entry commits an earlier partial result.
    store = PersonalStore(tmp_path / "work.sqlite3")
    evidence = source(SourceKind.TEAMS)
    store.observe((evidence,))
    first = store.handle(SaveWork(WorkDefinition("Atlas", "Deploy Atlas")), 20)
    assert isinstance(first, WorkSaved)
    captured = correlation_input(store.read())
    peer = PersonalStore(store.path)
    edit = peer.handle(SaveWork(replace(first.work.definition, goal="Deploy after approval"), (), first.work.id, first.work.revision), 21)
    assert isinstance(edit, WorkSaved)
    plan = WorkPlan((PlannedWork(first.work.id, WorkDefinition("Atlas", "Deploy immediately"), (Association(evidence.id, "Deploy"),)),))
    with TestCase().assertRaisesRegex(ValueError, "changed"):
        store.reconcile(captured, plan, 22)
    assert store.read() == peer.read()
    captured = correlation_input(store.read())
    peer.observe((replace(evidence, excerpt="Approval declined", revision="new-evidence", observed_at=23),))
    with TestCase().assertRaisesRegex(ValueError, "changed"):
        store.reconcile(captured, plan, 24)
    before = store.read()
    bad = WorkPlan((*plan.works, PlannedWork(None, WorkDefinition("Invalid", "Unknown source"), (Association("unobserved", "Invented"),))))
    with TestCase().assertRaisesRegex(ValueError, "outside its review"):
        store.reconcile(correlation_input(before), bad, 25)
    assert store.read() == before


def test_model_cannot_reference_stored_sources_outside_its_bounded_review(tmp_path: Path) -> None:
    # Defect: validation checks only the database and accepts identities the
    # model was never given, making its explanation unsupported.
    store = PersonalStore(tmp_path / "work.sqlite3")
    store.observe(tuple(source(SourceKind.KANBAN, str(index), float(index)) for index in range(65)))
    captured = correlation_input(store.read())
    assert len(captured.sources) == 60
    omitted = source(SourceKind.KANBAN, "0", 0)
    before = store.read()
    plan = WorkPlan((PlannedWork(None, WorkDefinition("Atlas", "Deploy Atlas"), (Association(omitted.id, "Not in the review"),)),))
    with TestCase().assertRaisesRegex(ValueError, "outside its review"):
        store.reconcile(captured, plan, 100)
    assert store.read() == before


def test_missing_and_older_observations_preserve_linked_evidence(tmp_path: Path) -> None:
    # Defect: virtualization is treated as deletion, source retention evicts
    # linked evidence, or a late observation replaces newer content.
    store = PersonalStore(tmp_path / "work.sqlite3")
    old = source(SourceKind.KANBAN, "linked", 1)
    store.observe((old,))
    saved = store.handle(SaveWork(WorkDefinition("Atlas", "Deploy Atlas"), (Association(old.id, "Deployment ticket"),)), 2)
    assert isinstance(saved, WorkSaved)
    newer = replace(old, excerpt="Deployment approved", revision="approved", observed_at=20)
    store.observe((newer,))
    store.observe((old,))
    store.observe(tuple(source(SourceKind.KANBAN, str(index), float(30 + index)) for index in range(1000)))
    state = store.observe(())
    assert len(state.sources) == 1000
    assert newer in state.sources and state.works == (saved.work,)


def test_background_reviews_skip_timestamp_only_changes_and_retry_failures(tmp_path: Path) -> None:
    # Defect: each poll buys another review of identical content, a forced
    # refresh is ignored, or a failed review permanently suppresses retry.
    store = PersonalStore(tmp_path / "work.sqlite3")
    sources = CapturedSources((source(SourceKind.KANBAN),))
    reviewed: list[CorrelationInput] = []

    def model(captured: CorrelationInput, cancel: threading.Event) -> WorkPlan:
        reviewed.append(captured)
        if len(reviewed) == 3:
            raise ValueError("Provider unavailable")
        work_id = captured.works[0].id if captured.works else None
        return WorkPlan((PlannedWork(work_id, WorkDefinition("Atlas", "Deploy Atlas"), (Association(captured.sources[0].id, "Deployment ticket"),)),))

    service = PersonalWork(store, sources, lambda _: None, model=model)
    try:
        service.tick()
        first = store.read().works[0]
        assert service.snapshot().catalog.works == (first,)
        service.tick()
        assert len(reviewed) == 1
        service.refresh()
        service.tick()
        assert sources.refreshed == 1 and len(reviewed) == 2
        sources.sources = (replace(sources.sources[0], excerpt="New approval", revision="new"),)
        service.tick()
        assert store.read().works == (first,) and "could not" in service.snapshot().status
        service.tick()
        assert len(reviewed) == 4 and "updated automatically" in service.snapshot().status
    finally:
        service.close()
    assert sources.closed == 1


def test_user_correction_during_review_is_not_undone(tmp_path: Path) -> None:
    # Defect: the worker uses its pre-model catalog to publish/commit over a
    # correction made while the model's network call is in progress.
    store = PersonalStore(tmp_path / "work.sqlite3")
    evidence = source(SourceKind.OUTLOOK)
    store.observe((evidence,))
    saved = store.handle(SaveWork(WorkDefinition("Atlas", "Deploy Atlas"), (Association(evidence.id, "Approval"),)), 10)
    assert isinstance(saved, WorkSaved)

    def model(captured: CorrelationInput, cancel: threading.Event) -> WorkPlan:
        corrected = store.handle(UnlinkWork(saved.work.id, evidence.id, saved.work.revision), 11)
        assert isinstance(corrected, WorkSaved)
        return WorkPlan((PlannedWork(saved.work.id, saved.work.definition, saved.work.links),))

    service = PersonalWork(store, CapturedSources((evidence,)), lambda _: None, model=model)
    try:
        service.tick()
        assert not service.snapshot().catalog.works[0].links
        assert service.snapshot().catalog.rejected[0].source_id == evidence.id
    finally:
        service.close()


def board(*cards: Card, following: int | None = None) -> Board:
    return Board(cards, len(cards), ("Ready", "Testing"), (), "", "Currently rendered board with its existing filters", following)


def mailbox(*rows: MailRow, selected: SelectedMail | None = None, following: int | None = None) -> Mailbox:
    return Mailbox(rows, len(rows), selected, "", "Current folder and tab", following, editor_open=False)


def test_browser_collection_routes_exact_tabs_paginates_and_uses_messages_not_titles() -> None:
    # Defect: the observer reads an unrelated tab, stops at the first Kanban
    # page, or promotes title-only Teams sidebar entries into work evidence.
    selected, sidebar = "19:selected@thread.v2", "19:sidebar@thread.v2"
    browser = CapturedBrowser(
        (
            Tab("board", source(SourceKind.KANBAN).url),
            Tab("chat", source(SourceKind.TEAMS).url),
            Tab("mail", source(SourceKind.OUTLOOK).url),
            Tab("other", "https://example.test/"),
        ),
        {
            BoardQuery("board", offset=0, limit=30): board(Card("one", "Atlas", "Ready", "Supplier review"), following=30),
            BoardQuery("board", offset=30, limit=30): board(Card("two", "Atlas", "Testing", "Deploy")),
            TeamsQuery("chat"): TeamsPage(
                selected,
                "Atlas",
                (TeamsChat(sidebar, "Atlas", "chat"),),
                (TeamsPost("message", "Colleague", "Awaiting supplier approval", 0, (), own=False),),
                editor_ready=True,
            ),
            MailList("mail", offset=0, limit=20): mailbox(MailRow("one", "Supplier review", "", selected=False), following=20),
            MailList("mail", offset=20, limit=20): mailbox(MailRow("two", "Deploy Atlas", "", selected=False)),
        },
    )
    reader = BrowserSources(browser)
    observations = reader.read(20, threading.Event())
    assert observations.coverage == ("kanban", "outlook", "teams") and not observations.problems
    assert len(observations.sources) == 6
    teams = tuple(item for item in observations.sources if item.kind is SourceKind.TEAMS)
    assert len(teams) == 2
    conversation = next(item for item in teams if item.parent_id is None)
    piece = next(item for item in teams if item.parent_id is not None)
    assert conversation.identity == selected and "supplier approval" in conversation.excerpt
    assert piece.parent_id == conversation.id and piece.excerpt == "Awaiting supplier approval"
    assert caption(piece) == "Teams message"
    assert BoardQuery("board", offset=30, limit=30) in browser.queries and MailList("mail", offset=20, limit=20) in browser.queries
    assert all(query.target_id != "other" for query in browser.queries)
    reader.close()
    assert browser.closed == 1


def test_selected_outlook_body_is_evidence_even_without_a_rendered_list_row() -> None:
    # Defect: selected mail disappears from collection when paginating or
    # when Outlook virtualizes its list row out of the current view.
    selected = SelectedMail("selected", "Atlas approval", (), "The supplier approved deployment.", "", truncated=False, loading=False)
    tab = Tab("mail", source(SourceKind.OUTLOOK).url)
    observations = outlook_sources(mailbox(selected=selected), tab, 20)
    assert len(observations) == 1 and observations[0].identity == selected.conversation_id
    assert observations[0].excerpt == selected.text and observations[0].title == selected.subject


def test_unavailable_browser_waits_for_refresh_and_empty_chats_are_not_evidence() -> None:
    # Defect: failed attachment repeatedly interrupts the user, or sidebar
    # titles alone create responsibilities despite no observed message body.
    browser = CapturedBrowser(BrowserError("Unavailable"), {})
    reader = BrowserSources(browser)
    first = reader.read(10, threading.Event())
    assert not first.sources and first.problems
    reader.read(11, threading.Event())
    assert browser.tab_reads == 1
    chat = "19:one@thread.v2"
    browser.tabs = (Tab("chat", source(SourceKind.TEAMS).url),)
    available: Mapping[Located, object] = {
        TeamsQuery("chat"): TeamsPage(chat, "Deploy Atlas", (TeamsChat(chat, "Deploy Atlas", "chat"),), (), editor_ready=True)
    }
    browser.answers = available
    reader.refresh()
    fresh = reader.read(12, threading.Event())
    assert not fresh.sources and not fresh.problems and fresh.coverage == ("teams",)
    reader.close()


def test_agent_tools_use_the_live_bridge_and_record_confirmed_edits(tmp_path: Path) -> None:
    # Defect: registered tools only return text without editing the saved
    # catalog, lose typed requests at HTTP, or journal a refusal as success.
    tasks, claim, clock = claimed(tmp_path)
    store = PersonalStore(tasks.path)
    evidence = source(SourceKind.TEAMS)
    store.observe((evidence,))
    service = PersonalWork(store, CapturedSources(), lambda _: None)
    endpoint = tmp_path / "feed-bridge.json"
    triage = Triage(
        endpoint, MemoryStore(), lambda _: None, lambda _batch, _rules: "{}", lambda _: False, server_factory=open_bridge, personal=service
    )
    rig = ToolRig(work=WorkExecution(claim, tasks, Resources(), clock=clock), feed_request=lambda data: request(data, endpoint))
    try:
        sources = rig.call("work_items_sources")
        assert sources.ok and evidence.id in sources.text
        assert not tasks.actions(claim.task.id)
        saved = rig.call(
            "work_items_save",
            definition={"title": "Atlas", "goal": "Deploy Atlas"},
            links=[{"source_id": evidence.id, "reason": "The selected chat requests deployment."}],
        )
        result = PERSONAL_RESPONSE.validate_json(saved.text)
        assert saved.ok and isinstance(result, WorkSaved)
        assert isinstance(tasks.actions(claim.task.id)[0].outcome, ActionVerified)
        listing = rig.call("work_items_list")
        assert listing.ok and result.work.id in listing.text
        correction = rig.call("work_items_unlink", work_id=result.work.id, source_id=evidence.id, expected_revision=result.work.revision)
        assert isinstance(PERSONAL_RESPONSE.validate_json(correction.text), WorkSaved)
        stale = rig.call("work_items_save", definition={"title": "Stale", "goal": "Stale"}, work_id=result.work.id, expected_revision=0)
        assert isinstance(PERSONAL_RESPONSE.validate_json(stale.text), WorkRefused)
        assert isinstance(tasks.actions(claim.task.id)[-1].outcome, ActionNotApplied)
        assert not store.read().works[0].links and store.read().rejected
        assert not rig.machine.log
        document = rig.call(
            "work_items_add_document",
            title="Design",
            reference={"kind": "web", "url": "https://contoso.example.test/design.docx"},
            work_id=result.work.id,
        )
        registered = PERSONAL_RESPONSE.validate_json(document.text)
        assert document.ok and isinstance(registered, DocumentAdded)
        assert isinstance(tasks.actions(claim.task.id)[-1].outcome, ActionVerified)
        current = store.read().works[0]
        dismissed = rig.call("work_items_dismiss", work_id=current.id, expected_revision=current.revision, reason="Not my responsibility")
        assert isinstance(PERSONAL_RESPONSE.validate_json(dismissed.text), WorkSaved)
        assert not store.read().works and store.read().dismissed[0].work.id == current.id
        restored = rig.call("work_items_restore", work_id=current.id)
        assert isinstance(PERSONAL_RESPONSE.validate_json(restored.text), WorkSaved)
        assert store.read().works[0].links == current.links and not store.read().dismissed
        assert isinstance(tasks.actions(claim.task.id)[-1].outcome, ActionVerified)
        assert any(link.source_id == registered.source.id for link in store.read().works[0].links)
        page = rig.call(
            "work_items_add_web_page",
            title="Architecture guidance",
            reference={"kind": "web", "url": "https://contoso.example.test/guidance"},
            excerpt="Verified evidence: compare schema versions.",
            work_id=result.work.id,
        )
        captured = PERSONAL_RESPONSE.validate_json(page.text)
        assert page.ok and isinstance(captured, DocumentAdded)
        assert captured.source.kind is SourceKind.WEB_PAGE and captured.source.url == "https://contoso.example.test/guidance"
        assert captured.source.excerpt == "Verified evidence: compare schema versions."
        assert any(link.source_id == captured.source.id for link in store.read().works[0].links)
        assert isinstance(tasks.actions(claim.task.id)[-1].outcome, ActionVerified)
    finally:
        triage.close()
        service.close()


def test_correlation_model_receives_bounded_evidence_and_has_no_action_tools(tmp_path: Path) -> None:
    # Defect: the connector uses the quick chat model, omits saved work or
    # corrections, or grants the background correlation model action tools.
    store = PersonalStore(tmp_path / "work.sqlite3")
    state = store.observe((source(SourceKind.TEAMS),))
    existing = store.handle(
        SaveWork(WorkDefinition("Atlas", "Deploy only after supplier approval"), (Association(state.sources[0].id, "Supplier review"),)), 20
    )
    assert isinstance(existing, WorkSaved)
    store.handle(UnlinkWork(existing.work.id, state.sources[0].id, existing.work.revision), 21)
    captured = correlation_input(store.read())
    plan = WorkPlan((PlannedWork(None, WorkDefinition("Atlas", "Deploy Atlas"), (Association(state.sources[0].id, "Deployment request"),)),))
    with fake_endpoint() as endpoint:
        output: dict[str, Json] = {
            "id": "resp_work",
            "object": "response",
            "created_at": 1,
            "model": "work-model",
            "status": "completed",
            "output": [message(WIRE.dump_json({"response": WIRE.validate_json(WORK_PLAN.dump_json(plan))}).decode())],
            "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
        }
        endpoint.replies = [Reply(WIRE.dump_json(output))]
        model = Correlator(Settings(endpoint.url, "key", "transcribe", "quick-model", "work-model", "", "", agent_reasoning_effort="low"))
        assert model(captured, threading.Event()) == plan
        wire = WIRE.validate_json(endpoint.last.body)
        assert wire["model"] == "work-model" and wire["store"] is False and not wire.get("tools")
        assert state.sources[0].id in str(wire["input"])
        assert existing.work.id in str(wire["input"]) and "Deploy only after supplier approval" in str(wire["input"])
        assert "rejected" in str(wire["input"])
        assert "untrusted evidence" in str(wire)
        assert "WorkPlan" in str(wire["text"])


def test_document_registration_is_durable_and_does_not_modify_the_file(tmp_path: Path) -> None:
    # Defect: adding a document only creates a transient card, duplicates it on
    # re-registration, edits its file, or partially commits an invalid work link.
    file = tmp_path / "Runbook.md"
    file.write_text("Original runbook", encoding="utf-8")
    store = PersonalStore(tmp_path / "work.sqlite3")
    work = store.handle(SaveWork(WorkDefinition("Migration", "Deploy safely")), 1)
    assert isinstance(work, WorkSaved)
    added = store.handle(AddDocument(file.name, LocalDocument(str(file)), "Approved steps", work.work.id), 2)
    assert isinstance(added, DocumentAdded)
    reopened = PersonalStore(store.path)
    state = reopened.read()
    assert state.sources == (added.source,) and state.works[0].links[0].source_id == added.source.id
    assert file.read_text(encoding="utf-8") == "Original runbook"
    again = reopened.handle(AddDocument("Runbook", LocalDocument(str(file)), "Revised observation"), 3)
    assert isinstance(again, DocumentAdded) and again.source.id == added.source.id
    assert len(reopened.read().sources) == 1
    before = reopened.read()
    with TestCase().assertRaisesRegex(ValueError, "no longer exists"):
        reopened.handle(AddDocument("Missing context", WebDocument("https://contoso.example.test/design.docx"), work_id="work:missing"), 4)
    assert reopened.read() == before
    for invalid in ("javascript:alert(1)", "https://user:password@example.test/document"):
        with TestCase().assertRaises(ValueError):
            WebDocument(invalid)


def test_individual_mail_preserves_the_conversation_reference(tmp_path: Path) -> None:
    # Defect: splitting observed mail replaces the conversation association or
    # assigns one identity to different messages and loses individual evidence.
    selected = SelectedMail(
        "conversation",
        "Supplier approval",
        (
            MailMessage("first", "Anna", "Can we migrate on Friday?"),
            MailMessage("second", "Jim", "Friday is approved."),
        ),
        "Latest reply",
        "",
        truncated=False,
        loading=False,
    )
    sources = outlook_sources(mailbox(selected=selected), Tab("mail", source(SourceKind.OUTLOOK).url), 1)
    conversation, first, second = sources
    assert first.parent_id == second.parent_id == conversation.id and first.id != second.id
    store = PersonalStore(tmp_path / "work.sqlite3")
    store.observe(sources)
    pieces = store.handle(ListSources(query=conversation.id), 1)
    assert isinstance(pieces, SourcePage) and frozenset(item.id for item in pieces.sources) == frozenset(item.id for item in sources)
    another = outlook_sources(mailbox(selected=replace(selected, conversation_id="another")), Tab("mail", source(SourceKind.OUTLOOK).url), 1)
    assert first.id != another[1].id and first.identity == another[1].identity
    captured = correlation_input(store.read())
    assert conversation in captured.sources and first in captured.sources
    saved = store.handle(
        SaveWork(WorkDefinition("Migration", "Deploy safely"), (Association(conversation.id, "The discussion agrees the window"),)), 2
    )
    assert isinstance(saved, WorkSaved)
    refreshed = store.observe((replace(second, excerpt="Friday at 18:00 is approved.", observed_at=3),))
    assert refreshed.works[0].links == saved.work.links
    assert frozenset(item.id for item in refreshed.sources) == frozenset(item.id for item in sources)
