"""Current browser capabilities through the agent and its real durable journal."""

import json
from pathlib import Path
from typing import cast

from automation.actions import Resources
from automation.execution import ApprovalReview, WorkExecution
from automation.json_value import Json
from tests.fake_endpoint import fake_endpoint
from tests.test_agent import Rig, ToolRig, calls, durable, says
from tests.test_work_actions import claimed


def test_retired_embedded_browser_tools_cannot_reach_the_machine_or_start_actions(tmp_path: Path) -> None:
    store, claim, clock = claimed(tmp_path)
    rig = ToolRig(work=WorkExecution(claim, store, Resources(), clock=clock))
    for operation in ("list", "open", "navigate", "snapshot", "action"):
        result = rig.call("browser_app_" + operation, url="https://example.invalid", target_id="retired-card", id="send", action="click")
        assert not result.ok and "no tool called" in result.text
    assert not rig.machine.log and not store.actions(claim.task.id)


def test_model_receives_only_current_browser_capabilities(tmp_path: Path) -> None:
    with fake_endpoint() as endpoint:
        rig = Rig(endpoint, calls(("browser_tabs", {})), says("Tabs inspected."), work=durable(tmp_path))
        rig.run()
        data: object = json.loads(endpoint.received[0].body)
        assert isinstance(data, dict)
        tools = cast("list[dict[str, object]]", cast("dict[str, object]", data)["tools"])
        names = {str(tool["name"]) for tool in tools}
        assert {"browser_attach", "browser_open", "browser_tabs", "browser_snapshot", "browser_action"} <= names
        assert not any(name.startswith("browser_app_") for name in names)
        assert rig.machine.log == ["browser PageList(offset=0, limit=20)"]


def test_browser_approval_reviews_name_the_address_or_exact_page(tmp_path: Path) -> None:
    # Defect: approval mode asks to approve a navigation or page script without
    # naming the address or page it acts on.
    reviews: list[ApprovalReview] = []

    def review(item: ApprovalReview) -> bool:
        reviews.append(item)
        return False

    cases: tuple[tuple[str, dict[str, Json]], ...] = (
        ("browser_open", {"url": "https://example.com/"}),
        ("browser_evaluate", {"target_id": "page-1", "expression": "1"}),
        ("browser_close", {"tab_ids": [7]}),
    )
    for name, arguments in cases:
        rig = ToolRig(approvals=True, work=durable(tmp_path, review=review))
        assert not rig.call(name, **arguments).ok
    summaries = [item.detail.split("\n\nExact operation:")[0] for item in reviews]
    assert summaries == ["open: https://example.com/", "evaluate: page-1", "close: Workspace browser"]
