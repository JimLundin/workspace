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

import desktop_ui.island_moment
from assistant.canvas_activity import SessionRequest
from assistant.communications import WindowsNotice
from assistant.feed_origin import FeedRequest
from assistant.feed_sources import PendingFeed
from assistant.notification_sources import NOTIFICATION_STATE
from assistant.state_store import SavedState
from assistant.work_canvas_contracts import CanvasEdits
from automation.task import TextAnswer
from desktop_ui.desktop_bar import BarActions, BarObservations, DesktopBar
from desktop_ui.island_model import Agent, Job, Key
from desktop_ui.island_motion import settled
from desktop_ui.island_surface import Capsule
from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import application
from desktop_ui.ui import Ui, Views
from desktop_ui.ui_spec import sizes
from desktop_ui.work_canvas_window import CanvasWindow
from desktop_ui.work_window import WorkWindow
from tests.agent_requests import asked
from tests.communications_fixture import communication_feed
from tests.test_communications_service import LocalCipher
from tests.test_work_canvas import local_canvas
from winapi.system_notices import Notice, NoticeKey, Observed

TOP = round(sizes().bar.top)

prepare()


class InboxUi(Ui):
    """The production Ui with isolated views; it keeps the views Ui built and reads nothing private."""

    __slots__ = ("current_bar", "current_canvas")

    def __init__(self) -> None:
        self.current_bar: DesktopBar | None = None
        self.current_canvas: CanvasWindow | None = None
        super().__init__(views=Views(self.create_bar, self.create_canvas))

    def create_bar(self, actions: BarActions, *, audio_level: Callable[[], float | None] | None = None) -> DesktopBar:
        self.current_bar = DesktopBar(actions, native_shell=False, audio_level=audio_level)
        return self.current_bar

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


def accept_answer(answer: TextAnswer) -> bool:
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
        lambda: None,
        lambda: invoke("stop"),
        lambda _: None,
        lambda: None,
        lambda: None,
        lambda: invoke("menu"),
        lambda _: None,
        inbox=lambda: invoke("inbox"),
        open_item=lambda _: None,
    )
    bar = DesktopBar(actions, native_shell=False)
    try:
        assert waiting(bar) is None
        bar.inbox_changed(1)
        capsule = waiting(bar)
        assert capsule is not None and "1 clarification needs" in capsule.accessibleName() and "Hold X + M" in capsule.toolTip()
        QTest.mouseClick(capsule, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(17, TOP + 17))
        assert invoked == ("inbox",) and bar.opened is None
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
    # Defects: routine app/feed arrivals still count as user attention, the
    # question count depends on a view already being created, or an empty inbox
    # request goes nowhere before the bar exists.
    app, original_style = application(), application().styleSheet()
    ui = InboxUi()
    opened: tuple[str, ...] = ()

    def show_canvas() -> None:
        nonlocal opened
        opened = (*opened, "canvas")

    try:
        agent = ui.agent(lambda: None, reveal=False, on_work=show_canvas)
        ui.open_inbox()
        ui.pump()
        assert opened == ("canvas",)
        store = local_canvas(tmp_path, ui.publish_canvas)
        ui.configure_canvas(store, lambda _title, _target: None, observe_session=store.observe_session)
        ui.desktop(show_work=lambda: None, stop=lambda: None, overlay=lambda: None, menu=lambda: None, on_problem=lambda _: None)
        ui.system_notices(Observed((Notice(NoticeKey(11, 100), "mail", "Outlook", "Review", "Budget review"),)))
        ui.pump()
        assert waiting(ui.bar) is None
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
    # Defect: the production Ui announces app observations on the desktop, or
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
        assert agent.snapshot().messages == ()
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
    answers: list[TextAnswer] = []
    fallback: list[str] = []

    def accept(reply: TextAnswer) -> bool:
        answers.append(reply)
        return True

    try:
        store = local_canvas(tmp_path, ui.publish_canvas)
        ui.configure_canvas(store, lambda _title, _target: None, observe_session=store.observe_session)
        ui.configure_work(lambda _command: None)
        ui.desktop(show_work=lambda: None, stop=lambda: None, overlay=lambda: None, menu=lambda: None, on_problem=lambda _: None)
        agent = ui.agent(lambda: None, reveal=False, on_work=lambda: ui.work_window().show())
        agent.request_input(asked("inline", "Which sheet should I use?", "Revenue contains the approved supplier figures.", 3), accept)
        ui.pump()
        assert ui.current_canvas is None
        ui.bar.visible = True
        ui.bar.render()
        ui.open_inbox()
        ui.pump()
        settle_toolbar(ui)
        capsule = ui.bar.window.capsules[Key.ISLAND]
        panel = capsule.request
        assert panel is not None and panel.isVisible() and panel.isEnabled()
        assert panel.question.text() == "Which sheet should I use?"
        assert panel.body.toPlainText() == "Revenue contains the approved supplier figures."
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


def test_an_open_request_follows_its_phase_and_reply_owner_when_work_asks_again(tmp_path: Path) -> None:
    # Defect: a continuation asks in the same work context but the open request
    # keeps the resolved question, so voice answers it instead of the new one.
    ui = InboxUi()
    original_style = application().styleSheet()
    answers: list[TextAnswer] = []

    def accept(reply: TextAnswer) -> bool:
        answers.append(reply)
        return True

    try:
        agent = ui.agent(lambda: None, reveal=False)
        store = local_canvas(tmp_path, ui.publish_canvas)
        ui.configure_canvas(store, agent.notify_canvas, observe_session=store.observe_session)
        ui.desktop(show_work=lambda: None, stop=lambda: None, overlay=lambda: None, menu=lambda: None, on_problem=lambda _: None)
        agent.begin("Review budget", source=FeedRequest("source:budget", "Budget notice"))
        agent.request_input(asked("figures", "Which figures?", "Actual or forecast?", 3), accept)
        ui.pump()
        ui.open_inbox()
        ui.pump()
        ui.voice_agent("Actual", lambda _text: None)
        ui.pump()
        agent.request_input(asked("deadline", "Which deadline?", "Monday or Friday?", 4), accept)
        ui.pump()
        panel = ui.bar.window.capsules[Key.ISLAND].request
        assert panel is not None and panel.question.text() == "Which deadline?" and ui.current_canvas is None
        ui.voice_agent("Monday", lambda _text: None)
        ui.pump()
        assert answers == [TextAnswer("Actual"), TextAnswer("Monday")]
    finally:
        ui.dispose()
        application().setStyleSheet(original_style)


def test_a_finished_reply_takes_the_island_then_waits_in_the_bell_and_opens_its_canvas_item(tmp_path: Path) -> None:
    # Defects: a finished reply never reaches the bar, stays on the island, isn't
    # counted once it collapses, or the bell's list doesn't open its canvas item.
    now = [100.0]
    opened: list[str] = []
    actions = BarActions(
        lambda: None,
        lambda: None,
        lambda _: None,
        lambda: None,
        lambda: None,
        lambda: None,
        lambda _: None,
        inbox=lambda: None,
        open_item=opened.append,
    )
    bar = DesktopBar(actions, native_shell=False, observations=BarObservations(clock=lambda: now[0], motion=lambda: False))
    try:
        bar.visible = True
        reply = desktop_ui.island_moment.Notice(
            "reply:s:1", "Compare the budget sheets", "Revenue is up four percent on the approved figures.", "reply:s:1", 5
        )
        bar.notices_changed((reply,))
        island = bar.window.capsules[Key.ISLAND]
        assert island.isVisible() and island.accessibleName().startswith("Compare the budget sheets: Revenue is up")
        assert island.height() > TOP + 34 and waiting(bar) is None
        island.grab().save(str(tmp_path / "workspace-island-notice.png"))
        now[0] += 7
        bar.render()
        bell = waiting(bar)
        assert bell is not None and bell.accessibleName().startswith("1 new from the agent")
        assert bar.open_inbox(())
        panel = bar.window.capsules[Key.ISLAND].inbox
        assert panel is not None and [row.accessibleName() for row in panel.rows] == [
            "Compare the budget sheets: Revenue is up four percent on the approved figures."
        ]
        QTest.mouseClick(panel.rows[0], QtCore.Qt.MouseButton.LeftButton)
        assert opened == ["reply:s:1"] and bar.opened is None and waiting(bar) is None
    finally:
        bar.close()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        application().processEvents()
