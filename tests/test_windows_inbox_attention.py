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

from assistant.agent_toasts import AgentToasts
from assistant.agent_window import AgentWindow
from assistant.canvas_activity import SessionRequest
from assistant.communications import WindowsNotice
from assistant.desktop_bar import BarActions, DesktopBar
from assistant.feed_sources import PendingFeed
from assistant.island_model import Agent, Job, Key
from assistant.island_surface import TOP, Capsule
from assistant.notification_sources import NOTIFICATION_STATE
from assistant.qt_runtime import prepare
from assistant.qt_ui import application
from assistant.state_store import SavedState
from assistant.ui import Ui, Views
from assistant.work_canvas_panel import CanvasEdits
from assistant.work_canvas_window import CanvasWindow
from assistant.work_window import WorkWindow
from automation.task import Reply
from tests.agent_requests import asked
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
        ui.configure_canvas(local_canvas(tmp_path, ui.publish_canvas), lambda _title, _target: None)
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
