"""Registered integration tools, private previews and exact resource ownership."""

import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast

from pydantic import TypeAdapter

from assistant.business_tools import WEB_TOOLS, AppTool, Collection, Edit, Read, Selection
from assistant.web_apps import (
    KANBAN_BOARD,
    KANBAN_COMMENT,
    KANBAN_MOVE_TASK,
    KANBAN_READ_TASK,
    KANBAN_UPDATE_TASK,
    OUTLOOK_DOCUMENTS,
    OUTLOOK_DOWNLOAD_DOCUMENT,
    OUTLOOK_DRAFT_REPLY,
    OUTLOOK_OPEN_DOCUMENT,
    OUTLOOK_OPEN_MAIL,
    OUTLOOK_READ,
    OUTLOOK_SEARCH,
    TEAMS_DRAFT_REPLY,
    TEAMS_OPEN_CHAT,
    TEAMS_READ,
    Board,
    ChatDrafted,
    ChatOpened,
    CollectedDocument,
    CommentPosted,
    Located,
    Mailbox,
    MailDocuments,
    MailDrafted,
    MailOpened,
    PreviewOpened,
    TaskDetail,
    TaskEdited,
    TaskMoved,
    TeamsPage,
    WebAppOperation,
)
from automation.actions import Change, Observation, Resources, target
from automation.execution import ApprovalReview, WorkExecution
from automation.json_value import Json
from automation.task import ActionUncertain, ActionVerified
from tests.test_agent import FakeMachine, ToolRig, durable
from tests.test_work_actions import claimed

_WIRE = TypeAdapter(dict[str, Json])

# Each change's receipt confirms arguments(name) exactly.
RECEIPTS: Mapping[object, object] = {
    KANBAN_BOARD: Board((), 0, (), (), "", "Currently rendered board", None),
    KANBAN_READ_TASK: TaskDetail("task-1", frozendict(), ""),
    KANBAN_UPDATE_TASK: TaskEdited("task-1", "title", "private content", verified=True),
    KANBAN_MOVE_TASK: TaskMoved("task-1", "Done", verified=True, changed=True),
    KANBAN_COMMENT: CommentPosted("task-1", "private content", posted=True),
    TEAMS_READ: TeamsPage("", "", (), (), editor_ready=False),
    TEAMS_OPEN_CHAT: ChatOpened("chat-1", opened=True),
    TEAMS_DRAFT_REPLY: ChatDrafted("chat-1", "private content", drafted=True, sent=False),
    OUTLOOK_READ: Mailbox((), 0, None, "", "Current folder and tab", None, editor_open=False),
    OUTLOOK_SEARCH: Mailbox((), 0, None, "private content", "All folders", None, editor_open=False),
    OUTLOOK_OPEN_MAIL: MailOpened("mail-1", None, opened=True),
    OUTLOOK_DRAFT_REPLY: MailDrafted("mail-1", "private content", "Re: Atlas", (), "Prepared", drafted=True, sent=False),
    OUTLOOK_DOCUMENTS: MailDocuments("mail-1", (), (), "Rendered attachments", truncated=False),
    OUTLOOK_OPEN_DOCUMENT: PreviewOpened("mail-1", "attachment-1", None, "Atlas", "Opened", opened=True),
    OUTLOOK_DOWNLOAD_DOCUMENT: CollectedDocument("mail-1", "attachment-1", "C:\\workspace\\document.txt", "0" * 64, 1, "text/plain"),
}

# The result fields that bind a receipt to its requested effect.
BINDINGS: Mapping[str, tuple[str, ...]] = {
    "kanban_update_task": ("task_id", "field", "value"),
    "kanban_move_task": ("task_id", "column"),
    "kanban_comment": ("task_id", "text"),
    "teams_web_open_chat": ("chat_id",),
    "teams_web_draft_reply": ("chat_id", "text"),
    "outlook_web_open_mail": ("conversation_id",),
    "outlook_web_open_document": ("conversation_id", "attachment_id"),
    "outlook_web_draft_reply": ("conversation_id", "text"),
    "outlook_web_download_document": ("conversation_id", "attachment_id", "path"),
}


class AppMachine(FakeMachine):
    """Concrete app results supplied at composition, and the typed requests received."""

    __slots__ = ("receipts", "requests")

    def __init__(self, receipts: Mapping[object, object] = RECEIPTS) -> None:
        super().__init__()
        self.receipts: frozendict[object, object] = frozendict(receipts)
        self.requests: list[tuple[object, Located]] = []

    def web_app[Q: Located, R](self, operation: WebAppOperation[Q, R], query: Q, cancel: threading.Event) -> R:
        self.log.append("web_app " + query.target_id)
        self.requests.append((operation, query))
        return operation.result.validate_python(self.receipts[operation])


def declared(name: str) -> AppTool[Located, object]:
    return cast(AppTool[Located, object], next(item for item in WEB_TOOLS if item.spec.name == name))


def arguments(name: str) -> dict[str, Json]:
    match name:
        case "kanban_update_task":
            return {"target_id": "page-1", "task_id": "task-1", "field": "title", "expected_value": "Before", "value": "private content"}
        case "kanban_move_task":
            return {"target_id": "page-1", "task_id": "task-1", "expected_column": "Ready", "column": "Done"}
        case "kanban_comment":
            return {"target_id": "page-1", "task_id": "task-1", "text": "private content"}
        case "kanban_read_task":
            return {"target_id": "page-1", "task_id": "task-1"}
        case "teams_web_open_chat":
            return {"target_id": "page-1", "chat_id": "chat-1"}
        case "teams_web_draft_reply":
            return {"target_id": "page-1", "chat_id": "chat-1", "text": "private content"}
        case "outlook_web_draft_reply":
            return {"target_id": "page-1", "conversation_id": "mail-1", "text": "private content"}
        case "outlook_web_open_mail":
            return {"target_id": "page-1", "conversation_id": "mail-1"}
        case "outlook_web_documents":
            return {"target_id": "page-1", "conversation_id": "mail-1"}
        case "outlook_web_open_document":
            return {"target_id": "page-1", "conversation_id": "mail-1", "attachment_id": "attachment-1"}
        case "outlook_web_download_document":
            return {
                "target_id": "page-1",
                "conversation_id": "mail-1",
                "attachment_id": "attachment-1",
                "expected_url": "https://outlook.office.com/attachment",
                "destination": {"path": "C:\\workspace\\document.txt", "kind": "local"},
            }
        case "outlook_web_search":
            return {"target_id": "page-1", "query": "private content"}
        case _:
            return {"target_id": "page-1"}


def test_business_tools_dispatch_privately_and_stop_before_effects(tmp_path: Path) -> None:
    # Defect: registration sends an app request to the wrong operation or shows
    # private mail/card content despite integration redaction.
    machine = AppMachine()
    for tool in WEB_TOOLS:
        rig = ToolRig(work=durable(tmp_path), machine=machine)
        assert rig.call(tool.spec.name, **arguments(tool.spec.name)).ok
        operation, query = machine.requests[-1]
        assert operation is tool.effect.operation and query.target_id == "page-1"
        assert all("private content" not in str(item) for item in (*rig.window.log, *rig.window.live))
    before = tuple(machine.requests)
    rig = ToolRig(work=durable(tmp_path), machine=machine)
    rig.agent.stop.set()
    assert not rig.call("kanban_comment", **arguments("kanban_comment")).ok
    assert tuple(machine.requests) == before


def test_business_reads_and_mutations_have_exact_resource_markers(tmp_path: Path) -> None:
    # Defect: a read creates a pending effect, or evidence from another card,
    # conversation or mailbox could resolve an uncertain mutation.
    tools = ToolRig(work=durable(tmp_path)).agent.tools

    def resources(name: str, arguments: Mapping[str, Json]) -> tuple[str, ...]:
        return tools[name].classify(arguments).resources

    for name in ("kanban_board", "kanban_read_task", "teams_web_read", "outlook_web_search", "outlook_web_read", "outlook_web_documents"):
        assert isinstance(tools[name].classify({}), Observation)
    assert isinstance(tools["kanban_update_task"].classify({}), Change)
    assert "filesystem" in resources("outlook_web_download_document", {}) and "filesystem" not in resources("outlook_web_open_document", {})
    page = target("browser-page", "page-1")
    assert resources("kanban_update_task", arguments("kanban_update_task")) == ("browser", page, target("kanban-task", "task-1"))
    assert resources("kanban_read_task", {"target_id": "page-1", "task_id": "task-2"}) == ("browser", page, target("kanban-task", "task-2"))
    assert resources("teams_web_draft_reply", arguments("teams_web_draft_reply")) == ("browser", page, target("teams-chat", "chat-1"))
    assert resources("teams_web_read", {"target_id": "page-1"}) == ("browser", page)
    assert resources("outlook_web_open_mail", {"target_id": "page-1", "conversation_id": "mail-2"}) == (
        "browser",
        page,
        target("outlook-conversation", "mail-2"),
    )
    assert resources("outlook_web_download_document", arguments("outlook_web_download_document")) == (
        "browser",
        "filesystem",
        page,
        target("outlook-conversation", "mail-1"),
        target("outlook-attachment", "attachment-1"),
    )


def test_approval_mode_declines_business_writes_before_the_machine(tmp_path: Path) -> None:
    # Defect: expanded tools bypass the existing optional approval policy.
    rig = ToolRig(approvals=True, work=durable(tmp_path))
    for name in ("kanban_update_task", "kanban_move_task", "kanban_comment", "teams_web_draft_reply", "outlook_web_draft_reply"):
        assert not rig.call(name, **arguments(name)).ok
    assert not any(item.startswith("web_app ") for item in rig.machine.log)


def test_agent_reads_and_document_collection_do_not_request_application_clarification(tmp_path: Path) -> None:
    # Defect: the agent interrupts autonomous investigation to approve routine
    # reads or collection of an exact attachment into a new local file.
    for name in ("outlook_web_documents", "outlook_web_open_document", "outlook_web_download_document", "teams_web_open_chat"):
        machine = AppMachine()
        rig = ToolRig(approvals=True, work=durable(tmp_path), machine=machine)
        assert rig.call(name, **arguments(name)).ok
        assert machine.requests[-1][0] is declared(name).effect.operation


def test_invalid_business_commands_do_not_start_durable_effects(tmp_path: Path) -> None:
    # Defect: input validation happens inside an attempted effect, leaving a
    # harmless invalid request recorded as an uncertain external change.
    store, claim, clock = claimed(tmp_path)
    rig = ToolRig(work=WorkExecution(claim, store, Resources(), clock=clock))
    assert not rig.call("kanban_update_task", target_id="page-1", task_id="task-1", field="title").ok
    assert not rig.call("outlook_web_draft_reply", target_id="page-1", text="Y").ok
    assert not store.actions(claim.task.id) and not rig.machine.log


def test_confirmed_app_outcomes_complete_their_durable_actions(tmp_path: Path) -> None:
    # Defect: a verified app save still leaves its action pending and prevents
    # the user's requested task from finishing without manual reconciliation.
    for name in BINDINGS:
        folder = tmp_path / name
        folder.mkdir()
        store, claim, clock = claimed(folder)
        rig = ToolRig(work=WorkExecution(claim, store, Resources(), clock=clock), machine=AppMachine())
        assert rig.call(name, **arguments(name)).ok
        outcome = store.actions(claim.task.id)[0].outcome
        assert isinstance(outcome, ActionVerified), name
        assert not store.unverified_actions(claim.task.id)
        assert "private content" not in outcome.evidence


def test_a_receipt_for_another_task_or_a_sent_reply_keeps_the_attempt_uncertain(tmp_path: Path) -> None:
    # Defect: the journal accepts a successful reply for another card, or a
    # sent message as an unsent draft, masking a misrouted or unrequested effect.
    sent = ChatDrafted("chat-1", "private content", drafted=True, sent=cast(Literal[False], True))
    for name, operation, receipt in (
        ("kanban_update_task", KANBAN_UPDATE_TASK, TaskEdited("other-task", "title", "private content", verified=True)),
        ("teams_web_draft_reply", TEAMS_DRAFT_REPLY, sent),
    ):
        folder = tmp_path / name
        folder.mkdir()
        store, claim, clock = claimed(folder)
        rig = ToolRig(work=WorkExecution(claim, store, Resources(), clock=clock), machine=AppMachine({**RECEIPTS, operation: receipt}))
        rig.call(name, **arguments(name))
        assert isinstance(store.actions(claim.task.id)[0].outcome, ActionUncertain)
        assert store.unverified_actions(claim.task.id)


def test_conflicting_app_receipts_cannot_verify_an_effect() -> None:
    # Mutation survivors showed that changing AND to OR accepted another
    # resource's receipt, or an unmatched saved value. Each bound field of a
    # confirmation must match the requested effect.
    for name, bound in BINDINGS.items():
        tool = declared(name)
        query = tool.effect.operation.query.validate_python(arguments(name))
        match tool.effect:
            case Selection(operation, confirm) | Edit(operation, confirm) | Collection(operation, confirm):
                receipt = operation.result.validate_python(RECEIPTS[operation])
                assert isinstance(confirm(query, receipt), ActionVerified), name
                fields = _WIRE.validate_json(operation.result.dump_json(receipt))
                for field in bound:
                    conflict = operation.result.validate_json(_WIRE.dump_json({**fields, field: "different"}))
                    assert isinstance(confirm(query, conflict), ActionUncertain), (name, field)
            case Read():
                raise AssertionError(f"{name} changes application state.")


def test_approval_reviews_name_the_exact_card_or_chat(tmp_path: Path) -> None:
    # Defect: approval mode asks the user to approve an edit or reply without
    # naming the card or chat it changes.
    reviews: list[ApprovalReview] = []

    def review(item: ApprovalReview) -> bool:
        reviews.append(item)
        return False

    for name in ("kanban_comment", "teams_web_draft_reply"):
        rig = ToolRig(approvals=True, work=durable(tmp_path, review=review))
        assert not rig.call(name, **arguments(name)).ok
    # The journal appends the exact operation after the family's own summary.
    assert [item.detail.split("\n\nExact operation:")[0] for item in reviews] == ["kanban_comment\ntask-1", "teams_web_draft_reply\nchat-1"]


def test_personal_work_changes_target_the_exact_work(tmp_path: Path) -> None:
    # Defect: a dismissal, restoration or attached page loses its work target,
    # so evidence about another work item could reconcile it.
    tools = ToolRig(work=durable(tmp_path)).agent.tools
    work = target("personal-work", "work-1")
    page: Mapping[str, Json] = {"title": "Guide", "reference": {"kind": "web", "url": "https://contoso.example.test/guide"}, "work_id": "work-1"}
    assert tools["work_items_add_web_page"].classify(page).resources == ("personal-work", work)
    assert tools["work_items_restore"].classify({"work_id": "work-1"}).resources == ("personal-work", work)
    assert tools["work_items_list"].classify({}).resources == ("personal-work",)
