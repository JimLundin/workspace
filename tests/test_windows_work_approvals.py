"""Only the actual native approval view may acknowledge a durable review."""

import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows native approval visibility")

from automation.task import ApprovalDecision, Reply
from tests.agent_requests import reviewed
from tests.test_windows_agent_toasts import notifications


def test_toast_approval_waits_for_a_visible_painted_card_and_a_fresh_request() -> None:
    replies: list[Reply] = []

    def accept(answer: Reply) -> bool:
        replies.append(answer)
        return True

    with notifications(animated=True) as panel:
        first = reviewed("first", "Write the workbook", "The complete reviewed content. Åäö.", 1.0)
        panel.agent.request_input(first, accept)
        assert not panel.agent.respond(first.id, ApprovalDecision.APPROVED)
        panel.pump()
        assert not panel.view.approval_visible(first.id)
        assert not panel.agent.respond(first.id, ApprovalDecision.APPROVED)
        panel.advance(1.0)
        assert panel.view.approval_visible(first.id)
        assert panel.agent.reply_by_voice("Approve!") and replies == [ApprovalDecision.APPROVED]
        panel.pump()
        second = reviewed("second", "Send the draft", "The complete recipients and content.", 2.0)
        panel.agent.request_input(second, accept)
        assert not panel.agent.respond(second.id, ApprovalDecision.APPROVED), "The previous visible card cannot acknowledge the new request."
        panel.pump()
        panel.advance(1.0)
        assert panel.view.approval_visible(second.id)
        assert panel.agent.respond(second.id, ApprovalDecision.APPROVED) and replies == [ApprovalDecision.APPROVED, ApprovalDecision.APPROVED]
