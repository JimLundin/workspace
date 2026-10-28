"""Native checks of our bubble adaptation, status updates and rich reply routing."""

import sys
import unittest
from unittest.mock import patch

if sys.platform != 'win32':
    raise unittest.SkipTest('Windows tool-call bubbles')

from assistant.agent_session import Answer, Failed, StreamState, Succeeded, ToolActivity
from assistant.feed_items import SourceKey, WorkItem
from assistant.feed_triage import Assessment, Solution, SolutionKind
from assistant.notifications import TurnKey
from assistant.qt import QFont
from assistant.qt_text import TextView

from .test_windows_agent_toasts import notifications


def test_real_tool_element_keeps_identity_status_and_copy_target() -> None:
    """Detect calls rendered as shared prose or bound to the wrong invocation."""
    with notifications() as panel:
        panel.agent.begin('Check the command', panel.stop)
        publish = panel.agent.updates()
        command = 'Write-Output "' + '**literal** ' * 30 + '"'
        publish(ToolActivity('cli', 'run_powershell', command, 1))
        panel.pump()
        card = panel.view.cards[TurnKey(0)]
        call = card.details.calls[0]
        assert call.objectName() == 'toolCall-cli' and call.isVisible()
        assert call.status.text() == 'Running'
        with patch('assistant.tool_call_view.QtWidgets.QApplication.clipboard') as clipboard:
            call.copy.click()
            clipboard.return_value.setText.assert_called_once_with(command)
        publish(ToolActivity('cli', 'run_powershell', command, 1, Failed('Exit code 1.\nMissing file.')))
        publish(Answer('a', 'Check **the path**.', 2, StreamState.COMPLETE))
        panel.pump()
        assert card.details.calls[0] is call and call.status.text() == 'Failed'
        card.toggle(animate=False)
        panel.pump()
        assert call.result.toPlainText() == 'Exit code 1.\nMissing file.'
        publish(ToolActivity('time', 'get_current_time', '', 3, Succeeded('Timezone: CET')))
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
        panel.agent.begin('Check the workbook', panel.stop)
        publish = panel.agent.updates()
        publish(Answer('first', 'An **earlier finding**.', 1, StreamState.COMPLETE))
        panel.pump()
        publish(ToolActivity('cli', 'run_powershell', 'git status --short', 2, Succeeded('Exit code 0.')))
        publish(Answer('last', 'The **current reply**.', 3, StreamState.COMPLETE))
        panel.pump()
        card = panel.view.cards[TurnKey(0)]
        card.toggle(animate=False)
        panel.pump()
        assert 'earlier finding' in card.details.toPlainText()
        views = card.details.findChildren(TextView)
        previous = next(view for view in views if not view.document().find('earlier finding').isNull())
        assert previous.document().find('earlier finding').charFormat().fontWeight() >= QFont.Weight.DemiBold
        assert card.text.toPlainText() == 'The current reply.'


def test_cli_call_remains_visible_and_updates_in_its_original_bubble() -> None:
    """Detect collapsed calls vanishing, duplicated windows or literal command loss."""
    with notifications() as panel:
        panel.agent.begin('Check the command', panel.stop)
        publish = panel.agent.updates()
        publish(ToolActivity('cli', 'run_powershell', 'Write-Output "**literal**"', 1))
        panel.pump()
        card = panel.view.cards[TurnKey(0)]
        handle = card.handle
        assert card.details.isVisible()
        assert 'Running' in card.details.toPlainText() and '**literal**' in card.details.toPlainText()
        assert card.details.calls[0].argument.document().find('Write-Output').charFormat().font().family() == 'Consolas'
        publish(ToolActivity('cli', 'run_powershell', 'Write-Output "**literal**"', 1, Failed('Exit code 1.\nMissing file.')))
        publish(Answer('a', 'Check **the path** and `report.csv`.', 2, StreamState.COMPLETE))
        panel.agent.finish()
        panel.pump()
        assert panel.view.cards[TurnKey(0)] is card and card.handle == handle
        assert card.details.toPlainText().count('run_powershell') == 1 and 'Failed' in card.details.toPlainText()
        assert card.text.document().find('the path').charFormat().fontWeight() >= QFont.Weight.DemiBold
        assert card.text.document().find('report.csv').charFormat().font().family() == 'Consolas'
        card.disclosure.click()
        panel.pump()
        assert 'Exit code 1.' in card.details.toPlainText() and 'Missing file.' in card.details.toPlainText()
        assert card.details.geometry().bottom() < card.text.y()


def test_time_observation_and_proposed_reply_reach_native_rich_views() -> None:
    """Detect time results hidden by collapse and reply variants flattened by routing."""
    with notifications() as panel:
        panel.agent.begin('What time is it?', panel.stop)
        publish = panel.agent.updates()
        publish(ToolActivity('time', 'get_current_time', '', 1, Succeeded('Local time: 2026-10-28T12:00:00+01:00\nTimezone: CET')))
        publish(Answer('a', 'It is **noon**.', 2, StreamState.COMPLETE))
        panel.agent.finish()
        panel.pump()
        card = panel.view.cards[TurnKey(0)]
        assert card.details.isVisible() and 'get_current_time' in card.details.toPlainText()
        assert '12:00:00+01:00' in card.details.toPlainText()
        item = Assessment('draft', (), 'Review budget', 'A review is needed.', 'Prepare a reply.', '', 1, 3,
                          solutions=(Solution('reply', 'Draft reply', SolutionKind.DRAFT, 'Please review **the totals** in `FY27`.'),))
        row = WorkItem(SourceKey('triage', 'draft'), item, item.title)
        card.expanded = True
        card.render(row, card.width, card.maximum, panel.view.material_preference())
        assert '**' not in card.text.toPlainText()
        assert card.text.document().find('the totals').charFormat().fontWeight() >= QFont.Weight.DemiBold
        assert card.text.document().find('FY27').charFormat().font().family() == 'Consolas'
