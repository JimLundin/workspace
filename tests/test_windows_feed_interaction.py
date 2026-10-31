"""Current bubble interactions, with fictional work and exact answer destinations."""

import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows feed interactions")
lazy from PySide6 import QtWidgets
lazy from PySide6.QtCore import Qt
lazy from PySide6.QtTest import QTest

from assistant.qt_runtime import prepare
from automation.presentation import Succeeded, ToolActivity
from automation.task import Reply, TextAnswer
from tests.agent_requests import asked
from tests.test_windows_agent_toasts import notifications

prepare()


def test_thinking_and_reply_share_one_dismissible_bubble() -> None:
    with notifications() as panel:
        panel.agent.begin("Review the fictional budget", panel.stop)
        panel.pump()
        cards = [c for c in panel.view.cards.values() if not c.retiring]
        assert len(cards) == 1, "The request and thinking must stay in one bubble."
        card = cards[0]
        assert card.dismiss.isVisible(), "Thinking needs an X independent of Stop."
        QTest.mouseClick(card.dismiss, Qt.MouseButton.LeftButton)
        panel.pump()
        panel.agent.step("Checking the fictional figures")
        panel.pump()
        assert not any(not c.retiring for c in panel.view.cards.values()), "A dismissed running bubble reappeared."
        assert panel.agent.state.busy, "Hiding a bubble must not cancel its work."


def test_expanded_turn_reserves_the_title_width_left_by_its_disclosure() -> None:
    with notifications() as panel:
        title = ("Review the fictional forecast " + "compare the figures " * 10).strip()
        panel.agent.begin(title, panel.stop)
        panel.agent.updates()(ToolActivity("check", "read_file", "fictional.csv", 1, Succeeded("24 rows")))
        panel.agent.done("The fictional figures are ready.")
        panel.agent.finish()
        panel.pump()
        card = next(card for card in panel.view.cards.values() if not card.retiring)
        card.toggle(animate=False)
        panel.pump()
        assert bool(card.expanded) and card.disclosure.isVisible()
        assert card.label.display_text() == title
        assert card.label.height() >= card.label.heightForWidth(card.label.width()), "The complete wrapped title fits beside its controls."
        assert card.label.geometry().right() < card.disclosure.x()


def test_pending_question_points_to_agent_voice_without_an_editor() -> None:
    # Defects: creating an editable reply widget, or losing the voice handoff hint.
    with notifications() as panel:
        replies: list[Reply] = []

        def record_reply(answer: Reply) -> bool:
            replies.append(answer)
            return True

        panel.agent.request_input(asked("owned-question", "Which figures should I check?", "Only the project totals.", 1), record_reply)
        panel.pump()
        card = next(c for c in panel.view.cards.values() if not c.retiring)
        assert not card.window.findChildren(QtWidgets.QPlainTextEdit)
        assert card.text.isReadOnly() and card.hint.isHidden()
        assert card.window.toolTip() == "Hold the agent voice-to-text button (N) to reply; release to send."
        assert card.text.toolTip() == card.window.toolTip()
        assert panel.agent.reply_by_voice("Use the revised totals.")
        panel.pump()
        assert replies == [TextAnswer("Use the revised totals.")]


def test_expanding_a_bubble_collapses_the_previous_one() -> None:
    # Defect: two independently expanded cards keep consuming the viewport.
    with notifications() as panel:
        for index, title in enumerate(("Check the first workbook", "Check the second workbook")):
            panel.agent.begin(title, panel.stop)
            panel.agent.updates()(ToolActivity(f"read-{index}", "read_file", f"fictional-{index}.csv", 2 * index + 1, Succeeded("24 rows")))
            panel.agent.done("The fictional figures are ready.")
            panel.agent.finish()
        panel.pump()
        first_card, second_card = sorted((card for card in panel.view.cards.values() if not card.retiring), key=lambda card: card.order)
        first_card.toggle(animate=False)
        assert bool(first_card.expanded)
        second_card.toggle(animate=False)
        assert bool(second_card.expanded) and not bool(first_card.expanded)
