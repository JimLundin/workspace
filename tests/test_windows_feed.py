"""One floating read-only feed owns source work, actions and agent replies."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows floating work feed")

lazy from PySide6.QtCore import QPoint, QRectF, Qt
lazy from PySide6.QtGui import QPainterPath
lazy from PySide6.QtTest import QTest

from assistant.communications import Acknowledgement, Update, WindowsNotice, handle, update_fingerprint
from assistant.feed_items import WorkItem, action_spans
from assistant.feed_origin import App
from assistant.feed_triage import Assessment, Board, Solution, SolutionKind, candidate, collect, decode, proposal_revision
from assistant.notification_sources import NOTIFICATION_STATE, HandleNotice
from assistant.notifications import MAX_VISIBLE
from assistant.qt_runtime import prepare
from assistant.qt_ui import application
from assistant.state_store import SavedState
from assistant.system_notices import Notice, NoticeKey, Observed
from assistant.toast_card import Card
from assistant.ui_components.appearance import CONTROL_STYLE
from assistant.ui_components.bubble import TITLE_SIZE
from tests.communications_fixture import communication_feed
from tests.test_communications_service import LocalCipher
from tests.test_feed_triage import output
from tests.test_windows_agent_toasts import notifications, widget_rect
from tests.test_windows_inbox_attention import InboxUi
from winapi.shapes import Rect

prepare()


def click_bubble(card: Card) -> None:
    QTest.mouseClick(card.window, Qt.MouseButton.LeftButton, pos=QPoint(card.label.x() + 4, card.label.y() + 4))


def test_source_badge_overlaps_and_title_shares_header_with_controls() -> None:
    with notifications() as panel:
        feed = replace(
            communication_feed(),
            updates=(Update(WindowsNotice(NoticeKey(81, 100), "outlook"), "Review reminder", "Please review the figures.", "Outlook", 2),),
        )
        candidates = collect(feed, ())
        proposal = Assessment(
            "owned-plan",
            tuple((item.identity, item.revision) for item in candidates),
            "Review the figures",
            "Check **the totals** in `FY27`.",
            "Compare both sheets.",
            "Shall I prepare a draft?",
            1,
            2,
        )
        panel.agent.communications(feed, {})
        panel.agent.triage(Board(enabled=True, items=(proposal,)))
        panel.pump()
        panel.agent.show(focus=True)
        panel.pump()
        card = next(card for card in panel.view.cards.values() if isinstance(card.content, WorkItem))
        assert card.label.isVisible() and card.label.text() == "Review the figures" and card.caption.isHidden() and card.badge.isVisible()
        assert isinstance(card.content, WorkItem) and [origin.app for origin in card.content.origins] == [App.TEAMS, App.OUTLOOK]
        assert "Microsoft Teams" in card.badge.accessibleName() and "Outlook" in card.badge.accessibleName()
        assert card.bounds is not None
        assert card.surface_bounds.left > card.bounds.left and card.surface_bounds.top > card.bounds.top
        assert card.dismiss.geometry().right() == card.window.width() - 9
        assert card.disclosure.isHidden()
        assert card.badge.geometry().left() == 0
        assert card.badge.geometry().right() < card.label.x()
        assert card.label.geometry().right() < card.dismiss.x()
        assert card.text.isVisible() and card.text.toPlainText() == proposal.suggestion
        assert card.window.accessibleDescription() == "Click to expand details"
        click_bubble(card)
        panel.pump()
        assert "Review the figures" not in card.text.document().toPlainText()
        assert card.label.font().pointSizeF() > 10.5
        assert "Shall I prepare a draft?" not in card.text.toPlainText()


def test_feed_details_expand_on_request_and_never_scroll_themselves() -> None:
    with notifications() as panel:
        original = "Fictional source content: check the FY27 forecast before Friday."
        feed = replace(
            communication_feed(),
            messages=(),
            updates=(Update(WindowsNotice(NoticeKey(811, 100), "outlook"), "Forecast review", original, "Outlook", 2),),
        )
        source = collect(feed, ())[0]
        title = "Review the complete fictional forecast and compare all the revised figures before Friday"
        proposal = Assessment(
            "forecast",
            ((source.identity, source.revision),),
            title,
            "\n".join(f"Paragraph {index}: **Compare the forecast** with the previous figures." for index in range(60)),
            "Check the totals.",
            "Shall I prepare a draft?",
            2,
            2,
        )
        panel.agent.communications(feed, {})
        panel.agent.triage(Board(enabled=True, items=(proposal,)))
        panel.pump()
        card = next(card for card in panel.view.cards.values() if isinstance(card.content, WorkItem))
        handle, collapsed_height = card.handle, card.height
        assert card.label.text() == proposal.title and not bool(card.expanded)
        assert card.label.display_text() != title, "The compact title needs an ellipsis."
        click_bubble(card)
        panel.pump()
        assert bool(card.expanded) and card.height > collapsed_height and card.handle == handle
        assert card.label.display_text() == title, "Expansion reveals the full title."
        assert card.label.height() >= card.label.heightForWidth(card.label.width())
        assert card.label.height() > card.label.fontMetrics().height()
        assert card.label.geometry().right() < card.dismiss.x()
        assert original in card.text.toPlainText() and "Check the totals." in card.text.toPlainText()
        assert card.window.accessibleDescription() == "Click to hide details" and card.dismiss.isVisible()
        assert card.disclosure.isHidden()
        assert not card.needs_reading() and card.overflow() > 0
        panel.advance(30)
        assert card.text.offset == 0
        card.scroll_delta(-240)
        offset = card.text.offset
        assert offset > 0
        panel.view.set_hover(card.key, inside=False)
        panel.advance(60)
        assert card.text.offset == offset
        click_bubble(card)
        panel.pump()
        assert not bool(card.expanded) and card.label.text() == proposal.title and card.text.offset == 0
        assert card.height == collapsed_height


def test_curated_bubbles_show_priority_at_the_top_and_dismiss_without_opening_the_composer() -> None:
    with notifications() as panel:
        items = tuple(
            Assessment(
                str(index),
                ((str(index), "revision"),),
                f"Work {index}",
                "Needs review",
                "Review it",
                "",
                2 if index == 0 else 1 if index < 3 else 0,
                index + 1,
            )
            for index in range(8)
        )
        panel.agent.triage(Board(enabled=True, items=items))
        panel.pump()
        visible = sorted((card for card in panel.view.cards.values() if not card.retiring), key=card_y)
        assert [card.content.title for card in visible if isinstance(card.content, WorkItem)] == ["Work 0", "Work 1", "Work 2"]
        first = visible[0]
        assert first.dismiss.isVisible() and first.dismiss.accessibleName() == "Dismiss item"
        assert first.label.geometry().right() < first.dismiss.x()
        assert first.text.isVisible() and first.prepared is not None and first.prepared[2].body_height > 0
        first.dismiss.click()
        panel.pump()
        visible = sorted((card for card in panel.view.cards.values() if not card.retiring), key=card_y)
        assert [card.content.title for card in visible if isinstance(card.content, WorkItem)] == ["Work 1", "Work 2", "Work 3"]
        assert len(panel.agent.state.triage.actions) == 7
        panel.dismiss_allowed = False
        visible[0].dismiss.click()
        panel.pump()
        assert len(panel.agent.state.triage.actions) == 7


def test_windows_notifications_use_the_chat_renderer_and_handling_removes_only_the_exact_work_item() -> None:
    with notifications() as panel:
        commands = panel.commands
        first = Update(WindowsNotice(NoticeKey(91, 100), "owned"), "Review the figures", "A fictional notice", "Outlook", 1)
        second = Update(WindowsNotice(NoticeKey(92, 101), "owned"), "Another request", "Another fictional notice", "Outlook", 2)
        feed = replace(communication_feed(), messages=(), updates=(first, second))
        panel.agent.communications(feed, {})
        panel.pump()
        card = next(card for card in panel.view.cards.values() if isinstance(card.content, WorkItem) and card.content.item == first)
        assert card.text.toPlainText().startswith("Review the figures") and card.glass
        done = next(button for button in card.choices if button.text() == "Done")
        assert done.isVisible() and card.window.rect().contains(done.geometry())
        assert isinstance(card.content, WorkItem)
        action = next(span.link for span in action_spans(card.content) if span.link.startswith("workspace://done?"))
        panel.view.action_link(action)
        assert commands[-1] == HandleNotice(Notice(NoticeKey(91, 100), "owned", "Outlook", "Review the figures", "A fictional notice"))
        panel.agent.communications(handle(feed, (Acknowledgement(first.key, update_fingerprint(first)),)), {})
        panel.pump()
        assert any(isinstance(card.content, WorkItem) and card.content.item == second for card in panel.view.cards.values())
        assert not any(isinstance(card.content, WorkItem) and card.content.item == first and not card.retiring for card in panel.view.cards.values())


def test_short_screen_keeps_every_work_item_reachable_through_the_bubble_pagination() -> None:
    with notifications() as panel:
        updates = tuple(
            Update(WindowsNotice(NoticeKey(index, 100 + index), "owned"), f"Item {index}", "Fictional notice", "Mail", index) for index in range(1, 9)
        )
        panel.desktop.bounds = Rect(0, 0, 700, 560)
        panel.agent.communications(replace(communication_feed(), messages=(), updates=updates), {})
        panel.agent.show(focus=True)
        panel.pump()
        view = panel.view
        seen: set[tuple[str, str]] = set()
        assert 0 < view.capacity < MAX_VISIBLE
        for _page in range(len(updates)):
            seen.update(
                card.content.item.key
                for card in view.cards.values()
                if isinstance(card.content, WorkItem) and isinstance(card.content.item, Update) and not card.retiring
            )
            if view.page >= view.stack.pages - 1:
                break
            view.older()
            panel.pump()
        assert seen == {update.key for update in updates}
        assert view.page > 0
        view.newer()
        panel.pump()


def test_native_notices_are_available_as_agent_context_without_creating_floating_alerts(tmp_path: Path) -> None:
    # Defect: the production Ui still turns app observations into floating
    # cards, or suppressing presentation drops the underlying source context.
    original_style = application().styleSheet()
    ui = InboxUi()
    ui.configure_communications(lambda _: True, SavedState(tmp_path / "notifications.bin", NOTIFICATION_STATE, cipher=LocalCipher()))
    try:
        agent = ui.agent(None, lambda: None, reveal=False)
        agent.show(focus=False)
        ui.pump()
        notice = Notice(NoticeKey(11, 100), "owned", "Mail", "Review this", "Immediate fictional notice")
        ui.system_notices(Observed((notice,)))
        ui.communications_changed(communication_feed(), {})
        ui.pump()
        assert not ui.feed.stack.toasts and not ui.feed.cards
        assert ui.communications.messages
        assert any(item.source == WindowsNotice(notice.key, notice.app_id) for item in ui.communications.updates)
    finally:
        ui.dispose()
        ui.root.setStyleSheet(original_style)


def test_solution_buttons_are_compact_and_start_exact_work_without_a_composer() -> None:

    with notifications() as panel:
        source = candidate("chat", "fixture", "Budget", "Review it.", 1)
        item = decode(output(([source.identity], "action")), (source,))[0]
        submissions = panel.choices
        panel.agent.triage(Board(enabled=True, items=(item,)))
        panel.pump()
        card = next(card for card in panel.view.cards.values() if isinstance(card.content, WorkItem))
        assert card.label.text() == item.title and not bool(card.expanded)
        assert item.suggestion in card.text.toPlainText() and card.text.isVisible()
        assert len(card.choices) == 2 and all(button.isVisible() for button in card.choices)
        assert card.choices[0].accessibleName() == "Check totals · Recommended"
        assert card.choices[0].geometry().bottom() < card.window.height()
        assert card.choices[0].geometry().right() < card.choices[1].geometry().left()
        height = card.height
        card.choices[0].click()
        panel.pump()
        assert submissions == [(item.identity, proposal_revision(item), "1")]
        assert card.chosen and all(not button.isEnabled() for button in card.choices)
        assert card.choices[0].text() == "Queued"
        click_bubble(card)
        panel.pump()
        assert bool(card.expanded) and card.height > height and not card.hint.isVisible()
        click_bubble(card)
        panel.pump()
        assert card.height == height and card.chosen


def test_failed_solution_start_keeps_choices_available() -> None:

    with notifications() as panel:
        source = candidate("chat", "fixture", "Review", "Please check.", 1)
        item = decode(output(([source.identity], "action")), (source,))[0]
        panel.choose_allowed = False
        panel.agent.triage(Board(enabled=True, items=(item,)))
        panel.pump()
        card = next(card for card in panel.view.cards.values() if isinstance(card.content, WorkItem))
        card.choices[0].click()
        panel.pump()
        assert not card.chosen and all(button.isEnabled() for button in card.choices)


def test_expanded_feed_text_wraps_inside_the_live_card_and_scrolls_without_a_hidden_gutter() -> None:
    with notifications(animated=True) as panel:
        item = Assessment(
            "wrap-test",
            (),
            "Review budget",
            ("Compare **the updated forecast** and `FY27` figures before preparing a reply. Reference: " + "budget_forecast_" * 12 + ".xlsx\n\n")
            * 15,
            "Compare the figures and prepare a recommendation.",
            "",
            1,
            1,
        )
        panel.agent.triage(Board(enabled=True, items=(item,)))
        panel.pump()
        panel.advance(0.3)
        card = next(card for card in panel.view.cards.values() if isinstance(card.content, WorkItem))
        view = card.text
        for _ in range(2):
            click_bubble(card)
            panel.pump()
            assert card.text.isHidden() or card.text.document().textWidth() <= card.text.viewport().width() + 1
            for _ in range(20):
                panel.now += 0.016
                panel.view.tick()
                panel.pump()
                view = card.text
                if view.isHidden():
                    continue
                assert view.x() + view.width() <= card.window.width() - 12
                assert view.document().textWidth() <= view.viewport().width() + 1
                assert view.viewport().width() == view.width()
                assert not view.verticalScrollBar().isVisible()
                block = view.document().begin()
                while block.isValid():
                    layout = block.layout()
                    for index in range(layout.lineCount()):
                        line = layout.lineAt(index)
                        assert line.x() + line.naturalTextWidth() <= view.viewport().width() + 1
                    block = block.next()
            if bool(card.expanded):
                assert view.verticalScrollBar().maximum() > 0 and view.offset == 0
                view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
                panel.pump()
                assert view.offset > 0 and view.document().textWidth() <= view.viewport().width() + 1
        assert not bool(card.expanded) and card.label.text() == item.title and card.text.offset == 0


def test_feed_controls_are_inside_the_painted_bubble() -> None:

    with notifications() as panel:
        item = Assessment("inside", (), "Review the budget", "Compare the figures.", "Prepare a recommendation.", "", 1, 1)
        longer = replace(item, identity="longer", title="Confirm the revised forecast and discuss the next steps with the project team")
        panel.agent.triage(Board(enabled=True, items=(item, longer)))
        panel.pump()
        cards = [card for card in panel.view.cards.values() if isinstance(card.content, WorkItem) and not card.retiring]
        assert len(cards) == 2 and cards[0].width == cards[1].width
        for card in cards:
            outline = QPainterPath()
            outline.addRoundedRect(QRectF(8, 8, card.window.width() - 8, card.window.height() - 8), 26, 26)
            for button in (card.dismiss,):
                assert outline.contains(QRectF(button.geometry())), (button.accessibleName(), button.geometry())
        assert abs(widget_rect(cards[0].dismiss).left - widget_rect(cards[1].dismiss).left) <= 1


def test_collapsed_feed_titles_keep_one_line_and_elide_long_text() -> None:
    with notifications() as panel:
        for length in (36, 64, 96, 128, 160):
            title = ("Confirm the revised forecast and discuss next steps with the project team. " * 3)[:length]
            item = Assessment(
                "title-fit",
                (),
                title,
                "A fictional review.",
                "Compare the figures.",
                "",
                1,
                1,
                solutions=(
                    Solution("1", "Draft response", SolutionKind.DRAFT, "Prepare a response."),
                    Solution("2", "Check details", SolutionKind.CHECK, "Check the figures."),
                ),
            )
            panel.agent.triage(Board(enabled=True, items=(item,)))
            panel.pump()
            card = next(card for card in panel.view.cards.values() if isinstance(card.content, WorkItem))
            assert card.label.height() >= card.label.heightForWidth(card.label.width()), (length, card.label.size())
            assert card.text.isVisible() and card.text.toPlainText() == item.suggestion


def test_crowded_feed_keeps_fixed_height_title_rows() -> None:
    with notifications() as panel:
        items = tuple(
            Assessment(
                str(index),
                (),
                ("Confirm the revised forecast and discuss next steps with the project team. " * 3)[:160],
                "A fictional review.",
                "Prepare a recommendation.",
                "",
                1,
                index + 1,
            )
            for index in range(3)
        )
        panel.desktop.bounds = Rect(0, 0, 420, 400)
        panel.agent.triage(Board(enabled=True, items=items))
        panel.pump()
        cards = [card for card in panel.view.cards.values() if isinstance(card.content, WorkItem) and not card.retiring]
        assert cards
        for card in cards:
            assert card.label.height() >= card.label.heightForWidth(card.label.width())
            assert card.text.isVisible() and card.text.toPlainText() == "Prepare a recommendation."


def test_production_theme_does_not_shrink_or_scroll_collapsed_feed_titles() -> None:
    with notifications() as panel:
        previous_style = panel.root.styleSheet()
        try:
            panel.root.setStyleSheet(CONTROL_STYLE)
            item = Assessment("styled-title", (), "Review the forecast", "A fictional review.", "Prepare a recommendation.", "", 1, 1)
            panel.agent.triage(Board(enabled=True, items=(item,)))
            panel.pump()
            panel.pump()
            card = next(card for card in panel.view.cards.values() if isinstance(card.content, WorkItem))
            view = card.text
            assert card.label.height() >= card.label.heightForWidth(card.label.width())
            assert card.label.font().pointSizeF() == 13
            card.toggle(animate=False)
            panel.pump()
            assert view.viewport().size() == view.size(), (view.viewport().size(), view.size())
            assert view.document().size().height() <= view.viewport().height() + 1
            assert view.verticalScrollBar().maximum() == 0 and view.offset == 0
        finally:
            panel.root.setStyleSheet(previous_style)
            panel.pump()


def test_feed_titles_elide_without_growing_and_clicking_the_bubble_expands_details() -> None:
    with notifications() as panel:
        short = Assessment("short", (), "Review the budget", "Check the figures.", "Prepare a draft.", "", 1, 1)
        long = replace(short, identity="long", title="Confirm the revised forecast and discuss next steps with the project team before Friday")
        panel.agent.triage(Board(enabled=True, items=(short, long)))
        panel.pump()
        cards = [card for card in panel.view.cards.values() if isinstance(card.content, WorkItem)]
        assert len(cards) == 2 and cards[0].width == cards[1].width and cards[0].height == cards[1].height
        card = next(card for card in cards if isinstance(card.content, WorkItem) and card.content.item == long)
        assert card.label.font().pointSizeF() == TITLE_SIZE and card.label.display_text().endswith("…")
        assert card.label.display_text() != long.title and long.title in card.label.toolTip()
        assert card.disclosure.isHidden() and card.label.geometry().right() < card.dismiss.x()
        collapsed = card.height
        click_bubble(card)
        panel.pump()
        assert bool(card.expanded) and card.height > collapsed and "Check the figures." in card.text.toPlainText()
        click_bubble(card)
        panel.pump()
        assert not bool(card.expanded) and card.height == collapsed


def card_y(card: Card) -> float:
    return card.y
