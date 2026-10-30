"""Native checks of our bubble adaptation, status updates and rich reply routing."""

import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows tool-call bubbles")

lazy import shiboken6
lazy from PySide6 import QtWidgets
lazy from PySide6.QtCore import Qt
lazy from PySide6.QtGui import QFont

from assistant.feed_contracts import SolutionKind
from assistant.feed_items import WorkItem
from assistant.feed_sources import SourceKey, SourceKind
from assistant.feed_triage import Assessment, Solution
from assistant.notifications import TurnKey
from assistant.qt_runtime import prepare
from assistant.tool_call_view import ToolCall
from assistant.tool_text import State, presentation
from assistant.ui_components.text import TextView
from automation.presentation import Answer, Failed, StreamState, Succeeded, ToolActivity
from tests.test_windows_agent_toasts import notifications

prepare()


def test_real_tool_element_keeps_identity_status_and_copy_target() -> None:
    """Detect calls rendered as shared prose or bound to the wrong invocation."""
    with notifications() as panel:
        panel.agent.begin("Check the command", panel.stop)
        publish = panel.agent.updates()
        command = 'Write-Output "' + "**literal** " * 30 + '"'
        publish(ToolActivity("cli", "run_powershell", command, 1))
        panel.pump()
        card = panel.view.cards[TurnKey(0)]
        call = card.details.calls[0]
        assert call.objectName() == "toolCall-cli" and call.isVisible()
        assert call.accessibleDescription() == "Running"
        publish(ToolActivity("cli", "run_powershell", command, 1, Failed("Exit code 1.\nMissing file.")))
        publish(Answer("a", "Check **the path**.", 2, StreamState.COMPLETE))
        panel.pump()
        assert card.details.calls[0] is call and call.accessibleDescription() == "Failed"
        card.toggle(animate=False)
        panel.pump()
        assert call.call.result == "Exit code 1.\nMissing file." and "Missing file." in call.toolTip()
        assert call.height() <= 32
        publish(ToolActivity("time", "get_current_time", "", 3, Succeeded("Timezone: CET")))
        panel.pump()
        assert card.details.calls[0] is call and len(card.details.calls) == 2
        card.toggle(animate=False)
        panel.pump()
        assert not call.isVisible() and card.details.calls[1].isVisible()
        card.toggle(animate=False)
        panel.pump()
        assert card.details.calls[0] is call and call.isVisible()


def test_previous_reply_moves_into_native_history_without_losing_markdown() -> None:
    """Detect history rows failing during native composition or flattening replies."""
    with notifications() as panel:
        panel.agent.begin("Check the workbook", panel.stop)
        publish = panel.agent.updates()
        publish(Answer("first", "An **earlier finding**.", 1, StreamState.COMPLETE))
        panel.pump()
        publish(ToolActivity("cli", "run_powershell", "git status --short", 2, Succeeded("Exit code 0.")))
        publish(Answer("last", "The **current reply**.", 3, StreamState.COMPLETE))
        panel.pump()
        card = panel.view.cards[TurnKey(0)]
        card.toggle(animate=False)
        panel.pump()
        assert "earlier finding" in card.details.toPlainText()
        views = card.details.findChildren(TextView)
        previous = next(view for view in views if not view.document().find("earlier finding").isNull())
        assert previous.document().find("earlier finding").charFormat().fontWeight() >= QFont.Weight.DemiBold
        assert card.text.toPlainText() == "The current reply."


def test_cli_call_remains_visible_and_updates_in_its_original_bubble() -> None:
    """Detect collapsed calls vanishing, duplicated windows or literal command loss."""
    with notifications() as panel:
        panel.agent.begin("Check the command", panel.stop)
        publish = panel.agent.updates()
        publish(ToolActivity("cli", "run_powershell", 'Write-Output "**literal**"', 1))
        panel.pump()
        card = panel.view.cards[TurnKey(0)]
        handle = card.handle
        assert card.details.isVisible()
        assert "Running" in card.details.toPlainText() and "**literal**" in card.details.toPlainText()
        assert card.details.calls[0].title.textFormat() is Qt.TextFormat.PlainText
        assert card.details.calls[0].width() == card.details.viewport().width()
        assert card.details.calls[0].title.text().startswith("PowerShell"), (
            card.details.calls[0].title.text(),
            card.details.calls[0].size(),
            card.details.viewport().size(),
        )
        assert card.details.calls[0].call.argument == 'Write-Output "**literal**"'
        publish(ToolActivity("cli", "run_powershell", 'Write-Output "**literal**"', 1, Failed("Exit code 1.\nMissing file.")))
        publish(Answer("a", "Check **the path** and `report.csv`.", 2, StreamState.COMPLETE))
        panel.agent.finish()
        panel.pump()
        assert panel.view.cards[TurnKey(0)] is card and card.handle == handle
        assert card.details.toPlainText().count("run_powershell") == 1 and "Failed" in card.details.toPlainText()
        assert card.text.document().find("the path").charFormat().fontWeight() >= QFont.Weight.DemiBold
        assert card.text.document().find("report.csv").charFormat().font().family() == "Consolas"
        card.disclosure.click()
        panel.pump()
        assert "Exit code 1." in card.details.toPlainText() and "Missing file." in card.details.toPlainText()
        assert card.details.geometry().bottom() < card.text.y()


def test_time_observation_and_proposed_reply_reach_native_rich_views() -> None:
    """Detect time results hidden by collapse and reply variants flattened by routing."""
    with notifications() as panel:
        panel.agent.begin("What time is it?", panel.stop)
        publish = panel.agent.updates()
        publish(ToolActivity("time", "get_current_time", "", 1, Succeeded("Local time: 2026-10-28T12:00:00+01:00\nTimezone: CET")))
        publish(Answer("a", "It is **noon**.", 2, StreamState.COMPLETE))
        panel.agent.finish()
        panel.pump()
        card = panel.view.cards[TurnKey(0)]
        assert card.details.isVisible() and "get_current_time" in card.details.toPlainText()
        assert "12:00:00+01:00" in card.details.toPlainText()
        item = Assessment(
            "draft",
            (),
            "Review budget",
            "A review is needed.",
            "Prepare a reply.",
            "",
            1,
            3,
            solutions=(Solution("reply", "Draft reply", SolutionKind.DRAFT, "Please review **the totals** in `FY27`."),),
        )
        row = WorkItem(SourceKey(SourceKind.PROPOSAL, "draft"), item, item.title)
        card.expanded = True
        card.render(row, card.width, card.maximum, panel.view.material_preference())
        assert "**" not in card.text.toPlainText()
        assert card.text.document().find("the totals").charFormat().fontWeight() >= QFont.Weight.DemiBold
        assert card.text.document().find("FY27").charFormat().font().family() == "Consolas"


def test_native_copy_action_uses_the_complete_current_invocation_payload() -> None:
    """Detect a copy action using the shortened preview or an earlier invocation."""
    with notifications():
        copied: list[str] = []
        parent = QtWidgets.QWidget()
        command = 'Write-Output "' + "**literal** " * 30 + '"'
        initial = presentation(ToolActivity("cli", "run_powershell", command, 1), expanded=False)
        call = ToolCall(parent, initial, copied.append)
        try:
            call.copy.click()
            revised = command + "; Get-Date"
            current = presentation(ToolActivity("cli", "run_powershell", revised, 1), expanded=False)
            call.present(current, 360)
            call.copy.click()
            assert copied == [command, revised]
        finally:
            parent.close()
            shiboken6.delete(parent)


def test_tool_rows_keep_one_line_and_paint_running_success_and_failure_feedback() -> None:
    # Defects: arguments/output grow a payload box, status updates rebuild the row,
    # or the running/success/failure states paint the same stationary indicator.
    with notifications():
        parent = QtWidgets.QWidget()
        activity = ToolActivity("row", "run_powershell", 'Write-Output "**literal**"\n' * 50, 1)
        row = ToolCall(parent, presentation(activity, expanded=True))
        try:
            row.present(presentation(activity, expanded=True), 300)
            status = row.status
            row.pulse(0)
            before = status.grab().toImage()
            row.pulse(90)
            assert status.grab().toImage() != before
            height = row.height()
            assert height <= 32 and not row.findChildren(TextView)
            for outcome, state in ((Succeeded("A long result.\n" * 50), State.SUCCEEDED), (Failed("Missing file."), State.FAILED)):
                call = presentation(ToolActivity(activity.identity, activity.name, activity.detail, 1, outcome), expanded=True)
                row.present(call, 300)
                assert row.status is status and row.call.state is state
                assert row.height() == height and row.rect().contains(row.title.geometry())
                assert row.rect().contains(row.copy.geometry()) and row.title.geometry().right() < row.copy.x()
                image = status.grab().toImage()
                pixels = tuple(image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height()))
                if state is State.SUCCEEDED:
                    assert any(pixel.alpha() > 100 and pixel.green() > pixel.red() * 1.2 for pixel in pixels)
                else:
                    assert any(pixel.alpha() > 100 and pixel.red() > pixel.green() * 1.2 for pixel in pixels)
                angle = status.angle
                row.pulse(180)
                assert status.angle == angle, "A completed tool kept spinning."
        finally:
            parent.close()
            shiboken6.delete(parent)
