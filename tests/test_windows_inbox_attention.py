"""Native bell interaction and inbox publication, without changing the shared shell."""

import sys
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import assistant.console_requests
import assistant.icons

if sys.platform != 'win32':
    raise unittest.SkipTest('Windows toolbar inbox attention')

lazy from PySide6 import QtCore, QtWidgets

from assistant.agent_session import Question
from assistant.agent_toasts import AgentToasts
from assistant.agent_window import AgentWindow
from assistant.communications import Feed, HandleNotice, Update, WindowsNotice
from assistant.console_requests import Provider, Request, State
from assistant.desktop_bar import BarActions, DesktopBar
from assistant.feed_items import SourceKey
from assistant.feed_triage import Assessment, Board, Disposition
from assistant.notifications import TurnKey
from assistant.qt_runtime import prepare
from assistant.qt_ui import application
from assistant.system_notices import Notice, NoticeKey, Observed
from assistant.ui import Ui

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
    actions = BarActions(lambda: invoke('conversation'), lambda: None, lambda: invoke('stop'), lambda _: None,
                         lambda: None, lambda: None, lambda: invoke('menu'), lambda _: None, inbox=lambda: invoke('inbox'))
    bar = DesktopBar(actions, native_shell=False)
    try:
        # Exercise the rendered toolbar while keeping native observers disabled.
        # Hidden Qt windows defer resize layout when activity removes the Stop button.
        bar.visible = True
        bar.render(animate=False)
        width = bar.window.width()
        assert bar.inbox.isHidden()
        bar.inbox_changed(1)
        assert not bar.inbox.isHidden() and bar.inbox.text() == '1'
        assert '1 inbox item needs' in bar.inbox.accessibleName()
        assert 'Hold V + T' in bar.inbox.toolTip()
        assert bar.window.width() > width
        bar.inbox.click()
        assert invoked == ('inbox',) and not bar.menu.isVisible()
        for state in (assistant.icons.State.AGENT, assistant.icons.State.LISTENING, assistant.icons.State.WORKING):
            bar.state(state)
            assert not bar.inbox.isHidden()
            assert bar.inbox.geometry().right() < bar.window.width()
        bar.state(assistant.icons.State.READY)
        bar.inbox_changed(137)
        assert bar.inbox.text() == '99+' and '137 inbox items need' in bar.inbox.toolTip()
        assert '137 inbox items need' in bar.inbox.accessibleName()
        bar.window.grab().save(str(tmp_path / 'workspace-toolbar-bell.png'))
        bar.inbox_changed(0)
        assert bar.inbox.isHidden() and bar.window.width() == width
        bar.close()
        # A late publication must return safely after native widgets are destroyed.
        bar.inbox_changed(1)
    finally:
        bar.close()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        app.processEvents()


def test_inbox_updates_before_view_creation_and_tracks_agent_console_and_curated_resolution() -> None:
    app, original_style = application(), application().styleSheet()
    ui = InboxUi()
    errors: tuple[str, ...] = ()
    def record_problem(problem: str) -> None:
        nonlocal errors
        errors = (*errors, problem)
    ui.configure_communications(lambda _: True)
    def show_agent() -> None:
        ui.agent(None, lambda: None, reveal=False)
    try:
        notice = Notice(NoticeKey(11, 100), 'mail', 'Outlook', 'Review', 'Budget needs review')
        ui.system_notices(Observed((notice,)))
        ui.desktop(show_agent=show_agent, show_work=lambda: None,
                   stop=lambda: None, overlay=lambda: None, menu=lambda: None, on_problem=record_problem)
        ui.pump()
        bar = ui.bar
        assert not errors
        assert bar.inbox.text() == '1' and not bar.inbox.isHidden()
        assert ui.communicate(HandleNotice(notice))
        assert bar.inbox.isHidden()
        ui.communications_changed(Feed(updates=(Update(WindowsNotice(notice.key, notice.app_id), notice.title,
                                                        notice.body, notice.app_name, 1),)), {})
        ui.pump()
        assert bar.inbox.isHidden()  # A late source publication cannot revive the handled notice.
        waiting = Request('console', Provider.CODEX, 'session', 'C:/fictional', 'Choose a sheet', '',
                              (assistant.console_requests.Question('Which sheet?'),), 2)
        ui.console_changed((waiting,))
        ui.pump()
        assert bar.inbox.text() == '1' and not bar.inbox.isHidden()
        bar.inbox.click()
        ui.pump()
        agent = ui.panel
        agent.request_input(Question('owned', 'Which sheet?', '', 3), accept_answer)
        ui.pump()
        assert bar.inbox.text() == '2'
        assert agent.respond('owned', 'Revenue')
        ui.pump()
        assert bar.inbox.text() == '1'
        ui.console_changed((replace(waiting, state=State.ANSWERED),))
        ui.pump()
        assert bar.inbox.isHidden()
        work = Assessment('budget', (('budget-source', 'revision'),), 'Review budget', '', '', '', 1, 4)
        ui.triage_changed(Board(enabled=True, items=(work,)))
        ui.pump()
        assert bar.inbox.text() == '1' and not bar.inbox.isHidden()
        ui.triage_changed(Board(enabled=True, items=(replace(work, disposition=Disposition.DISMISSED),)))
        ui.pump()
        assert bar.inbox.isHidden()
    finally:
        ui.dispose()
        app.setStyleSheet(original_style)


def test_bell_restores_current_feed_and_locally_hidden_unanswered_and_source_bubbles() -> None:
    app, original_style = application(), application().styleSheet()
    ui = InboxUi()
    ui.configure_communications(lambda _: True)
    def show_agent() -> None:
        ui.agent(None, lambda: None, reveal=False)
    try:
        ui.desktop(show_agent=show_agent, show_work=lambda: None, stop=lambda: None,
                   overlay=lambda: None, menu=lambda: None, on_problem=lambda _: None)
        ui.pump()
        # Keyboard access creates the inbox even before there is a visible bell.
        assert ui.bar.inbox.isHidden()
        ui.open_inbox(show_agent)
        ui.pump()
        assert not ui.feed.query.history and ui.feed.page == 0 and not ui.feed.stack.toasts
        update = Update(WindowsNotice(NoticeKey(17, 200), 'mail'), 'Review', 'Check the budget', 'Outlook', 1)
        ui.communications_changed(Feed(updates=(update,)), {})
        ui.pump()
        ui.bar.inbox.click()
        ui.pump()
        ui.panel.request_input(Question('owned', 'Which sheet?', '', 3), accept_answer)
        ui.pump()
        view, source_key = ui.feed, SourceKey(*update.key)
        openers: tuple[Callable[[], None], ...] = (lambda: ui.open_inbox(show_agent), ui.bar.inbox.click)
        for open_inbox in openers:
            view.show_history()
            view.dismiss_card(TurnKey(-1))
            view.dismiss_card(source_key)
            ui.pump()
            assert bool(view.query.history) and not view.stack.toasts
            assert ui.bar.inbox.text() == '2'  # Hiding bubbles does not handle their work.
            view.page = 3
            open_inbox()
            ui.pump()
            assert not bool(view.query.history) and view.page == 0
            assert frozenset(toast.key for toast in view.stack.toasts) == frozenset((TurnKey(-1), source_key))
            question = view.cards[TurnKey(-1)]
            assert question.text.isReadOnly() and "agent voice-to-text button" in question.window.toolTip()
    finally:
        ui.dispose()
        app.setStyleSheet(original_style)
