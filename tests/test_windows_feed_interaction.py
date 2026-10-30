"""Current bubble interactions, with fictional work and exact answer destinations."""

import sys
import unittest
from dataclasses import replace

if sys.platform != "win32":
    raise unittest.SkipTest("Windows feed interactions")
lazy from PySide6 import QtWidgets
lazy from PySide6.QtCore import Qt
lazy from PySide6.QtTest import QTest

from assistant.agent_session import Succeeded, ToolActivity
from assistant.console_requests import Answer, Command, Provider, request
from assistant.feed_contracts import SolutionKind
from assistant.feed_items import WorkItem
from assistant.feed_observation import ConsolesObserved, TriageObserved
from assistant.feed_origin import FeedRequest
from assistant.feed_triage import Assessment, Board, Solution
from assistant.notification_text import details, spans
from assistant.notifications import Turn
from assistant.qt_runtime import prepare
from tests.agent_requests import asked
from tests.test_console_inbox import event
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
        replies: list[str] = []

        def record_reply(answer: str) -> bool:
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
        assert replies == ["Use the revised totals."]


def test_console_options_are_pills_and_route_to_the_exact_question() -> None:
    with notifications() as panel:
        answers: list[Command] = []

        def answer(command: Command) -> bool:
            answers.append(command)
            return True

        panel.console = answer
        current = request(Provider.CLAUDE, event(Provider.CLAUDE, "owned-console"), "owned-console", 1)
        panel.observe(ConsolesObserved((current,)))
        panel.pump()
        card = next(c for c in panel.view.cards.values() if isinstance(c.content, WorkItem))
        assert card.choices and not card.hint.text().startswith("<a"), "Question options must be pill buttons."
        assert not card.window.findChildren(QtWidgets.QPlainTextEdit)
        card.choices[0].click()
        panel.pump()
        assert len(answers) == 1
        command = answers[0]
        assert isinstance(command, Answer)
        assert command.request == current.identity and command.question == 0 and command.text == "Revenue"


def test_proposal_thinking_question_and_reply_keep_the_same_source_bubble() -> None:
    with notifications() as panel:
        proposal = Assessment(
            "fictional-linked",
            (("source", "revision"),),
            "Check the revised totals",
            "The totals need review.",
            "Compare the two sheets.",
            "",
            1,
            1,
            solutions=(Solution("check", "Compare sheets", SolutionKind.CHECK, "Compare the original and revised totals."),),
        )
        panel.observe(TriageObserved(Board(enabled=True, items=(proposal,))))
        panel.pump()
        card = next(card for card in panel.view.cards.values() if not card.retiring)
        context = FeedRequest(proposal.identity, proposal.title)
        panel.agent.begin(proposal.title, panel.stop, source=context)
        panel.pump()
        assert panel.view.cards[card.key] is card and isinstance(card.content, Turn)
        assert len([card for card in panel.view.cards.values() if not card.retiring]) == 1
        assert card.label.text() == proposal.title and card.dismiss.isVisible()
        panel.agent.request_input(asked("linked-question", "Use the revised sheet?", "It includes the corrections.", 2), lambda _answer: True)
        panel.pump()
        assert panel.view.cards[card.key] is card
        assert not card.window.findChildren(QtWidgets.QPlainTextEdit)
        assert panel.agent.reply_by_voice("No, compare the original first.")
        panel.pump()
        panel.agent.done("The original totals differ. Review the corrections before replying.")
        panel.agent.finish()
        panel.pump()
        assert panel.view.cards[card.key] is card and card.stop.isHidden()
        assert "original totals differ" in card.text.toPlainText()
        content = card.content
        assert content is not None
        shown = "".join(span.text for span in (*spans(content), *details(content)))
        assert "Context JSON" not in shown and "source_revisions" not in shown

        panel.agent.begin("Continue the comparison", panel.stop, source=context)
        panel.pump()
        assert panel.view.cards[card.key] is card
        assert len([card for card in panel.view.cards.values() if not card.retiring]) == 1


def test_expanding_a_bubble_collapses_the_previous_one() -> None:
    # Defect: two independently expanded cards keep consuming the viewport.
    with notifications() as panel:
        first = Assessment("first", (), "First request", "A fictional summary. " * 8, "Compare the totals.", "", 1, 1)
        second = replace(first, identity="second", title="Second request", created_at=2)
        panel.observe(TriageObserved(Board(enabled=True, items=(first, second))))
        panel.pump()
        cards = tuple(card for card in panel.view.cards.values() if not card.retiring)
        assert len(cards) == 2
        first_card, second_card = cards
        collapsed = first_card.height
        first_card.toggle(animate=False)
        assert bool(first_card.expanded) and first_card.height > collapsed
        second_card.toggle(animate=False)
        assert not bool(first_card.expanded) and first_card.height == collapsed
        assert bool(second_card.expanded) and sum(bool(card.expanded) for card in cards) == 1
        second_card.toggle(animate=False)
        assert not any(bool(card.expanded) for card in cards)
