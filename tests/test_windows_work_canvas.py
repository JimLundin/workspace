"""Native canvas rendering, commands and persistent spatial interaction."""

import sys
import time
import unittest
from collections import deque
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows native canvas")

lazy from PySide6 import QtCore, QtGui, QtTest, QtWidgets
lazy from PySide6.QtCore import Qt

import automation.task
from assistant.agent_session import Answered
from assistant.canvas_activity import ROOT_CONTEXT, Attention, CanvasInstruction, CanvasQuestion, CanvasRun, SessionRequest, TaskRequest
from assistant.feed_agent_tools import request
from assistant.feed_origin import App
from assistant.icons import State
from assistant.local_bridge import LocalBridge
from assistant.notifications import body
from assistant.personal_work_panel import PersonalPanel
from assistant.qt_runtime import prepare
from assistant.qt_ui import application
from assistant.ui_components.bubble import heading_text
from assistant.ui_components.canvas_loading import CanvasLoading
from assistant.work_bridge import WorkOwners
from assistant.work_bridge_contracts import WORK_BRIDGE
from assistant.work_canvas import WorkCanvas, instruction_prompt
from assistant.work_canvas_commands import CANVAS_RESPONSE, CanvasSnapshot, CanvasUpdated
from assistant.work_canvas_context import CanvasMode
from assistant.work_canvas_detail import NoteDetail, QuestionDetail, SourceDetail, WorkDetail
from assistant.work_canvas_model import (
    CanvasCollection,
    CanvasDocument,
    CanvasNote,
    CanvasRelation,
    Placement,
    save_collection,
    save_note,
    view_state,
)
from assistant.work_canvas_view import CanvasGroup
from assistant.work_canvas_window import CanvasWindow
from assistant.work_window import AnswerTask, ReplyProblem, WorkCommand, WorkOpening, WorkSnapshot, WorkView, WorkWindow
from automation.actions import Resources
from automation.execution import WorkExecution
from automation.personal_work import (
    AddDocument,
    Association,
    Catalog,
    DismissedWork,
    DismissWork,
    OpenWorkSource,
    PersonalStore,
    PersonalView,
    RefreshPersonalWork,
    RestoreWork,
    SaveWork,
    SourceKind,
    UnlinkWork,
    WorkDefinition,
    WorkSaved,
    WorkState,
    WorkThread,
)
from automation.store import TaskStore
from automation.task import ActionNotApplied, ActionVerified
from automation.work_documents import WebDocument
from tests.agent_requests import asked
from tests.feed_fixture import feed_unavailable, no_personal_work
from tests.personal_work_fixture import source
from tests.test_agent import ToolRig
from tests.test_windows_inbox_attention import InboxUi
from tests.test_work_actions import claimed
from tests.test_work_canvas import local_canvas, nested_bubbles
from tests.test_work_window import work_task
from winapi import windows

prepare()


class NativeCanvas:
    """Publishes like App: the canvas owner observes, then the window renders its document."""

    def __init__(self, store: WorkCanvas) -> None:
        self.root = application()
        self.store = store
        self.jobs: deque[Callable[[], None]] = deque()
        self.commands: list[WorkCommand] = []
        self.view: CanvasWindow
        self.work = WorkWindow(self.commands.append, post=self.jobs.append, create_view=self.build)
        self.work.show(focus=False)
        self.pump()
        assert not self.work.state.status, self.work.state.status

    def build(self, work: WorkWindow) -> CanvasWindow:
        self.view = CanvasWindow(self.root, work, self.store)
        return self.view

    def pump(self) -> None:
        while self.jobs:
            self.jobs.popleft()()
        self.root.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)

    def publish(self, snapshot: WorkSnapshot) -> None:
        self.store.observe_catalog(snapshot.personal.catalog)
        self.view.personal.document = self.store.observe_work(snapshot).document
        self.work.publish(snapshot)
        self.pump()

    def last_command(self) -> WorkCommand:
        return self.commands[-1]

    def close(self) -> None:
        self.work.close()
        self.pump()


@contextmanager
def native_canvas(store: WorkCanvas) -> Generator[NativeCanvas]:
    panel = NativeCanvas(store)
    try:
        yield panel
    finally:
        panel.close()


class LoadingPaintObserver(QtCore.QObject):
    """Observe the real viewport event and the owned native indicator's lifetime."""

    def __init__(self, root: QtCore.QObject, loading: CanvasLoading) -> None:
        super().__init__(root)
        self.loading = loading
        self.first_paint: bool | None = None

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.Paint and self.first_paint is None:
            indicator = self.loading.spinner
            self.first_paint = indicator is not None and windows.is_visible(indicator.handle)
        return False


def test_my_work_sources_corrections_and_editing_survive_background_publication(tmp_path: Path) -> None:
    # Defect: My work renders no saved sources, opens/unlinks the wrong identity,
    # or a background summary replaces an unsaved user editing draft.
    store = PersonalStore(tmp_path / "work.sqlite3")
    evidence = source(SourceKind.OUTLOOK)
    store.observe((evidence,))
    saved = store.handle(
        SaveWork(
            WorkDefinition("Atlas migration", "Deploy Atlas", "Supplier approved", "Schedule deployment"),
            (Association(evidence.id, "This mail approves the Atlas deployment."),),
        ),
        20,
    )
    assert isinstance(saved, WorkSaved)
    canvas_store = local_canvas(tmp_path)
    with native_canvas(canvas_store) as panel:
        view = panel.view.personal
        assert not panel.view.window.findChildren(QtWidgets.QTabWidget)
        assert panel.view.administration is None
        panel.publish(WorkSnapshot(personal=PersonalView(store.read(), "Automatically connected")))
        assert len(view.cards) == 1 and len(view.group_frames) == 1
        view.inspect(saved.work.id)
        detail = view.detail(saved.work.id)
        assert isinstance(detail, WorkDetail)
        assert "Deploy Atlas" in detail.text.toPlainText()
        assert "Schedule deployment" in detail.text.toPlainText()
        view.inspect(evidence.id)
        source_detail = view.detail(evidence.id)
        assert isinstance(source_detail, SourceDetail)
        assert "approves the Atlas deployment" in source_detail.reason.toPlainText()
        source_detail.open.click()
        assert panel.last_command() == OpenWorkSource(evidence.id)
        source_detail.unlink.click()
        assert panel.last_command() == UnlinkWork(saved.work.id, evidence.id, saved.work.revision)
        detail.done.click()
        done = panel.last_command()
        assert isinstance(done, SaveWork) and done.definition.state is WorkState.DONE
        detail.edit_button.click()
        detail.goal.setPlainText("My unsaved deployment plan")
        card = view.card(evidence.id)
        assert card is not None
        position = drag_bubble(panel, evidence.id)
        assert Placement(evidence.id, position.x(), position.y()) in canvas_store.read().placements
        updated = store.handle(
            SaveWork(replace(saved.work.definition, summary="A new message arrived"), saved.work.links, saved.work.id, saved.work.revision), 21
        )
        assert isinstance(updated, WorkSaved)
        panel.publish(WorkSnapshot(personal=PersonalView(store.read(), "Updated")))
        assert detail.goal.toPlainText() == "My unsaved deployment plan"
        assert view.card(evidence.id) is card and card.pos() == position
        detail.save()
        command = panel.last_command()
        assert isinstance(command, SaveWork) and command.expected_revision == saved.work.revision
        assert command.definition.goal == "My unsaved deployment plan"
        assert "new message" in detail.text.toPlainText()
        view.refresh()
        assert panel.last_command() is RefreshPersonalWork.REFRESH


def test_unchanged_canvas_reopening_and_resize_reuse_native_groups(tmp_path: Path) -> None:
    # Defect: reopening/resize recreates every embedded group header on Qt,
    # blocking interaction despite unchanged content and discarding widget state.
    store = local_canvas(tmp_path)
    data, document = nested_bubbles()
    store.save(document)
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=PersonalView(data)))
        panel = native.view.personal
        previous = frozendict((frame.context.id, frame) for frame in panel.group_frames)
        native.work.show(focus=False)
        native.pump()
        assert all(frame is previous[frame.context.id] for frame in panel.group_frames)
        panel.open_context(data.works[0].id)
        panel.clear_selection()
        native.pump()
        assert all(frame is previous[frame.context.id] for frame in panel.group_frames)
        native.view.window.showNormal()
        native.view.window.resize(1100, 850)
        native.pump()
        assert all(frame is previous[frame.context.id] for frame in panel.group_frames)


def test_unopened_nested_bubbles_are_created_when_found_or_redirected(tmp_path: Path) -> None:
    # Defect: opening materializes every collapsed conversation/document child,
    # or deferring those widgets makes search and agent redirects lose their target.
    data, document = nested_bubbles()
    store = local_canvas(tmp_path)
    store.save(document)
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=PersonalView(data)))
        canvas = native.view.personal
        first = next(item for item in data.sources if item.parent_id == data.sources[0].id)
        assert canvas.card(first.id) is None
        canvas.search.setText(first.id)
        canvas.find()
        native.pump()
        card = canvas.card(first.id)
        assert card is not None and card in canvas.visible_cards
        doc = next(item for item in data.sources if item.kind is SourceKind.DOCUMENT)
        canvas.open_at(doc.id)
        native.pump()
        card = canvas.card(doc.id)
        assert card is not None and card in canvas.visible_cards
        assert card.contents is not None
        assert tuple(child for child in card.childItems() if isinstance(child, QtWidgets.QGraphicsProxyWidget)) == ()


def test_attention_redirect_reveals_its_question_in_a_collapsed_work_context(tmp_path: Path) -> None:
    # Defect: a work_ids-only question has no navigation parent, and a cached
    # hidden card is centered while its actual work stays collapsed elsewhere.
    work = WorkThread("work:attention", 0, WorkDefinition("Attention", "Resolve ownership"), (), 10, 10)
    question = CanvasQuestion(
        "question:attention", "Which owner?", "Choose the right owner.", 11, TaskRequest("task", "attention"), Attention.WAITING, (work.id,)
    )
    store = local_canvas(tmp_path)
    store.save(CanvasDocument(activity=(question,), collapsed=frozenset((work.id,))))
    task = work_task(automation.task.Waiting(automation.task.Question("attention", "Which owner?", "Choose the right owner.")), identity="task")
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(tasks=(task,), personal=PersonalView(Catalog(works=(work,)))))
        canvas = native.view.personal
        canvas.questions_button.click()
        native.pump()
        card = canvas.card(question.id)
        assert canvas.scope.identity is None
        assert card is not None and card in canvas.visible_cards and card.expanded
        assert canvas.selected == question.id
        center = canvas.canvas.mapFromScene(card.sceneBoundingRect().center())
        assert canvas.canvas.viewport().rect().contains(center)


def test_work_dismissal_and_restore_controls_change_the_local_canvas(tmp_path: Path) -> None:
    # Defect: the work menu cannot correct ownership, removed contexts keep
    # rendering after publication, or restore has no route back to the catalog.
    personal = PersonalStore(tmp_path / "work.sqlite3")
    saved = personal.handle(SaveWork(WorkDefinition("Atlas", "Check ownership")), 10)
    assert isinstance(saved, WorkSaved)
    with native_canvas(local_canvas(tmp_path)) as native:
        native.publish(WorkSnapshot(personal=PersonalView(personal.read())))
        canvas = native.view.personal
        canvas.context_menu(saved.work.id)
        next(action for action in canvas.context_popup.actions() if action.text() == "This isn't my work").trigger()
        command = native.last_command()
        assert isinstance(command, DismissWork) and "not my responsibility" in command.reason
        personal.handle(command, 11)
        native.publish(WorkSnapshot(personal=PersonalView(personal.read())))
        assert all(frame.context.id != saved.work.id for frame in canvas.group_frames)
        canvas.refresh_dismissed()
        canvas.dismissed_menu.actions()[0].trigger()
        command = native.last_command()
        assert isinstance(command, RestoreWork)
        personal.handle(command, 12)
        native.publish(WorkSnapshot(personal=PersonalView(personal.read())))
        assert any(frame.context.id == saved.work.id for frame in canvas.group_frames)


def test_startup_prepared_canvas_remains_hidden_and_keeps_its_native_scene(tmp_path: Path) -> None:
    # Defect: preparing the initial viewport shows a native window, changes
    # focus, or throws away prepared bubbles when the toolbar opens the canvas.
    data, document = nested_bubbles()
    store = local_canvas(tmp_path)
    store.save(document)
    ui = InboxUi()
    try:
        ui.configure_canvas(store, lambda _title, _target: None)
        work = ui.work(lambda _command: None, reveal=False)
        work.publish(WorkSnapshot(personal=PersonalView(data)))
        work.prepare()
        ui.pump()
        view = ui.canvas_view
        assert not view.window.isVisible() and not view.window.isActiveWindow()
        assert view.preview_prepared
        cards = view.personal.cards
        frames = view.personal.group_frames
        work.show(focus=False)
        ui.pump()
        assert view.window.isVisible()
        assert view.personal.cards == cards and view.personal.group_frames == frames
    finally:
        ui.dispose()


def test_first_canvas_open_shows_native_loading_before_building_and_releases_it(tmp_path: Path) -> None:
    # Defect: loading masquerades as a fullscreen canvas and is removed after
    # native show, leaving a blank interval before the viewport's first paint.
    root = application()
    data, document = nested_bubbles()
    store = local_canvas(tmp_path)
    store.save(document)
    jobs: deque[Callable[[], None]] = deque()
    loading = CanvasLoading(root)
    openings: list[CanvasLoading] = []
    views: list[CanvasWindow] = []
    observer = LoadingPaintObserver(root, loading)

    def opening() -> WorkOpening:
        openings.append(loading)
        return loading

    def create(work: WorkWindow) -> WorkView:
        assert loading.loop is not None
        if loading.loop.composition is not None:
            assert loading.spinner is not None and not loading.spinner.closed
            handle = loading.spinner.handle
            assert windows.is_visible(handle) and windows.foreground() != handle
            bounds = windows.outer_rect(handle)
            assert bounds.width == bounds.height == round(80 * windows.scale(handle))
        view = CanvasWindow(root, work, store)
        view.personal.canvas.viewport().installEventFilter(observer)
        views.append(view)
        return view

    work = WorkWindow(lambda _: None, post=jobs.append, create_view=create, create_loading=opening)
    try:
        work.publish(WorkSnapshot(personal=PersonalView(data)))
        work.show(focus=False)
        while jobs:
            jobs.popleft()()
        assert not loading.closed
        if loading.spinner is not None:
            assert windows.is_visible(loading.spinner.handle)
        root.processEvents()
        QtTest.QTest.qWait(20)
        assert not work.state.status, work.state.status
        view = views[0]
        assert view.window.isVisible() and loading.closed
        assert loading.loop is not None and loading.loop.closed
        if loading.spinner is not None:
            assert observer.first_paint is True
            assert loading.spinner.closed and not loading.spinner.rotating
            assert not windows.is_visible(loading.spinner.handle)
    finally:
        work.close()
        while jobs:
            jobs.popleft()()
        root.processEvents()
        observer.deleteLater()


def drag_bubble(panel: NativeCanvas, identity: str) -> QtCore.QPointF:
    # Drive the public native surface; release must reach our persistence owner.
    view = panel.view.personal
    card = view.card(identity)
    assert card is not None
    panel.pump()
    view.canvas.centerOn(card)
    point = view.canvas.mapFromScene(card.mapToScene(QtCore.QPointF(200, 25)))
    before = card.pos()
    QtTest.QTest.mousePress(view.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QtTest.QTest.mouseMove(view.canvas.viewport(), point + QtCore.QPoint(45, 30))
    QtTest.QTest.mouseRelease(view.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point + QtCore.QPoint(45, 30))
    panel.pump()
    assert card.pos() != before
    return card.pos()


def test_dragging_a_work_container_moves_its_contents_and_preserves_the_arrangement(tmp_path: Path) -> None:
    # Defect: a container only toggles on release, or its children stay behind
    # and the next publication discards the dragged container's position.
    evidence = source(SourceKind.KANBAN)
    work = WorkThread("work:drag", 0, WorkDefinition("Drag this work", "Keep its evidence together"), (Association(evidence.id, "Evidence"),), 10, 10)
    store = local_canvas(tmp_path)
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=PersonalView(Catalog(works=(work,), sources=(evidence,)))))
        canvas = native.view.personal
        group = next(frame for frame in canvas.group_frames if frame.context.id == work.id)
        child = canvas.card(evidence.id)
        assert child is not None
        origin, child_origin = group.pos(), child.pos()
        canvas.canvas.centerOn(group)
        start = canvas.canvas.mapFromScene(group.mapToScene(QtCore.QPointF(180, 25)))
        end = start + QtCore.QPoint(70, 45)
        QtTest.QTest.mousePress(canvas.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QtTest.QTest.mouseMove(canvas.canvas.viewport(), end)
        QtTest.QTest.mouseRelease(canvas.canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        native.pump()
        assert group.pos() != origin and child.pos() - child_origin == group.pos() - origin
        assert work.id in store.read().pinned
        canvas.render(native.work.state.personal)
        assert group.pos() != origin


def test_native_drag_and_drop_puts_an_existing_bubble_inside_another(tmp_path: Path) -> None:
    # Defect: dropping on a container only moves the card on top of it instead
    # of committing containment and revealing the card through its new route.
    note = CanvasNote("note:drop", "Evidence", "Collected evidence")
    target = CanvasCollection("group:drop", "Collect here")
    store = local_canvas(tmp_path)
    store.save(
        CanvasDocument(
            notes=(note,),
            collections=(target,),
            placements=(Placement(note.id, 0, 64), Placement(target.id, 520, 64)),
            pinned=frozenset((note.id, target.id)),
            collapsed=frozenset((target.id,)),
        )
    )
    with native_canvas(store) as native:
        canvas = native.view.personal
        card = canvas.card(note.id)
        group = next(frame for frame in canvas.group_frames if frame.context.id == target.id)
        assert card is not None
        start = canvas.canvas.mapFromScene(card.mapToScene(QtCore.QPointF(160, 25)))
        end = canvas.canvas.mapFromScene(group.mapToScene(QtCore.QPointF(150, 70)))
        QtTest.QTest.mousePress(canvas.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QtTest.QTest.mouseMove(canvas.canvas.viewport(), end)
        QtTest.QTest.mouseRelease(canvas.canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        native.pump()
        assert note.id in store.read().collections[0].members
        canvas.open_context(target.id)
        assert canvas.card(note.id) in canvas.visible_cards


def test_selecting_a_bubble_preserves_automatic_layout_until_it_is_dragged(tmp_path: Path) -> None:
    # Defect: an ordinary selection is saved as a manual pin, preventing
    # subsequent expansion and arrangement from moving that bubble safely.
    evidence = source(SourceKind.TEAMS)
    store = PersonalStore(tmp_path / "work.sqlite3")
    store.observe((evidence,))
    store.handle(SaveWork(WorkDefinition("Atlas", "Review this evidence"), (Association(evidence.id, "Supports Atlas"),)), 11)
    canvas_store = local_canvas(tmp_path)
    with native_canvas(canvas_store) as panel:
        panel.publish(WorkSnapshot(personal=PersonalView(store.read())))
        view = panel.view.personal
        card = view.card(evidence.id)
        assert card is not None
        point = view.canvas.mapFromScene(card.mapToScene(QtCore.QPointF(200, 25)))
        QtTest.QTest.mouseClick(view.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
        panel.pump()
        assert view.selected == evidence.id and not canvas_store.read().pinned
        drag_bubble(panel, evidence.id)
        assert canvas_store.read().pinned == frozenset((evidence.id,))


def test_long_bubbles_resize_without_overlapping_text_or_controls(tmp_path: Path) -> None:
    # Defect: fixed title/preview positions overlap on long source data, or an
    # expanded editor forces the dedicated window taller than its requested size.
    store = PersonalStore(tmp_path / "work.sqlite3")
    evidence = replace(source(SourceKind.TEAMS), title="LongUnbrokenConversationTitle" * 8, excerpt="LongUnbrokenExcerpt" * 250)
    store.observe((evidence,))
    store.handle(SaveWork(WorkDefinition("Atlas", "Review this evidence"), (Association(evidence.id, "Supports Atlas"),)), 11)
    with native_canvas(local_canvas(tmp_path)) as panel:
        panel.view.window.showNormal()
        panel.view.window.resize(800, 560)
        panel.publish(WorkSnapshot(personal=PersonalView(store.read())))
        card = panel.view.personal.card(evidence.id)
        assert card is not None
        compact_title = card.title_label.mapRectToParent(card.title_label.boundingRect())
        preview = card.preview.mapRectToParent(card.preview.rect())
        assert compact_title.bottom() < preview.top()
        assert card.rect().contains(compact_title) and card.rect().contains(preview)
        assert card.rect().height() < 330
        assert card.toolTip().startswith(evidence.title)
        assert_source_mark_visible(panel, evidence.id)
        assert_heading_surface(panel, evidence.id)
        panel.view.personal.select(evidence.id)
        assert_source_mark_visible(panel, evidence.id)
        panel.view.personal.inspect(evidence.id)
        panel.pump()
        assert card.detail_proxy is not None
        assert card.title_label.mapRectToParent(card.title_label.boundingRect()).bottom() < card.detail_proxy.pos().y()
        assert card.rect().contains(card.detail_proxy.mapRectToParent(card.detail_proxy.boundingRect()))
        assert panel.view.window.size() == QtCore.QSize(800, 560)
        assert panel.view.personal.frame.rect().contains(panel.view.personal.toolbar.geometry())
        panel.view.show_administration()
        assert panel.view.administration is not None
        assert panel.view.administration.window is not panel.view.window
        panel.view.hide()
        panel.view.show(focus=False)
        panel.pump()
        assert panel.view.window.isVisible() and card.expanded


def test_canvas_opens_maximized_and_retains_a_deliberate_restore(tmp_path: Path) -> None:
    # Defect: the opening path leaves the canvas at its fixed initial size,
    # or subsequent redirects override a user's deliberate restored window.
    with native_canvas(local_canvas(tmp_path)) as panel:
        window = panel.view.window
        window_menu = next(action.menu() for action in panel.view.personal.menu.actions() if action.text() == "Window")
        assert isinstance(window_menu, QtWidgets.QMenu)
        maximize = next(action for action in window_menu.actions() if action.text() == "Maximize or restore canvas")
        assert window.isMaximized()
        assert window.geometry().contains(window.screen().availableGeometry())
        maximize.trigger()
        window.resize(900, 640)
        panel.view.hide()
        panel.view.show(focus=False)
        panel.pump()
        assert not window.isMaximized() and window.size() == QtCore.QSize(900, 640)
        maximize.trigger()
        panel.pump()
        assert window.isMaximized()
        next(action for action in window_menu.actions() if action.text() == "Close canvas").trigger()
        panel.pump()
        assert not window.isVisible()


def escape_canvas(native: NativeCanvas) -> None:
    native.view.window.activateWindow()
    native.pump()
    QtTest.QTest.keyClick(native.view.window, Qt.Key.Key_Escape)
    native.pump()


def test_escape_unwinds_bubbles_and_search_keeps_drafts_then_exits(tmp_path: Path) -> None:
    # Defect: Escape closes the whole canvas from a nested view, loses its
    # parent camera or unsent clarification, or root Escape cannot close it.
    data, document = nested_bubbles()
    store = local_canvas(tmp_path)
    store.save(save_note(document, CanvasNote("note:standalone", "Context", "Original context")))
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=PersonalView(data)))
        canvas = native.view.personal
        conversation = data.sources[0]
        canvas.canvas.setTransform(QtGui.QTransform().scale(0.8, 0.8))
        canvas.canvas.centerOn(80, 120)
        canvas.open_context("work:two")
        canvas.open_context(conversation.id)
        neighbors = frozenset(frame.context.id for frame in canvas.group_frames)
        canvas.toggle_search()
        escape_canvas(native)
        assert canvas.search.isHidden() and not canvas.scope.path
        escape_canvas(native)
        assert native.view.window.isVisible() and not canvas.scope.path
        assert frozenset(frame.context.id for frame in canvas.group_frames) == neighbors
        card = canvas.card(conversation.id)
        assert card is not None and not card.expanded
        canvas.clear_selection()
        canvas.inspect("note:standalone")
        detail = canvas.detail("note:standalone")
        assert isinstance(detail, NoteDetail)
        detail.text.setPlainText("Unsent context")
        escape_canvas(native)
        assert native.view.window.isVisible()
        escape_canvas(native)
        assert not native.view.window.isVisible()
        native.view.show(focus=False)
        assert detail.text.toPlainText() == "Unsent context"
        native.view.exit_button.click()
        assert not native.view.window.isVisible()


def test_shared_connections_move_highlight_and_disappear_with_their_reference(tmp_path: Path) -> None:
    # Defect: connectors use stale positions/reasons after moving a source or
    # stay visible after removing the factual connection.
    data, document = nested_bubbles()
    store = local_canvas(tmp_path)
    store.save(document)
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=PersonalView(data)))
        canvas = native.view.personal
        path = canvas.connection_paths[0]
        assert path.toolTip() == "Shared approval"
        before = path.path()
        drag_bubble(native, data.sources[0].id)
        assert canvas.connection_paths[0] is path and path.path() != before
        canvas.select(data.sources[0].id)
        assert path.pen().widthF() > 2
        native.publish(WorkSnapshot(personal=PersonalView(replace(data, works=(data.works[0], replace(data.works[1], links=()))))))
        assert not canvas.connection_paths and path.scene() is None


def test_canvas_speech_instructs_the_open_canvas_and_keeps_failed_directions_for_retry(tmp_path: Path) -> None:
    # Defect: speech routes to a stale selection, a failed handoff loses the
    # pending direction, or a hidden canvas swallows the conversation input.
    ui = InboxUi()
    tasks = TaskStore(tmp_path / "tasks.sqlite3")
    attempts: list[CanvasRun] = []

    def queue(run: CanvasRun) -> None:
        attempts.append(run)
        if len(attempts) == 1:
            raise OSError("Queue unavailable")
        tasks.submit(run.task_id, "Canvas instruction", instruction_prompt(run), automation.task.RequestSource("canvas"), at=20)

    store = WorkCanvas(tmp_path / "canvas.sqlite3", queue, autonomous=False)
    ui.configure_canvas(store, lambda _title, _target: None)
    work = ui.work(lambda _command: None, reveal=False)
    work.show(focus=False)
    ui.pump()
    try:
        canvas = ui.canvas_view.personal
        instruction = "Find the deployment plan\nand compare the two document versions."
        fallback: list[str] = []
        ui.voice_agent(instruction, fallback.append)
        ui.pump()
        assert canvas.instruction_run is not None and "Queue unavailable" in canvas.status.text()
        ui.voice_agent(instruction, fallback.append)
        ui.pump()
        assert canvas.instruction_run is None and attempts[0] == attempts[1] and not fallback
        run = attempts[-1]
        assert run.intent == CanvasInstruction(instruction) and run.work_id == ROOT_CONTEXT
        task = tasks.get(run.task_id)
        assert task is not None and task.prompt.startswith(instruction + "\n\n") and "whole canvas" in task.prompt
        finding = CanvasNote("note:versions", "Deployment plans", "Two versions found")
        assert canvas.commit(save_note(canvas.document, finding))
        canvas.select(finding.id)
        ui.voice_agent("Explain the differences", fallback.append)
        ui.pump()
        assert attempts[-1].work_id == finding.id and store.read().notes == (finding,)
        canvas.clear_context.click()
        assert canvas.selected is None and "whole canvas" in canvas.voice_hint.toolTip()
        ui.canvas_view.window.hide()
        ui.voice_agent("Work in the background", fallback.append)
        ui.pump()
        assert fallback == ["Work in the background"]
    finally:
        ui.dispose()


def test_canvas_toolbar_keeps_search_and_center_accessible_in_a_small_window(tmp_path: Path) -> None:
    # Defect: consolidating chrome crowds long context titles/search, loses a
    # nested search target, keeps the retired input field, or centers by
    # changing the saved bubble arrangement.
    personal, document = nested_scene(tmp_path)
    store = local_canvas(tmp_path)
    store.save(document)
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=personal))
        native.view.window.showNormal()
        native.view.window.resize(800, 560)
        canvas = native.view.personal
        assert not canvas.clear_context.isVisible()
        assert not canvas.toolbar.findChildren(QtWidgets.QPlainTextEdit)
        work = next(item for item in personal.catalog.works if item.definition.title.startswith("Atlas"))
        canvas.open_context(work.id)
        native.pump()
        canvas.search_button.click()
        native.pump()
        toolbar = canvas.toolbar
        assert canvas.search.isVisible() and canvas.search_button.isChecked()
        assert canvas.frame.rect().contains(toolbar.geometry())
        assert abs(toolbar.geometry().center().x() - canvas.frame.rect().center().x()) <= 1
        assert canvas.frame.height() - toolbar.geometry().bottom() == 25
        controls = (
            canvas.voice_hint,
            canvas.clear_context,
            canvas.search_button,
            canvas.search,
            canvas.center_button,
            canvas.questions_button,
            canvas.menu_button,
        )
        assert all(toolbar.rect().contains(control.geometry()) for control in controls)
        assert all(not first.geometry().intersects(second.geometry()) for first, second in pairwise(controls))
        assert work.definition.title in canvas.voice_hint.toolTip()
        assert canvas.voice_hint.keycap.text() == "N"
        assert canvas.voice_hint.microphone.pixmap() is not None
        assert "release to send" in canvas.voice_hint.toolTip()
        assert tuple(label.text() for label in canvas.voice_hint.findChildren(QtWidgets.QLabel)) == ("", "N")
        assert all(abs(control.geometry().center().y() - toolbar.rect().center().y()) <= 1 for control in controls)
        canvas.search.setText(personal.catalog.sources[0].id)
        QtTest.QTest.keyClick(canvas.search, Qt.Key.Key_Return)
        native.pump()
        assert canvas.selected == personal.catalog.sources[0].id
        assert not canvas.search.isVisible() and not canvas.search_button.isChecked()
        before = store.read()
        canvas.canvas.centerOn(10000, 10000)
        canvas.center_button.click()
        native.pump()
        visible = canvas.canvas.mapToScene(canvas.canvas.viewport().rect()).boundingRect()
        assert visible.contains(canvas.scene.itemsBoundingRect())
        bottom = canvas.canvas.mapFromScene(canvas.scene.itemsBoundingRect().bottomRight())
        assert canvas.canvas.viewport().mapTo(canvas.frame, bottom).y() < canvas.toolbar.y()
        assert store.read() == before
        canvas.menu_button.click()
        native.pump()
        assert canvas.menu.isVisible()
        assert canvas.menu.geometry().contains(canvas.menu.actionGeometry(canvas.contents_action).translated(canvas.menu.pos()))
        canvas.menu.close()


def test_canvas_gestures_pan_and_zoom_without_moving_saved_bubbles(tmp_path: Path) -> None:
    # Defect: relying on gestures ignores pixel-only trackpad input, double
    # counts its wheel deltas, or stops recognizing pinch/Control-wheel zoom.
    data, document = nested_bubbles()
    store = local_canvas(tmp_path)
    store.save(document)
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=PersonalView(data)))
        canvas = native.view.personal
        viewport = canvas.canvas
        before = store.read()
        point = QtCore.QPointF(200, 200)
        for pixels, angle, modifiers in (
            (QtCore.QPoint(17, 23), QtCore.QPoint(120, 120), Qt.KeyboardModifier.NoModifier),
            (QtCore.QPoint(), QtCore.QPoint(0, 120), Qt.KeyboardModifier.ControlModifier),
            (QtCore.QPoint(0, 30), QtCore.QPoint(), Qt.KeyboardModifier.ControlModifier),
        ):
            scale = viewport.transform().m11()
            old = QtCore.QPoint(viewport.horizontalScrollBar().value(), viewport.verticalScrollBar().value())
            event = QtGui.QWheelEvent(point, point, pixels, angle, Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.ScrollUpdate, False)
            QtCore.QCoreApplication.sendEvent(viewport.viewport(), event)
            if modifiers is Qt.KeyboardModifier.NoModifier:
                assert viewport.transform().m11() == scale
                assert QtCore.QPoint(viewport.horizontalScrollBar().value(), viewport.verticalScrollBar().value()) == old - pixels
            else:
                assert viewport.transform().m11() > scale
        scale = viewport.transform().m11()
        pinch = QtGui.QNativeGestureEvent(
            Qt.NativeGestureType.ZoomNativeGesture,
            QtGui.QPointingDevice.primaryPointingDevice(),
            2,
            point,
            point,
            point,
            -0.2,
            QtCore.QPointF(),
        )
        QtCore.QCoreApplication.sendEvent(viewport.viewport(), pinch)
        assert 0.15 <= viewport.transform().m11() < scale
        assert store.read() == before


def test_grid_remains_visible_and_spaced_when_zoomed_out_and_panned(tmp_path: Path) -> None:
    # Defect: the tiled raster shrinks into invisible dots or dense stripes;
    # Workspace must keep its spatial reference visible at every allowed zoom.
    with native_canvas(local_canvas(tmp_path)) as panel:
        viewport = panel.view.personal.canvas
        for zoom in (1.6, 1.0, 0.6, 0.3, 0.15):
            viewport.setTransform(QtGui.QTransform().scale(zoom, zoom))
            for center in (QtCore.QPointF(0, 0), QtCore.QPointF(173, -91)):
                viewport.centerOn(center)
                panel.pump()
                image = viewport.viewport().grab().toImage()
                # Sample empty canvas away from the floating controls, in
                # native pixels (the real desktop may have a DPI scale).
                x0, y0 = image.width() // 2 - 160, image.height() // 2 - 100
                rows = tuple(tuple(x for x in range(x0, x0 + 320) if image.pixelColor(x, y).lightness() > 42) for y in range(y0, y0 + 200))
                pixels = max(rows, key=len)
                dots = tuple(x for index, x in enumerate(pixels) if index == 0 or x > pixels[index - 1] + 1)
                gaps = tuple(b - a for a, b in pairwise(dots))
                assert len(dots) >= 4, (zoom, center, dots)
                assert all(16 <= gap <= 80 for gap in gaps), (zoom, center, gaps)
                assert max(gaps) - min(gaps) <= 1, (zoom, center, gaps)


def assert_source_mark_visible(panel: NativeCanvas, identity: str) -> None:
    # Defect: the selection outline fills over the app mark painted beneath it.
    view = panel.view.personal
    card = view.card(identity)
    assert card is not None
    image = QtGui.QImage(18, 18, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    view.scene.render(painter, QtCore.QRectF(0, 0, 18, 18), QtCore.QRectF(card.pos().x() + 5, card.pos().y() + 5, 18, 18))
    painter.end()
    assert any(image.pixelColor(x, y) != QtGui.QColor(card.colors.surface) for x in range(18) for y in range(18))


def assert_heading_surface(panel: NativeCanvas, identity: str) -> None:
    # Defect: the heading paints a dark rectangle behind the title
    # instead of using the same continuous surface as the notification bubble.
    card = panel.view.personal.card(identity)
    assert card is not None
    image = QtGui.QImage(20, 2, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    origin = card.mapToScene(card.title_label.pos())
    painter = QtGui.QPainter(image)
    panel.view.personal.scene.render(painter, QtCore.QRectF(0, 0, 20, 2), QtCore.QRectF(origin.x() + 4, origin.y() + 1, 20, 2))
    painter.end()
    assert all(image.pixelColor(x, y) == QtGui.QColor(card.colors.surface) for x in range(20) for y in range(2))


def pump_until(ui: InboxUi, ready: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 4
    while not ready() and time.monotonic() < deadline:
        ui.pump()
        QtTest.QTest.qWait(10)
    assert ready(), "The native canvas did not receive the request publication."


def test_agent_canvas_bridge_commits_on_qt_and_refreshes_without_revealing(tmp_path: Path) -> None:
    # Defect: worker edits race with Qt, return success before persistence,
    # overwrite a user draft, bypass durable verification or reveal a window.
    ui = InboxUi()
    store = local_canvas(tmp_path)
    ui.configure_canvas(store, lambda _title, _target: None)
    ui.observe_canvas(nested_bubbles()[0])
    ui.pump()
    endpoint = tmp_path / "bridge.json"
    bridge = LocalBridge(endpoint, WORK_BRIDGE, WorkOwners(feed_unavailable, no_personal_work, ui.canvas_command).handle)
    tasks, claim, clock = claimed(tmp_path)
    rig = ToolRig(work=WorkExecution(claim, tasks, Resources(), clock=clock), feed_request=lambda data: request(data, endpoint))
    try:
        with ThreadPoolExecutor(max_workers=1) as worker:
            reading = worker.submit(rig.call, "work_canvas_read")
            pump_until(ui, reading.done)
            snapshot = CANVAS_RESPONSE.validate_json(reading.result().text.split("\n[observation_id:", 1)[0])
            assert isinstance(snapshot, CanvasSnapshot) and snapshot.work_ids
            assert not tasks.actions(claim.task.id)
            edit = worker.submit(
                rig.call,
                "work_canvas_update",
                expected_revision=snapshot.revision,
                edits=[
                    {"kind": "note", "note": {"id": "note:agent", "title": "Version evidence", "text": "Candidate two matches the approval."}},
                    {"kind": "group", "id": "group:agent", "title": "Candidate documents"},
                    {"kind": "move", "id": "note:agent", "parent_id": "group:agent"},
                ],
            )
            pump_until(ui, edit.done)
            receipt = CANVAS_RESPONSE.validate_json(edit.result().text)
            assert isinstance(receipt, CanvasUpdated) and receipt.changed
            persisted = store.read()
            assert persisted.notes[0].text == "Candidate two matches the approval."
            assert persisted.collections[0].members == ("note:agent",)
            assert isinstance(tasks.actions(claim.task.id)[0].outcome, ActionVerified)
            stale = worker.submit(
                rig.call,
                "work_canvas_update",
                expected_revision=snapshot.revision,
                edits=[{"kind": "group", "id": "group:stale", "title": "Must not appear"}],
            )
            pump_until(ui, stale.done)
            stale.result()
            assert isinstance(tasks.actions(claim.task.id)[-1].outcome, ActionNotApplied)
            assert store.read() == persisted
        # No window had to be created for any read, edit or conflict.
        assert not any(widget.isVisible() for widget in ui.root.topLevelWidgets())
        assert not rig.machine.log
    finally:
        bridge.close()
        ui.dispose()


def click_canvas_notification(ui: InboxUi) -> None:
    card = next(card for card in ui.feed.cards.values() if card.content is not None and "Open on canvas" in body(card.content))
    if not card.expanded:
        card.toggle(animate=False)
    ui.pump()
    assert len(card.canvas_actions) == 1
    span, button = card.canvas_actions[0]
    assert span.link.startswith("workspace://canvas?")
    assert button.isVisible() and not button.icon().isNull()
    assert card.window.rect().contains(button.geometry())
    assert card.text.document().find("Open on canvas").isNull()
    QtTest.QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    ui.pump()


def test_canvas_voice_key_feedback_follows_agent_capture_and_release(tmp_path: Path) -> None:
    # Defect: opening during speech misses the held state, background work
    # clears it, release leaves it pressed during transcription, or dictation
    # incorrectly lights the agent key. Feedback must not resize the toolbar.
    ui = InboxUi()
    ui.configure_canvas(local_canvas(tmp_path), lambda _title, _target: None)
    ui.desktop_state(State.LISTENING, agent_speaking=True)
    ui.pump()
    work = ui.work(lambda _: None, reveal=True, focus=False)
    ui.pump()
    try:
        legend = ui.canvas_view.personal.voice_hint
        assert legend.pressed and "Listening" in legend.accessibleDescription()
        held = legend.grab().toImage()
        bounds = legend.geometry()
        ui.desktop_state(State.LISTENING, agent_speaking=True)
        ui.pump()
        assert legend.pressed and legend.grab().toImage() == held
        ui.desktop_state(State.WORKING)
        ui.pump()
        assert not legend.pressed and legend.geometry() == bounds
        released = legend.grab().toImage()
        assert released != held
        ui.desktop_state(State.AGENT)
        ui.pump()
        assert not legend.pressed and legend.grab().toImage() == released
        ui.desktop_state(State.LISTENING)
        ui.pump()
        assert not legend.pressed and legend.grab().toImage() == released
        ui.desktop_state(State.LISTENING, agent_speaking=True)
        ui.pump()
        assert legend.pressed and legend.grab().toImage() == held
        ui.canvas_view.hide()
        ui.desktop_state(State.AGENT)
        ui.pump()
        work.show(focus=False)
        ui.pump()
        assert not legend.pressed and legend.grab().toImage() == released
    finally:
        ui.dispose()


def test_canvas_clarification_redirect_submits_context_to_the_waiting_agent(tmp_path: Path) -> None:
    # Defect: the redirect opens the wrong bubble, reserves empty editor space,
    # or spoken context fails to resume the exact existing waiting worker.
    ui = InboxUi()
    store = local_canvas(tmp_path)
    ui.configure_canvas(store, lambda _title, _target: None)
    work = ui.work(lambda _command: None, reveal=False)
    agent = ui.agent(None, lambda: None, on_work=lambda: work.show(focus=False), reveal=False)
    ui.pump()
    agent.show(focus=False)
    ui.pump()
    resumed: list[str] = []

    def resume(answer: str) -> bool:
        resumed.append(answer)
        return True

    agent.request_input(
        asked("atlas", "Which supplier should own Atlas?", "I have read the handoff mail. I need your ownership decision.", time.time()),
        resume,
    )
    try:
        pump_until(ui, lambda: bool(store.read().activity))
        question = store.read().activity[0]
        assert isinstance(question, CanvasQuestion) and isinstance(question.request, SessionRequest)
        click_canvas_notification(ui)
        canvas = ui.canvas_view.personal
        assert canvas.selected == question.id
        detail = canvas.detail(question.id)
        assert isinstance(detail, QuestionDetail)
        assert not detail.frame.findChildren(QtWidgets.QPlainTextEdit) and detail.frame.height() <= 152
        assert detail.status.text() == "Hold N to reply · release to send"
        fallback: list[str] = []
        ui.voice_agent("Contoso owns the handoff.", fallback.append)
        pump_until(ui, lambda: bool(resumed))
        assert resumed == ["Contoso owns the handoff."]
        ui.pump()
        assert "Contoso owns the handoff." in detail.response.text() and not fallback
        answered = store.read().activity[0]
        assert isinstance(answered, CanvasQuestion) and answered.reply == Answered("Contoso owns the handoff.")
        card = canvas.card(question.id)
        assert card is not None and card.detail_proxy is not None
        assert card.rect().contains(card.detail_proxy.boundingRect().translated(card.detail_proxy.pos()))
    finally:
        ui.dispose()


def test_canvas_spoken_reply_keeps_transcript_on_rejection_and_continue_stays_bound_to_work(tmp_path: Path) -> None:
    # Defect: task replies route to a different request, failed persistence loses
    # user text, or starting research loses the work-to-run connection on reopen.
    ui = InboxUi()
    commands: list[WorkCommand] = []
    runs: list[CanvasRun] = []
    store = WorkCanvas(tmp_path / "canvas.sqlite3", runs.append, autonomous=False)
    ui.configure_canvas(store, lambda _title, _target: None)
    work = ui.work(commands.append, reveal=True, focus=False)
    task = work_task(automation.task.Waiting(automation.task.Question("request", "Which owner?", "Confirm the handoff.")))
    personal = PersonalStore(tmp_path / "work.sqlite3")
    saved = personal.handle(SaveWork(WorkDefinition("Atlas", "Deploy Atlas")), 20)
    assert isinstance(saved, WorkSaved)
    store.save(replace(store.read(), runs=(CanvasRun(task.id, saved.work.id),)))
    snapshot = WorkSnapshot(tasks=(task,), personal=PersonalView(personal.read()))
    work.publish(snapshot)
    ui.observe_canvas_work(snapshot)
    ui.pump()
    try:
        canvas = ui.canvas_view.personal
        canvas.open_at("question:request")
        question = canvas.detail("question:request")
        assert isinstance(question, QuestionDetail)
        assert not ui.answer_canvas(TaskRequest(task.id, "request"), "x" * 16001)
        fallback: list[str] = []
        ui.voice_agent("x" * 16001, fallback.append)
        ui.pump()
        assert not fallback and "could not be sent" in canvas.status.text()
        ui.voice_agent("Use Contoso", fallback.append)
        ui.pump()
        assert commands[-1] == AnswerTask(task.id, "request", automation.task.TextAnswer("Use Contoso"))
        rejected = replace(
            snapshot, reply_problems=(ReplyProblem(task_id=task.id, request_id="request", receipt_id="receipt", reason="Disk unavailable"),)
        )
        work.publish(rejected)
        ui.observe_canvas_work(rejected)
        ui.pump()
        assert "Use Contoso" in question.response.text() and question.status.text() == "Hold N to reply · release to send"
        ui.voice_agent("Use Fabrikam instead", fallback.append)
        ui.pump()
        assert commands[-1] == AnswerTask(task.id, "request", automation.task.TextAnswer("Use Fabrikam instead")) and not fallback
        canvas.inspect(saved.work.id)
        work_detail = canvas.detail(saved.work.id)
        assert isinstance(work_detail, WorkDetail)
        next(control for control in work_detail.frame.findChildren(QtWidgets.QToolButton) if control.text() == "Continue with agent").click()
        assert not runs and "already has an investigation" in canvas.status.text()
        assert len(canvas.group_frames) == 1
        bounds = tuple(card.sceneBoundingRect() for card in canvas.cards)
        assert all(not one.intersects(two) for index, one in enumerate(bounds) for two in bounds[index + 1 :])
    finally:
        ui.dispose()


def test_canvas_attention_reaches_the_desktop_and_redirects_to_its_bubble(tmp_path: Path) -> None:
    # Defect: the bell counts or opens a dismissed question, a hidden canvas
    # misses its result notice, or the notice redirects to another bubble.
    ui = InboxUi()
    store = local_canvas(tmp_path)
    dismissed = WorkThread("work:dismissed", 0, WorkDefinition("Not mine", "Other responsibility"), (), 10, 10)
    active = replace(dismissed, id="work:active", definition=WorkDefinition("Mine", "My responsibility"))
    data = Catalog(works=(active,), dismissed=(DismissedWork(dismissed, "Wrong owner"),))
    old = work_task(automation.task.Waiting(automation.task.Question("old", "Old question", "")), identity="old-task")
    current = work_task(automation.task.Waiting(automation.task.Question("current", "Current question", "")), identity="current-task")
    research = work_task(identity="research-task")
    store.save(replace(store.read(), runs=(CanvasRun(old.id, dismissed.id), CanvasRun(current.id, active.id), CanvasRun(research.id, active.id))))
    notices: list[tuple[str, str]] = []

    def notify(title: str, target: str) -> None:
        notices.append((title, target))

    try:
        ui.configure_canvas(store, notify)
        work = ui.work(lambda _command: None, reveal=True, focus=False)
        ui.desktop(
            show_agent=lambda: None, show_work=lambda: None, stop=lambda: None, overlay=lambda: None, menu=lambda: None, on_problem=lambda _: None
        )
        snapshot = WorkSnapshot(personal=PersonalView(data), tasks=(old, current, research))
        work.publish(snapshot)
        ui.observe_canvas(data)
        ui.observe_canvas_work(snapshot)
        ui.pump()
        assert not ui.bar.inbox.text() and "1 clarification needs" in ui.bar.inbox.accessibleName()
        ui.open_inbox(lambda: None)
        ui.pump()
        assert ui.canvas_view.personal.selected == "question:current"
        notices.clear()
        ui.canvas_view.hide()
        completed = replace(snapshot, tasks=(old, current, replace(research, state=automation.task.Completed("Handoff confirmed", ()))))
        work.publish(completed)
        ui.observe_canvas_work(completed)
        ui.pump()
        assert notices == [(research.title, "result:" + research.id)]
        ui.open_canvas_at(notices[0][1])
        ui.pump()
        assert ui.canvas_view.personal.selected == "result:" + research.id
    finally:
        ui.dispose()


def nested_scene(folder: Path) -> tuple[PersonalView, CanvasDocument]:
    evidence = source(SourceKind.KANBAN)
    personal = PersonalStore(folder / "work.sqlite3")
    personal.observe((evidence,))
    saved = personal.handle(
        SaveWork(
            WorkDefinition("Atlas handoff and receiving ownership decisions " * 3, "Agree handoff"), (Association(evidence.id, "Tracks handoff"),)
        ),
        20,
    )
    assert isinstance(saved, WorkSaved)
    group = CanvasCollection("group:project", "Project", (saved.work.id,))
    personal.handle(SaveWork(WorkDefinition("Other context", "Retain the same evidence"), (Association(evidence.id, "Also relevant here"),)), 22)
    question = CanvasQuestion(
        "question:owner",
        "Who owns the handoff?",
        "The receiving owner is unresolved.",
        21,
        SessionRequest("session", "owner"),
        Attention.WAITING,
        (saved.work.id,),
    )
    return PersonalView(personal.read()), save_collection(CanvasDocument(activity=(question,)), group)


def test_nested_bubbles_reveal_on_one_canvas_and_retain_reading_and_pins(tmp_path: Path) -> None:
    # Defect: focusing a nested work hides neighbors, creates a second layout,
    # discards the clarification reading view or duplicates a shared Kanban source.
    personal, document = nested_scene(tmp_path)
    evidence = personal.catalog.sources[0]
    work = next(item for item in personal.catalog.works if item.definition.title.startswith("Atlas"))
    question = document.activity[0]
    assert isinstance(question, CanvasQuestion)
    group = document.collections[0]
    store = local_canvas(tmp_path)
    store.save(document)
    with native_canvas(store) as panel:
        panel.publish(WorkSnapshot(personal=personal))
        canvas = panel.view.personal
        scene = canvas.scene
        assert len(canvas.cards) == 2 and canvas.card(work.id) is None
        context_frame = next(frame for frame in canvas.group_frames if frame.context.id == work.id)
        assert_context_header(context_frame)
        card = canvas.card(evidence.id)
        assert card is not None and card.app is App.KANBAN
        assert card.title_label.value == evidence.title and card.heading.toPlainText() == "Kanban ticket"
        root_position = drag_bubble(panel, evidence.id)
        canvas.inspect(question.id)
        editor = canvas.detail(question.id)
        assert isinstance(editor, QuestionDetail)
        clarification = editor.question.text()
        canvas.contents_action.trigger()
        assert canvas.scope.mode is CanvasMode.CONTEXTS and not canvas.visible_cards
        next(frame for frame in canvas.group_frames if frame.context.id == group.id).contents.open_canvas.click()
        panel.pump()
        next(frame for frame in canvas.group_frames if frame.context.id == work.id).contents.open_canvas.click()
        panel.pump()
        assert not canvas.scope.path and canvas.scene is scene
        assert canvas.card(question.id) in canvas.visible_cards and canvas.detail(question.id) is editor
        assert editor.question.text() == clarification
        assert canvas.card(evidence.id) is card and card.pos() == root_position
        canvas.inspect(evidence.id)
        assert_source_context(canvas, work.id)
        assert Placement(evidence.id, root_position.x(), root_position.y()) in view_state(store.read(), None).placements
        assert not store.read().views
        panel.view.window.showNormal()
        panel.view.window.resize(800, 560)
        canvas.open_context(work.id)
        panel.pump()
        assert canvas.frame.rect().contains(canvas.toolbar.geometry())
        canvas.open_at(question.id)
        assert canvas.selected == question.id and editor.question.text() == clarification


def assert_context_header(frame: CanvasGroup) -> None:
    # Defect: a long context title clips without ellipsis or crowds the native
    # controls because elision happens before their final geometry is measured.
    assert heading_text(frame.title_label.value, round(frame.title_label.rect().width()), expanded=False).endswith("…")
    assert frame.rect().contains(frame.title_label.mapRectToParent(frame.title_label.rect()))
    assert frame.rect().contains(frame.contents.mapRectToParent(frame.contents.rect()))


def assert_source_context(canvas: PersonalPanel, identity: str) -> None:
    assert canvas.selected is not None
    source_editor = canvas.detail(canvas.selected)
    assert isinstance(source_editor, SourceDetail)
    connected = source_editor.selected()
    assert connected is not None and connected.id == identity


def assert_inline_containment(canvas: PersonalPanel, parent: str) -> None:
    bubble = canvas.card(parent)
    assert bubble is not None
    bounds = tuple(item.sceneBoundingRect() for item in canvas.visible_cards if item is not bubble)
    assert all(not one.intersects(two) for index, one in enumerate(bounds) for two in bounds[index + 1 :])
    children = frozenset(source.id for source in canvas.view.catalog.sources if source.parent_id == parent)
    assert all(bubble.sceneBoundingRect().contains(item.sceneBoundingRect()) for item in canvas.visible_cards if item.content.id in children)


def test_nested_document_and_conversation_controls_keep_routes_and_drafts(tmp_path: Path) -> None:
    # Defect: disclosure still acts as Read, parent collapse closes a draft,
    # shared-source navigation jumps to the other work, or documents use Edge's badge.
    data, document = nested_bubbles()
    store = local_canvas(tmp_path)
    store.save(document)
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=PersonalView(data)))
        canvas = native.view.personal
        conversation = data.sources[0]
        card = canvas.card(conversation.id)
        assert card is not None and card.contents is not None and card.contents.disclosure.action.title == "▸ Show 8 pieces"
        card.contents.disclosure.click()
        native.pump()
        assert card.contents_expanded and card in canvas.visible_cards
        assert len(canvas.visible_cards) == 10
        assert_inline_containment(canvas, conversation.id)
        card.contents.disclosure.click()
        canvas.open_context("work:two")
        native.pump()
        card.contents.open_canvas.click()
        native.pump()
        assert not canvas.scope.path
        assert len(canvas.visible_cards) == 10
        first = next(item for item in data.sources if item.parent_id == conversation.id)
        first_card = canvas.card(first.id)
        assert first_card is not None and first_card.contents is not None
        first_card.contents.open_canvas.click()
        native.pump()
        assert not canvas.scope.path and canvas.selected == first.id
        doc = next(item for item in data.sources if item.kind is SourceKind.DOCUMENT)
        doc_card = canvas.card(doc.id)
        assert doc_card is not None and doc_card.app is App.DOCUMENT and doc_card.heading.toPlainText() == "Document"
        assert doc_card.contents is not None
        open_document_context(native, doc.id, "work:one")
        canvas.inspect("note:annotation")
        note = canvas.detail("note:annotation")
        assert isinstance(note, NoteDetail)
        note.text.setPlainText("Unsent document annotation")
        canvas.open_context(conversation.id)
        assert not canvas.scope.path
        canvas.open_context(first.id)
        canvas.open_context(doc.id)
        assert canvas.detail("note:annotation") is note and note.text.toPlainText() == "Unsent document annotation"
        canvas.add_document(AddDocument("Design", WebDocument("https://contoso.example.test/design.docx")))
        command = native.last_command()
        assert isinstance(command, AddDocument) and command.work_id == "work:one"
        assert any(node.parent_id == doc.id and len(node.members) == 2 for node in canvas.document.nesting)


def open_document_context(native: NativeCanvas, identity: str, work: str) -> None:
    canvas = native.view.personal
    card = canvas.card(identity)
    assert card is not None and card.contents is not None
    card.contents.open_canvas.click()
    native.pump()
    assert_source_context(canvas, work)
    assert canvas.canvas.transform().m11() == 0.9


def test_native_connector_relationships_and_menus_work_for_cards_and_containers(tmp_path: Path) -> None:
    # Defect: a connector starts a bubble move, loses the relationship on
    # refresh, or right-clicks on child headings/editors bypass bubble options.
    note = CanvasNote("note:connect", "Evidence", "Useful finding")
    group = CanvasCollection("group:connect", "Decision")
    store = local_canvas(tmp_path)
    store.save(
        CanvasDocument(
            notes=(note,),
            collections=(group,),
            placements=(Placement(note.id, 0, 64), Placement(group.id, 520, 64)),
            pinned=frozenset((note.id, group.id)),
            collapsed=frozenset((group.id,)),
        )
    )
    with native_canvas(store) as native:
        canvas = native.view.personal
        card = canvas.card(note.id)
        target = next(frame for frame in canvas.group_frames if frame.context.id == group.id)
        assert card is not None
        start = canvas.canvas.mapFromScene(card.mapToScene(card.connector.pos()))
        end = canvas.canvas.mapFromScene(target.mapToScene(QtCore.QPointF(160, 70)))
        QtTest.QTest.mousePress(canvas.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QtTest.QTest.mouseMove(canvas.canvas.viewport(), end)
        assert target.drop_target and not store.read().relations
        QtTest.QTest.mouseRelease(canvas.canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        native.pump()
        assert store.read().relations == (CanvasRelation(note.id, group.id),)
        assert not store.read().collections[0].members
        canvas.render(native.work.state.personal)
        assert len(canvas.connection_paths) == 1
        for bubble in (card, target):
            point = canvas.canvas.mapFromScene(bubble.mapToScene(QtCore.QPointF(120, 25)))
            event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Reason.Mouse, point, canvas.canvas.viewport().mapToGlobal(point))
            QtCore.QCoreApplication.sendEvent(canvas.canvas.viewport(), event)
            assert canvas.context_popup.isVisible()
            labels = tuple(action.text() for action in canvas.context_popup.actions())
            assert "Focus bubble" in labels and "Connect to another bubble…" in labels and "Move to canvas" in labels
            canvas.context_popup.hide()
        canvas.inspect(note.id)
        assert card.detail_proxy is not None
        point = canvas.canvas.mapFromScene(card.detail_proxy.mapToScene(QtCore.QPointF(30, 30)))
        event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Reason.Mouse, point, canvas.canvas.viewport().mapToGlobal(point))
        QtCore.QCoreApplication.sendEvent(canvas.canvas.viewport(), event)
        assert canvas.context_popup.isVisible() and canvas.selected == note.id
        canvas.context_popup.hide()
        canvas.remove_relation(store.read().relations[0])
        assert not store.read().relations and not canvas.connection_paths
