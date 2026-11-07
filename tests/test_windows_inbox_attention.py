"""Native bell interaction and inbox publication, without changing the shared shell."""

import sys
import time
import unittest
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from cell import Cell

if sys.platform != "win32":
    raise unittest.SkipTest("Windows toolbar inbox attention")

lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtTest import QTest

import desktop_ui.island_moment
from contracts.canvas_activity import SessionRequest
from contracts.feed_origin import FeedRequest
from contracts.status import Job
from contracts.task import TextAnswer
from contracts.work_canvas_contracts import CanvasEdits
from desktop_ui.desktop_bar import BarActions, BarObservations, DesktopBar
from desktop_ui.island_model import Agent, Key
from desktop_ui.island_motion import settled
from desktop_ui.island_surface import Capsule
from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import application
from desktop_ui.spec.sizes import SIZES
from desktop_ui.ui import Ui, Views
from desktop_ui.work_canvas_window import CanvasWindow
from desktop_ui.work_window import WorkWindow
from tests.agent_requests import asked
from tests.desktop_fixture import Unreachable
from tests.local_assistant import LocalAssistant
from winapi.system_notices import Notice, NoticeKey, Observed

TOP = round(SIZES.bar.top)

prepare()


@dataclass(frozen=True, slots=True)
class _Recorded:
    bar: DesktopBar | None = None
    canvas: CanvasWindow | None = None


@dataclass(frozen=True, slots=True)
class InboxUi:
    """The production Ui with isolated views; it keeps the views Ui built and reads nothing private."""

    ui: Ui
    assistant: LocalAssistant | Unreachable
    recorded: Cell[_Recorded]

    @classmethod
    def start(cls, assistant: LocalAssistant | Unreachable) -> InboxUi:
        recorded = Cell(_Recorded())

        def create_bar(actions: BarActions, *, audio_level: Callable[[], float | None] | None = None) -> DesktopBar:
            bar = DesktopBar.open(actions, native_shell=False, audio_level=audio_level)
            recorded.update(lambda views: replace(views, bar=bar))
            return bar

        def create_canvas(root: QtWidgets.QApplication, work: WorkWindow, canvas: CanvasEdits) -> CanvasWindow:
            view = CanvasWindow(root, work, canvas)
            recorded.update(lambda views: replace(views, canvas=view))
            return view

        return cls(Ui.start(assistant, views=Views(create_bar, create_canvas)), assistant, recorded)

    @property
    def root(self) -> QtWidgets.QApplication:
        return application()

    @property
    def current_bar(self) -> DesktopBar | None:
        return self.recorded.get().bar

    @property
    def current_canvas(self) -> CanvasWindow | None:
        return self.recorded.get().canvas

    def pump(self) -> None:
        # Ui yields queued work between frames. This fixture waits across those
        # turns before assertions that require every queued publication to land.
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if isinstance(self.assistant, LocalAssistant):
                self.assistant.drain()
            self.ui.drain()
            application().processEvents()
            if self.ui.settled() and not (isinstance(self.assistant, LocalAssistant) and self.assistant.jobs):
                break
        assert self.ui.settled(), "Queued UI publications did not settle."

    @property
    def bar(self) -> DesktopBar:
        bar = self.current_bar
        assert bar is not None
        return bar

    @property
    def canvas_view(self) -> CanvasWindow:
        view = self.current_canvas
        assert view is not None
        return view

    def dispose(self) -> None:
        self.ui.close_views()
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
    bar = DesktopBar.open(actions, native_shell=False)
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
    # question count depends on a view already being created, an empty inbox
    # request goes nowhere before the bar exists, or Windows notices never reach
    # the assistant's triage.
    app, original_style = application(), application().styleSheet()
    assistant = LocalAssistant(tmp_path)
    ui = InboxUi.start(assistant)
    try:
        agent = assistant.attach(ui.ui)
        ui.ui.open_inbox()
        ui.pump()
        assert ui.current_canvas is not None
        ui.ui.desktop(record=lambda _: None, stop=lambda: None, overlay=lambda: None, menu=lambda: None)
        notices = Observed((Notice(NoticeKey(11, 100), "mail", "Outlook", "Review", "Budget review"),))
        ui.ui.system_notices(notices)
        ui.pump()
        assert waiting(ui.bar) is None and assistant.observed == (notices,)
        agent.request_input(asked("owned", "Which sheet?", "", 3), accept_answer)
        ui.pump()
        capsule = waiting(ui.bar)
        assert capsule is not None and "1 clarification needs" in capsule.accessibleName()
        assert ui.ui.answer_canvas(SessionRequest(agent.snapshot().identity, "owned"), "Revenue")
        ui.pump()
        assert waiting(ui.bar) is None
    finally:
        ui.dispose()
        app.setStyleSheet(original_style)


def test_toolbar_request_expands_in_place_routes_voice_and_opens_canvas_only_from_icon(tmp_path: Path) -> None:
    # Defect: the attention click navigates away, clips the request, or sends a
    # spoken reply to the conversation rather than its exact waiting owner.
    assistant = LocalAssistant(tmp_path)
    ui = InboxUi.start(assistant)
    original_style = application().styleSheet()
    answers: list[TextAnswer] = []

    def accept(reply: TextAnswer) -> bool:
        answers.append(reply)
        return True

    try:
        ui.ui.desktop(record=lambda _: None, stop=lambda: None, overlay=lambda: None, menu=lambda: None)
        agent = assistant.attach(ui.ui)
        agent.request_input(asked("inline", "Which sheet should I use?", "Revenue contains the approved supplier figures.", 3), accept)
        ui.pump()
        assert ui.current_canvas is None
        ui.bar.show(visible=True)
        ui.bar.render()
        ui.ui.open_inbox()
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
        ui.ui.open_inbox()
        ui.pump()
        ui.ui.route_speech("Revenue")
        ui.pump()
        assert answers == [TextAnswer("Revenue")] and not assistant.spoken
        settle_toolbar(ui)
        assert waiting(ui.bar) is None
    finally:
        ui.dispose()
        application().setStyleSheet(original_style)


def test_an_open_request_follows_its_phase_and_reply_owner_when_work_asks_again(tmp_path: Path) -> None:
    # Defect: a continuation asks in the same work context but the open request
    # keeps the resolved question, so voice answers it instead of the new one.
    assistant = LocalAssistant(tmp_path)
    ui = InboxUi.start(assistant)
    original_style = application().styleSheet()
    answers: list[TextAnswer] = []

    def accept(reply: TextAnswer) -> bool:
        answers.append(reply)
        return True

    try:
        agent = assistant.attach(ui.ui)
        ui.ui.desktop(record=lambda _: None, stop=lambda: None, overlay=lambda: None, menu=lambda: None)
        agent.begin("Review budget", source=FeedRequest("source:budget", "Budget notice"))
        agent.request_input(asked("figures", "Which figures?", "Actual or forecast?", 3), accept)
        ui.pump()
        ui.ui.open_inbox()
        ui.pump()
        ui.ui.route_speech("Actual")
        ui.pump()
        agent.request_input(asked("deadline", "Which deadline?", "Monday or Friday?", 4), accept)
        ui.pump()
        panel = ui.bar.window.capsules[Key.ISLAND].request
        assert panel is not None and panel.question.text() == "Which deadline?" and ui.current_canvas is None
        ui.ui.route_speech("Monday")
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
    bar = DesktopBar.open(actions, native_shell=False, observations=BarObservations(clock=lambda: now[0], motion=lambda: False))
    try:
        bar.show(visible=True)
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
