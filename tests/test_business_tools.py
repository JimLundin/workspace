"""Registered integration tools, private previews and exact resource ownership."""

import json
import threading
from collections.abc import Mapping
from pathlib import Path

from assistant.business_tools import WEB_SPECS, verified_outcome
from assistant.llm import Json
from automation.actions import Change, Observation, Resources
from automation.execution import WorkExecution
from automation.task import ActionUncertain, ActionVerified
from tests.test_agent import FakeMachine, ToolRig, durable
from tests.test_work_actions import claimed


class AppMachine(FakeMachine):
    """A concrete app capability with immutable replies supplied at composition."""

    __slots__ = ("receipts",)

    def __init__(self, receipts: Mapping[str, str]) -> None:
        super().__init__()
        self.receipts: frozendict[str, str] = frozendict(receipts)

    def browse(self, operation: str, arguments: dict[str, Json], cancel: threading.Event) -> tuple[str, bytes | None]:
        super().browse(operation, arguments, cancel)
        return self.receipts[operation], None


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
    # Defect: registration sends an app request to the wrong owner or shows
    # private mail/card content despite integration redaction. Each tool gets
    # its own task because the fixture's unverified app results suspend a task.
    machine = FakeMachine()
    for spec in WEB_SPECS:
        rig = ToolRig(work=durable(tmp_path), machine=machine)
        assert rig.call(spec.name, **arguments(spec.name)).ok
        assert machine.log[-1].startswith("browser " + spec.name + " ")
        assert all("private content" not in str(item) for item in (*rig.window.log, *rig.window.live))
    before = tuple(machine.log)
    rig = ToolRig(work=durable(tmp_path), machine=machine)
    rig.agent.stop.set()
    assert not rig.call("kanban_comment", **arguments("kanban_comment")).ok
    assert tuple(rig.machine.log) == before


def test_business_reads_and_mutations_have_exact_resource_markers(tmp_path: Path) -> None:
    # Defect: a read creates a pending effect, or evidence from another card,
    # conversation or mailbox could resolve an uncertain mutation.
    tools = ToolRig(work=durable(tmp_path)).agent.tools

    def resources(name: str, arguments: Mapping[str, Json]) -> tuple[str, ...]:
        return tools[name].classify(arguments).resources

    for name in ("kanban_board", "kanban_read_task", "teams_web_read", "outlook_web_search", "outlook_web_read", "outlook_web_documents"):
        assert isinstance(tools[name].classify({}), Observation)
    assert isinstance(tools["kanban_update_task"].classify({}), Change)
    first = resources("kanban_update_task", {"target_id": "page-1", "task_id": "task-1"})
    second = resources("kanban_read_task", {"target_id": "page-1", "task_id": "task-2"})
    assert "browser" in first and first[-1] != second[-1]
    assert resources("teams_web_draft_reply", {"target_id": "page-1", "chat_id": "chat-1"}) != resources(
        "teams_web_read", {"target_id": "page-1", "chat_id": "chat-2"}
    )
    assert resources("outlook_web_draft_reply", {"conversation_id": "mail-1"}) != resources("outlook_web_open_mail", {"conversation_id": "mail-2"})


def test_approval_mode_declines_business_writes_before_the_machine(tmp_path: Path) -> None:
    # Defect: expanded tools bypass the existing optional approval policy.
    rig = ToolRig(approvals=True, work=durable(tmp_path))
    for name in ("kanban_update_task", "kanban_move_task", "kanban_comment", "teams_web_draft_reply", "outlook_web_draft_reply"):
        assert not rig.call(name, **arguments(name)).ok
    assert not any(item.startswith(("browser ", "teams ")) for item in rig.machine.log)


def test_agent_reads_and_document_collection_do_not_request_application_clarification(tmp_path: Path) -> None:
    # Defect: the agent interrupts autonomous investigation to approve routine
    # reads or collection of an exact attachment into a new local file.
    for name in ("outlook_web_documents", "outlook_web_open_document", "outlook_web_download_document", "teams_web_open_chat"):
        rig = ToolRig(approvals=True, work=durable(tmp_path))
        assert rig.call(name, **arguments(name)).ok
        assert rig.machine.log[-1].startswith("browser " + name + " ")


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
    for name, receipt in confirmations().items():
        folder = tmp_path / name
        folder.mkdir()
        store, claim, clock = claimed(folder)
        work = WorkExecution(claim, store, Resources(), clock=clock)
        response: dict[str, Json] = dict(receipt)
        rig = ToolRig(work=work, machine=AppMachine({name: json.dumps(response)}))
        assert rig.call(name, **arguments(name)).ok
        outcome = store.actions(claim.task.id)[0].outcome
        assert isinstance(outcome, ActionVerified)
        assert not store.unverified_actions(claim.task.id)
        assert "private content" not in outcome.evidence


def test_a_receipt_for_another_task_keeps_the_attempt_uncertain(tmp_path: Path) -> None:
    # Defect: the journal accepts a successful reply for another card, masking
    # an interrupted or misrouted edit and permitting an unsafe retry.
    store, claim, clock = claimed(tmp_path)
    receipt = {"verified": True, "task_id": "other-task", "field": "title", "value": "private content"}
    rig = ToolRig(
        work=WorkExecution(claim, store, Resources(), clock=clock),
        machine=AppMachine({"kanban_update_task": json.dumps(receipt)}),
    )
    rig.call("kanban_update_task", **arguments("kanban_update_task"))
    assert isinstance(store.actions(claim.task.id)[0].outcome, ActionUncertain)
    assert store.unverified_actions(claim.task.id)


def confirmations() -> Mapping[str, Mapping[str, Json]]:
    return {
        "kanban_update_task": {"verified": True, "task_id": "task-1", "field": "title", "value": "private content"},
        "kanban_move_task": {"verified": True, "task_id": "task-1", "column": "Done"},
        "kanban_comment": {"posted": True, "task_id": "task-1", "text": "private content"},
        "teams_web_open_chat": {"opened": True, "chat_id": "chat-1"},
        "teams_web_draft_reply": {"drafted": True, "sent": False, "chat_id": "chat-1", "text": "private content"},
        "outlook_web_open_mail": {"opened": True, "conversation_id": "mail-1"},
        "outlook_web_open_document": {"opened": True, "conversation_id": "mail-1", "attachment_id": "attachment-1"},
        "outlook_web_draft_reply": {"drafted": True, "sent": False, "conversation_id": "mail-1", "text": "private content"},
    }


def test_conflicting_or_incomplete_app_receipts_cannot_verify_an_effect() -> None:
    # Mutation survivors showed that changing AND to OR accepted another
    # resource's receipt, or an unmatched saved value. Each required confirmation
    # must bind the requested effect; sent mail cannot confirm an unsent draft.
    for name, receipt in confirmations().items():
        for key, value in receipt.items():
            match value:
                case bool():
                    conflict: Json = not value
                case str():
                    conflict = "different"
                case _:
                    raise AssertionError("Unexpected app confirmation field")
            wrong = {**receipt, key: conflict}
            missing = {field: item for field, item in receipt.items() if field != key}
            for result in (wrong, missing):
                assert isinstance(verified_outcome(name, arguments(name), json.dumps(result)), ActionUncertain)
    assert isinstance(verified_outcome("kanban_update_task", arguments("kanban_update_task"), "partial response"), ActionUncertain)
