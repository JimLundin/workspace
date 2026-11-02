"""Native bell interaction and inbox publication, without changing the shared shell."""

import sys
import time
import unittest
from collections.abc import Callable
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows toolbar inbox attention")

lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtTest import QTest

from assistant.canvas_activity import SessionRequest
from assistant.communications import WindowsNotice
from assistant.feed_origin import FeedRequest
from assistant.feed_sources import PendingFeed
from assistant.notification_sources import NOTIFICATION_STATE
from assistant.state_store import SavedState
from assistant.work_canvas_contracts import CanvasEdits
from automation.task import ApprovalDecision, Reply, TextAnswer
from desktop_ui.agent_toasts import AgentToasts
from desktop_ui.agent_window import AgentWindow
from desktop_ui.desktop_bar import BarActions, DesktopBar
from desktop_ui.island_model import Agent, Job, Key
from desktop_ui.island_motion import settled
from desktop_ui.island_surface import TOP, Capsule
from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import application
from desktop_ui.ui import Ui, Views
from desktop_ui.work_canvas_window import CanvasWindow
from desktop_ui.work_window import WorkWindow
from tests.agent_requests import asked, reviewed
from tests.communications_fixture import communication_feed
from tests.test_communications_service import LocalCipher
from tests.test_work_canvas import local_canvas
from winapi.system_notices import Notice, NoticeKey, Observed

prepare()


class InboxUi(Ui):
    """The production Ui with isolated views; it keeps the views Ui built and reads nothing private."""

    __slots__ = ("current_bar", "current_canvas", "current_feed")

    def __init__(self) -> None:
        self.current_bar: DesktopBar | None = None
        self.current_canvas: CanvasWindow | None = None
        self.current_feed: AgentToasts | None = None
        super().__init__(views=Views(self.create_bar, self.create_feed, self.create_canvas))

    def create_bar(self, actions: BarActions, *, audio_level: Callable[[], float | None] | None = None) -> DesktopBar:
        self.current_bar = DesktopBar(actions, native_shell=False, audio_level=audio_level)
        return self.current_bar

    def create_feed(self, root: QtWidgets.QApplication, agent: AgentWindow, open_canvas: Callable[[str], None]) -> AgentToasts:
        self.current_feed = AgentToasts(root, agent, open_canvas)
        return self.current_feed

    def create_canvas(self, root: QtWidgets.QApplication, work: WorkWindow, canvas: CanvasEdits) -> CanvasWindow:
        self.current_canvas = CanvasWindow(root, work, canvas)
        return self.current_canvas

    @property
    def root(self) -> QtWidgets.QApplication:
        return application()

    def pump(self) -> None:
        # Ui yields queued work between frames. This fixture waits across those
        # turns before assertions that require every queued publication to land.
        deadline = time.monotonic() + 4
        self.drain()
        application().processEvents()
        while not self._jobs.empty() and time.monotonic() < deadline:
            self.drain()
            application().processEvents()
        assert self._jobs.empty(), "Queued UI publications did not settle."

    @property
    def bar(self) -> DesktopBar:
        assert self.current_bar is not None
        return self.current_bar

    @property
    def feed(self) -> AgentToasts:
        assert self.current_feed is not None
        return self.current_feed

    @property
    def canvas_view(self) -> CanvasWindow:
        assert self.current_canvas is not None
        return self.current_canvas

    def dispose(self) -> None:
        self.close_views()
        self.pump()


def waiting(bar: DesktopBar) -> Capsule | None:
    """The inbox capsule while it is shown."""
    capsule = bar.window.capsules.get(Key.INBOX)
    return capsule if capsule is not None and capsule.isVisibleTo(bar.window) else None


def accept_answer(answer: Reply) -> bool:
    return True


def settle_toolbar(ui: InboxUi) -> None:
    deadline = time.monotonic() + 5
    while not settled(ui.bar.motion) and time.monotonic() < deadline:
        QTest.qWait(20)
        ui.pump()
    assert settled(ui.bar.motion), "The toolbar transition did not settle."


def test_bell_opens_inbox_keeps_exact_accessible_count_and_survives_activity(tmp_path: Path) -> None:
    app = application()
    invoked: tuple[str, ...] = ()

    def invoke(action: str) -> None:
        nonlocal invoked
        invoked = (*invoked, action)

    actions = BarActions(
        lambda: invoke("conversation"),
        lambda: None,
        lambda: invoke("stop"),
        lambda _: None,
        lambda: None,
        lambda: None,
        lambda: invoke("menu"),
        lambda _: None,
        inbox=lambda: invoke("inbox"),
    )
    bar = DesktopBar(actions, native_shell=False)
    try:
        assert waiting(bar) is None
        bar.inbox_changed(1)
        capsule = waiting(bar)
        assert capsule is not None and "1 clarification needs" in capsule.accessibleName() and "Hold V + T" in capsule.toolTip()
        QTest.mouseClick(capsule, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(17, TOP + 17))
        assert invoked == ("inbox",) and bar.expanded is None
        starts: tuple[Callable[[], None], ...] = (
            lambda: bar.agent_changed(Agent("Comparing both sheets", waiting=False)),
            lambda: bar.dictation(active=True),
            lambda: bar.job_changed(Job.TRANSCRIBING),
        )
        for start in starts:
            start()
            assert waiting(bar) is capsule
        bar.dictation(active=False)
        bar.job_changed(None)
        bar.agent_changed(None)
        bar.inbox_changed(137)
        assert "137 clarifications need" in capsule.accessibleName()
        capsule.grab().save(str(tmp_path / "workspace-island-inbox.png"))
        bar.inbox_changed(0)
        assert waiting(bar) is None
        bar.close()
        # A late publication must return safely after native widgets are destroyed.
        bar.inbox_changed(1)
    finally:
        bar.close()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        app.processEvents()


def test_app_context_stays_quiet_and_only_agent_questions_change_toolbar_attention(tmp_path: Path) -> None:
    # Defect: routine app/feed arrivals still count as user attention, or the
    # question count depends on a floating view already being created.
    app, original_style = application(), application().styleSheet()
    ui = InboxUi()
    conversations: tuple[str, ...] = ()

    def show_conversation() -> None:
        nonlocal conversations
        conversations = (*conversations, "shown")

    try:
        # Defect: inbox navigation loses the configured conversation callback
        # before either canvas or agent view is created.
        ui.configure_controls(on_agent_waiting=lambda _: None, on_recording=lambda _: None, on_show_agent=show_conversation)
        ui.open_inbox()
        ui.pump()
        assert conversations == ("shown",)
        store = local_canvas(tmp_path, ui.publish_canvas)
        ui.configure_canvas(store, lambda _title, _target: None, observe_session=store.observe_session)
        ui.desktop(
            show_agent=lambda: None, show_work=lambda: None, stop=lambda: None, overlay=lambda: None, menu=lambda: None, on_problem=lambda _: None
        )
        ui.system_notices(Observed((Notice(NoticeKey(11, 100), "mail", "Outlook", "Review", "Budget review"),)))
        ui.pump()
        assert waiting(ui.bar) is None
        agent = ui.agent(lambda: None, reveal=False)
        agent.request_input(asked("owned", "Which sheet?", "", 3), accept_answer)
        ui.pump()
        capsule = waiting(ui.bar)
        assert capsule is not None and "1 clarification needs" in capsule.accessibleName()
        assert ui.answer_canvas(SessionRequest(agent.snapshot().identity, "owned"), "Revenue")
        ui.pump()
        assert waiting(ui.bar) is None
    finally:
        ui.dispose()
        app.setStyleSheet(original_style)


def test_app_arrivals_reach_triage_joined_without_floating_alerts(tmp_path: Path) -> None:
    # Defect: the production Ui turns app observations into floating cards, or
    # triage sees Teams work without the Windows notices it must assess.
    original_style = application().styleSheet()
    assessed: list[PendingFeed] = []
    ui = InboxUi()
    ui.configure_feed(
        SavedState(tmp_path / "notifications.bin", NOTIFICATION_STATE, cipher=LocalCipher()),
        assessed.append,
    )
    try:
        agent = ui.agent(lambda: None, reveal=False)
        agent.show(focus=False)
        ui.pump()
        notice = Notice(NoticeKey(11, 100), "owned", "Mail", "Review this", "Immediate fictional notice")
        ui.system_notices(Observed((notice,)))
        ui.communications_changed(communication_feed())
        ui.pump()
        assert not ui.feed.stack.toasts and not ui.feed.cards
        assert assessed[-1].teams.messages
        assert any(item.source == WindowsNotice(notice.key, notice.app_id) for item in assessed[-1].notices.updates)
    finally:
        ui.dispose()
        ui.root.setStyleSheet(original_style)


def test_toolbar_request_expands_in_place_routes_voice_and_opens_canvas_only_from_icon(tmp_path: Path) -> None:
    # Defect: the attention click navigates away, clips the request, or sends a
    # spoken reply to the conversation rather than its exact waiting owner.
    ui = InboxUi()
    original_style = application().styleSheet()
    answers: list[Reply] = []
    fallback: list[str] = []

    def accept(reply: Reply) -> bool:
        answers.append(reply)
        return True

    try:
        store = local_canvas(tmp_path, ui.publish_canvas)
        ui.configure_canvas(store, lambda _title, _target: None, observe_session=store.observe_session)
        ui.configure_work(lambda _command: None)
        ui.desktop(
            show_agent=lambda: None, show_work=lambda: None, stop=lambda: None, overlay=lambda: None, menu=lambda: None, on_problem=lambda _: None
        )
        agent = ui.agent(lambda: None, reveal=False, on_work=lambda: ui.work_window().show())
        agent.request_input(asked("inline", "Which sheet should I use?", "Revenue contains the approved supplier figures.", 3), accept)
        ui.pump()
        card = next(iter(ui.feed.cards.values()))
        assert (card.expanded, "Revenue contains" in card.text.toPlainText()) == (False, False)
        ui.feed.toggle_card(card, animate=False)
        ui.pump()
        assert card.expanded and "Revenue contains the approved supplier figures" in card.text.toPlainText()
        assert ui.current_canvas is None
        ui.bar.visible = True
        ui.bar.render()
        ui.open_inbox()
        ui.pump()
        settle_toolbar(ui)
        capsule = ui.bar.window.capsules[Key.ISLAND]
        panel = capsule.request
        assert panel is not None and panel.isVisible() and panel.isEnabled()
        assert "Revenue contains the approved supplier figures" in panel.body.toPlainText()
        assert ui.current_canvas is None, "Reviewing a request must not create or open the canvas."
        capsule.grab().save(str(tmp_path / "workspace-inline-request.png"))
        QTest.mouseClick(panel.canvas, QtCore.Qt.MouseButton.LeftButton)
        ui.pump()
        assert ui.canvas_view.panel.selected == "question:inline"
        ui.canvas_view.hide()
        ui.open_inbox()
        ui.pump()
        ui.voice_agent("Revenue", fallback.append)
        ui.pump()
        assert answers == [TextAnswer("Revenue")] and not fallback
        settle_toolbar(ui)
        assert waiting(ui.bar) is None
    finally:
        ui.dispose()
        application().setStyleSheet(original_style)


def test_toolbar_approval_presents_exact_review_and_decides_without_canvas() -> None:
    # Defect: the expanded toolbar omits the exact operation, never acknowledges
    # its presentation, or routes its approval button to another request owner.
    ui = InboxUi()
    original_style = application().styleSheet()
    decisions: list[Reply] = []

    def decide(reply: Reply) -> bool:
        decisions.append(reply)
        return True

    try:
        ui.desktop(
            show_agent=lambda: None, show_work=lambda: None, stop=lambda: None, overlay=lambda: None, menu=lambda: None, on_problem=lambda _: None
        )
        agent = ui.agent(lambda: None, reveal=False)
        agent.request_input(reviewed("write", "Save approved figures?", "Write the approved totals to C:/Budget/approved.xlsx", 3), decide)
        ui.pump()
        ui.bar.visible = True
        ui.bar.render()
        ui.open_inbox()
        ui.pump()
        settle_toolbar(ui)
        panel = ui.bar.window.capsules[Key.ISLAND].request
        assert panel is not None and panel.isVisible() and panel.isEnabled()
        assert "C:/Budget/approved.xlsx" in panel.body.toPlainText()
        assert [button.text() for _, button in panel.options] == ["Approve", "Decline"]
        assert ui.current_canvas is None
        QTest.mouseClick(panel.options[0][1], QtCore.Qt.MouseButton.LeftButton)
        ui.pump()
        assert decisions == [ApprovalDecision.APPROVED] and not agent.snapshot().waiting
    finally:
        ui.dispose()
        application().setStyleSheet(original_style)


def test_expanded_notification_keeps_its_card_and_reply_owner_when_work_asks_again(tmp_path: Path) -> None:
    # Defect: a continuation asks in the existing expanded card but voice still
    # targets the resolved request, or the continuation creates another card.
    ui = InboxUi()
    original_style = application().styleSheet()
    answers: list[Reply] = []

    def accept(reply: Reply) -> bool:
        answers.append(reply)
        return True

    try:
        agent = ui.agent(lambda: None, reveal=False)
        store = local_canvas(tmp_path, ui.publish_canvas)
        ui.configure_canvas(store, agent.notify_canvas, observe_session=store.observe_session)
        agent.begin("Review budget", source=FeedRequest("source:budget", "Budget notice"))
        agent.request_input(asked("figures", "Which figures?", "Approved or forecast?", 3), accept)
        ui.pump()
        card = next(iter(ui.feed.cards.values()))
        ui.feed.toggle_card(card, animate=False)
        ui.voice_agent("Approved", lambda _text: None)
        ui.pump()
        agent.request_input(asked("deadline", "Which deadline?", "Monday or Friday?", 4), accept)
        ui.pump()
        assert tuple(ui.feed.cards.values()) == (card,) and card.expanded
        assert "Monday or Friday" in card.text.toPlainText() and ui.current_canvas is None
        ui.voice_agent("Monday", lambda _text: None)
        ui.pump()
        assert answers == [TextAnswer("Approved"), TextAnswer("Monday")]
    finally:
        ui.dispose()
        application().setStyleSheet(original_style)
