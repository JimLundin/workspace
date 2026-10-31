"""Native bell interaction and inbox publication, without changing the shared shell."""

import sys
import unittest
from collections.abc import Callable
from pathlib import Path

import assistant.icons

if sys.platform != "win32":
    raise unittest.SkipTest("Windows toolbar inbox attention")

lazy from PySide6 import QtCore, QtWidgets

from assistant.agent_toasts import AgentToasts
from assistant.agent_window import AgentWindow
from assistant.communications import Feed, WindowsNotice
from assistant.desktop_bar import BarActions, DesktopBar
from assistant.notification_sources import NOTIFICATION_STATE
from assistant.qt_runtime import prepare
from assistant.qt_ui import application
from assistant.state_store import SavedState
from assistant.system_notices import Notice, NoticeKey, Observed
from assistant.ui import Ui, Views
from assistant.work_canvas import WorkCanvas
from assistant.work_canvas_window import CanvasWindow
from assistant.work_window import WorkWindow
from automation.task import Reply, TextAnswer
from tests.agent_requests import asked
from tests.communications_fixture import communication_feed
from tests.test_communications_service import LocalCipher
from tests.test_work_canvas import local_canvas

prepare()


class InboxUi(Ui):
    """The production Ui with isolated views; it keeps the views Ui built and reads nothing private."""

    __slots__ = ("current_bar", "current_canvas", "current_feed")

    def __init__(self, *, dismiss_notice: Callable[[NoticeKey], None] | None = None) -> None:
        self.current_bar: DesktopBar | None = None
        self.current_canvas: CanvasWindow | None = None
        self.current_feed: AgentToasts | None = None
        super().__init__(views=Views(self.create_bar, self.create_feed, self.create_canvas), dismiss_notice=dismiss_notice or (lambda _: None))

    def create_bar(self, actions: BarActions, *, audio_level: Callable[[], float | None] | None = None) -> DesktopBar:
        self.current_bar = DesktopBar(actions, native_shell=False, audio_level=audio_level)
        return self.current_bar

    def create_feed(self, root: QtWidgets.QApplication, agent: AgentWindow, open_canvas: Callable[[str], None]) -> AgentToasts:
        self.current_feed = AgentToasts(root, agent, open_canvas)
        return self.current_feed

    def create_canvas(self, root: QtWidgets.QApplication, work: WorkWindow, canvas: WorkCanvas) -> CanvasWindow:
        self.current_canvas = CanvasWindow(root, work, canvas)
        return self.current_canvas

    @property
    def root(self) -> QtWidgets.QApplication:
        return application()

    def pump(self) -> None:
        self.drain()
        application().processEvents()

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


def accept_answer(answer: Reply) -> bool:
    return True


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
        # Exercise the rendered toolbar while keeping native observers disabled.
        # Hidden Qt windows defer resize layout when activity removes the Stop button.
        bar.visible = True
        bar.render(animate=False)
        width = bar.window.width()
        assert bar.inbox.isHidden()
        bar.inbox_changed(1)
        assert not bar.inbox.isHidden() and not bar.inbox.text()
        assert "1 clarification needs" in bar.inbox.accessibleName()
        assert "Hold V + T" in bar.inbox.toolTip()
        assert bar.window.width() > width
        bar.inbox.click()
        assert invoked == ("inbox",) and not bar.menu.isVisible()
        for state in (assistant.icons.State.AGENT, assistant.icons.State.LISTENING, assistant.icons.State.WORKING):
            bar.state(state)
            assert not bar.inbox.isHidden()
            assert bar.inbox.geometry().right() < bar.window.width()
        bar.state(assistant.icons.State.READY)
        bar.inbox_changed(137)
        assert not bar.inbox.text() and "137 clarifications need" in bar.inbox.toolTip()
        assert "137 clarifications need" in bar.inbox.accessibleName()
        bar.window.grab().save(str(tmp_path / "workspace-toolbar-bell.png"))
        bar.inbox_changed(0)
        assert bar.inbox.isHidden() and bar.window.width() == width
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
    try:
        ui.configure_canvas(local_canvas(tmp_path), lambda _title, _target: None)
        ui.desktop(
            show_agent=lambda: None, show_work=lambda: None, stop=lambda: None, overlay=lambda: None, menu=lambda: None, on_problem=lambda _: None
        )
        ui.system_notices(Observed((Notice(NoticeKey(11, 100), "mail", "Outlook", "Review", "Budget review"),)))
        ui.pump()
        assert ui.bar.inbox.isHidden()
        agent = ui.agent(lambda: None, reveal=False)
        agent.request_input(asked("owned", "Which sheet?", "", 3), accept_answer)
        ui.pump()
        assert not ui.bar.inbox.text() and not ui.bar.inbox.isHidden()
        assert "1 clarification needs" in ui.bar.inbox.accessibleName()
        assert agent.respond("owned", TextAnswer("Revenue"))
        ui.pump()
        assert ui.bar.inbox.isHidden()
    finally:
        ui.dispose()
        app.setStyleSheet(original_style)


def test_app_arrivals_reach_triage_joined_without_floating_alerts(tmp_path: Path) -> None:
    # Defect: the production Ui turns app observations into floating cards, or
    # triage sees Teams work without the Windows notices it must assess.
    original_style = application().styleSheet()
    assessed: list[Feed] = []
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
        assert assessed[-1].messages
        assert any(item.source == WindowsNotice(notice.key, notice.app_id) for item in assessed[-1].updates)
    finally:
        ui.dispose()
        ui.root.setStyleSheet(original_style)
