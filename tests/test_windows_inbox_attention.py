"""Native bell interaction and inbox publication, without changing the shared shell."""

import sys
import unittest
from collections.abc import Callable
from pathlib import Path

import assistant.console_requests
import assistant.icons

if sys.platform != "win32":
    raise unittest.SkipTest("Windows toolbar inbox attention")

lazy from PySide6 import QtCore, QtWidgets

from assistant.agent_session import Question
from assistant.agent_toasts import AgentToasts
from assistant.agent_window import AgentWindow
from assistant.communications import Feed
from assistant.console_requests import Provider, Request
from assistant.desktop_bar import BarActions, DesktopBar
from assistant.feed_triage import Assessment, Board
from assistant.qt_runtime import prepare
from assistant.qt_ui import application
from assistant.system_notices import Notice, NoticeKey, Observed
from assistant.ui import Ui
from assistant.work_canvas_window import CanvasWindow
from tests.test_work_canvas import local_canvas

prepare()


class InboxUi(Ui):
    __slots__ = ("current_feed",)

    def __init__(self, *, dismiss_notice: Callable[[NoticeKey], None] | None = None) -> None:
        self.current_feed: AgentToasts | None = None
        super().__init__(desktop_factory=isolated_bar, feed_factory=self.create_feed, dismiss_notice=dismiss_notice or (lambda _: None))

    def create_feed(self, root: QtWidgets.QApplication, agent: AgentWindow) -> AgentToasts:
        self.current_feed = AgentToasts(root, agent)
        return self.current_feed

    @property
    def communications(self) -> Feed:
        return self._communication_feed

    @property
    def root(self) -> QtWidgets.QApplication:
        return self._root

    def pump(self) -> None:
        self._poll(self._root)
        self._root.processEvents()

    @property
    def bar(self) -> DesktopBar:
        assert self._desktop is not None
        return self._desktop

    @property
    def panel(self) -> AgentWindow:
        assert self._agent is not None
        return self._agent

    @property
    def feed(self) -> AgentToasts:
        assert self.current_feed is not None
        return self.current_feed

    @property
    def canvas_view(self) -> CanvasWindow:
        assert self._work_view is not None
        return self._work_view

    def dispose(self) -> None:
        self._poll_timer.stop()
        self._close_views()
        self.pump()


def isolated_bar(actions: BarActions, *, audio_level: Callable[[], float | None] | None = None) -> DesktopBar:
    return DesktopBar(actions, native_shell=False, audio_level=audio_level)


def accept_answer(answer: str) -> bool:
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
        ui.console_changed(
            (
                Request(
                    "console",
                    Provider.CODEX,
                    "session",
                    "C:/fictional",
                    "Choose a sheet",
                    "",
                    (assistant.console_requests.Question("Which sheet?"),),
                    2,
                ),
            )
        )
        ui.triage_changed(Board(enabled=True, items=(Assessment("budget", (), "Review budget", "", "", "", 1, 4),)))
        ui.pump()
        assert ui.bar.inbox.isHidden()
        agent = ui.agent(None, lambda: None, reveal=False)
        agent.request_input(Question("owned", "Which sheet?", "", 3), accept_answer)
        ui.pump()
        assert not ui.bar.inbox.text() and not ui.bar.inbox.isHidden()
        assert "1 clarification needs" in ui.bar.inbox.accessibleName()
        assert agent.respond("owned", "Revenue")
        ui.pump()
        assert ui.bar.inbox.isHidden()
    finally:
        ui.dispose()
        app.setStyleSheet(original_style)
