"""Native canvas rendering, commands and persistent spatial interaction."""

import sys
import unittest
from collections import deque
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows native canvas")

import time
from dataclasses import dataclass

lazy from PySide6 import QtCore, QtGui, QtTest, QtWidgets
lazy from PySide6.QtCore import Qt

import contracts.task
from assistant.meeting_store import MeetingStore
from assistant.personal_work_store import PersonalStore
from assistant.work_canvas import WorkCanvas
from cell import Cell
from contracts.canvas_activity import Attention, CanvasQuestion, SessionRequest, TaskRequest
from contracts.feed_origin import App
from contracts.personal_work import (
    AddDocument,
    Association,
    Catalog,
    DismissWork,
    OpenWorkSource,
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
from contracts.work_canvas_context import CanvasMode
from contracts.work_canvas_contracts import CanvasEdits, CanvasPublication
from contracts.work_canvas_model import (
    CanvasCollection,
    CanvasDocument,
    CanvasNote,
    CanvasRelation,
    Placement,
    save_collection,
    save_note,
    view_state,
)
from contracts.work_commands import ReadMeeting, WorkViewCommand
from contracts.work_documents import WebDocument
from contracts.work_snapshot import WorkSnapshot
from desktop_ui.components.canvas_look import surface_fill
from desktop_ui.components.voice_legend import VoiceLegend
from desktop_ui.desktop_bar import BarActions, DesktopBar
from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import application
from desktop_ui.ui import Ui, Views
from desktop_ui.work_canvas_detail import NoteDetail, QuestionDetail, SourceDetail, WorkDetail
from desktop_ui.work_canvas_panel import CanvasPanel
from desktop_ui.work_canvas_view import CanvasGroup
from desktop_ui.work_canvas_window import CanvasWindow
from desktop_ui.work_window import WorkWindow
from tests.desktop_fixture import Unreachable
from tests.local_assistant import LocalAssistant
from tests.personal_work_fixture import source
from tests.test_work_canvas import local_canvas, nested_bubbles, queue_nothing, seeded
from tests.test_work_window import work_task

prepare()


class NativeCanvas:
    """Publishes like App: the canvas owner posts each observation to its view."""

    def __init__(self, store: WorkCanvas) -> None:
        self.root = application()
        self.jobs: deque[Callable[[], None]] = deque()
        self.store = WorkCanvas(store.path, queue_nothing, self.show_publication, autonomous=False)
        self.commands: list[WorkViewCommand] = []
        self.view: CanvasWindow
        self.work = WorkWindow.open(self.command, post=self.jobs.append, create_view=self.build)
        self.work.show(focus=False)
        self.pump()
        assert not self.work.state.status, self.work.state.status

    def command(self, command: WorkViewCommand) -> None:
        """Keep each command; answer a meeting page as the assistant does."""
        self.commands.append(command)
        match command:
            case ReadMeeting(transcript_path=path, offset=offset):
                page = MeetingStore(Path(path).parent).conversation(offset)
                self.jobs.append(lambda: self.view.meeting_page(path, page))
            case _:
                pass

    def build(self, work: WorkWindow) -> CanvasWindow:
        self.view = CanvasWindow.open(self.root, work, self.store)
        return self.view

    def pump(self) -> None:
        while self.jobs:
            self.jobs.popleft()()
        self.root.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)

    def publish(self, snapshot: WorkSnapshot) -> None:
        self.store.observe_catalog(snapshot.personal.catalog)
        self.store.observe_work(snapshot)
        self.work.publish(snapshot)
        self.pump()

    def show_publication(self, publication: CanvasPublication) -> None:
        self.jobs.append(lambda: self.view.panel.show_document(publication.document))

    def last_command(self) -> WorkViewCommand:
        return self.commands[-1]

    def close(self) -> None:
        self.work.close()
        self.pump()


def press(canvas: CanvasPanel, label: str) -> None:
    """Press the toolbar tile named `label`, pinned in the row or in its expanded sections."""
    next(tile for tile in (*canvas.pinned, *canvas.tiles) if tile.accessibleName() == label).click()


@contextmanager
def native_canvas(store: WorkCanvas) -> Generator[NativeCanvas]:
    panel = NativeCanvas(store)
    try:
        yield panel
    finally:
        panel.close()


def pressed(legend: VoiceLegend) -> bool:
    """The legend's current state, read afresh after each desktop transition."""
    return legend.pressed


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
        view = panel.view.panel
        assert not panel.view.window.findChildren(QtWidgets.QTabWidget)
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
    seeded(store, document)
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=PersonalView(data)))
        panel = native.view.panel
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
    seeded(store, document)
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=PersonalView(data)))
        canvas = native.view.panel
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
    seeded(store, CanvasDocument(activity=(question,), collapsed=frozenset((work.id,))))
    task = work_task(contracts.task.Waiting(contracts.task.Question("attention", "Which owner?", "Choose the right owner.")), identity="task")
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(tasks=(task,), personal=PersonalView(Catalog(works=(work,)))))
        canvas = native.view.panel
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
        canvas = native.view.panel
        canvas.context_menu(saved.work.id)
        press(canvas, "This isn't my work")
        command = native.last_command()
        assert isinstance(command, DismissWork) and "not my responsibility" in command.reason
        personal.handle(command, 11)
        native.publish(WorkSnapshot(personal=PersonalView(personal.read())))
        assert all(frame.context.id != saved.work.id for frame in canvas.group_frames)
        canvas.expand(None)
        press(canvas, "Restore · Atlas")
        command = native.last_command()
        assert isinstance(command, RestoreWork)
        personal.handle(command, 12)
        native.publish(WorkSnapshot(personal=PersonalView(personal.read())))
        assert any(frame.context.id == saved.work.id for frame in canvas.group_frames)


def test_startup_prepared_canvas_remains_hidden_and_keeps_its_native_scene(tmp_path: Path) -> None:
    # Defect: preparing the initial viewport shows a native window, changes
    # focus, or throws away prepared bubbles when the toolbar opens the canvas.
    data, document = nested_bubbles()
    assistant = LocalAssistant(tmp_path)
    ui = InboxUi.start(assistant)
    assistant.attach(ui.ui)
    store = assistant.canvas
    seeded(store, document)
    try:
        # Defect: retrieving the controller opens native views.
        work = ui.ui.work_window()
        ui.pump()
        assert ui.current_canvas is None and ui.ui.work_window() is work
        work.publish(WorkSnapshot(personal=PersonalView(data)))
        work.prepare()
        ui.pump()
        view = ui.canvas_view
        assert not view.window.isVisible() and not view.window.isActiveWindow()
        assert view.preview_prepared
        cards = view.panel.cards
        frames = view.panel.group_frames
        work.show(focus=False)
        ui.pump()
        assert view.window.isVisible()
        assert view.panel.cards == cards and view.panel.group_frames == frames
    finally:
        ui.dispose()


def drag_bubble(panel: NativeCanvas, identity: str) -> QtCore.QPointF:
    # Drive the public native surface; release must reach our persistence owner.
    view = panel.view.panel
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
        canvas = native.view.panel
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
        card = panel.view.panel.card(evidence.id)
        assert card is not None
        compact_title = card.title_label.mapRectToParent(card.title_label.boundingRect())
        preview = card.preview.mapRectToParent(card.preview.rect())
        assert compact_title.bottom() < preview.top()
        assert card.rect().contains(compact_title) and card.rect().contains(preview)
        assert card.rect().height() < 330
        assert card.toolTip().startswith(evidence.title)
        assert_source_mark_visible(panel, evidence.id)
        assert_heading_surface(panel, evidence.id)
        panel.view.panel.select(evidence.id)
        assert_source_mark_visible(panel, evidence.id)
        panel.view.panel.inspect(evidence.id)
        panel.pump()
        assert card.detail_proxy is not None
        assert card.title_label.mapRectToParent(card.title_label.boundingRect()).bottom() < card.detail_proxy.pos().y()
        assert card.rect().contains(card.detail_proxy.mapRectToParent(card.detail_proxy.boundingRect()))
        assert panel.view.window.size() == QtCore.QSize(800, 560)
        assert panel.view.panel.frame.rect().contains(panel.view.panel.toolbar.geometry())
        panel.view.hide()
        panel.view.show(focus=False)
        panel.pump()
        assert panel.view.window.isVisible() and card.expanded


def test_canvas_opens_maximized_and_retains_a_deliberate_restore(tmp_path: Path) -> None:
    # Defect: the opening path leaves the canvas at its fixed initial size,
    # or subsequent redirects override a user's deliberate restored window.
    with native_canvas(local_canvas(tmp_path)) as panel:
        window = panel.view.window

        def maximize() -> None:
            panel.view.panel.expand(None)
            press(panel.view.panel, "Maximize or restore")

        assert window.isMaximized()
        assert window.geometry().contains(window.screen().availableGeometry())
        maximize()
        window.resize(900, 640)
        panel.view.hide()
        panel.view.show(focus=False)
        panel.pump()
        assert not window.isMaximized() and window.size() == QtCore.QSize(900, 640)
        maximize()
        panel.pump()
        assert window.isMaximized()
        panel.view.panel.expand(None)
        press(panel.view.panel, "Close canvas")
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
    seeded(store, save_note(document, CanvasNote("note:standalone", "Context", "Original context")))
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=PersonalView(data)))
        canvas = native.view.panel
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
        native.view.panel.expand(None)
        press(native.view.panel, "Close canvas")
        assert not native.view.window.isVisible()


def test_shared_connections_move_highlight_and_disappear_with_their_reference(tmp_path: Path) -> None:
    # Defect: connectors use stale positions/reasons after moving a source or
    # stay visible after removing the factual connection.
    data, document = nested_bubbles()
    store = local_canvas(tmp_path)
    seeded(store, document)
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=PersonalView(data)))
        canvas = native.view.panel
        path = canvas.connection_paths[0]
        assert path.toolTip() == "Shared approval"
        before = path.path()
        drag_bubble(native, data.sources[0].id)
        assert canvas.connection_paths[0] is path and path.path() != before
        canvas.select(data.sources[0].id)
        assert path.pen().widthF() > 2
        native.publish(WorkSnapshot(personal=PersonalView(replace(data, works=(data.works[0], replace(data.works[1], links=()))))))
        assert not canvas.connection_paths and path.scene() is None


def test_canvas_toolbar_keeps_search_and_center_accessible_in_a_small_window(tmp_path: Path) -> None:
    # Defect: consolidating chrome crowds long context titles/search, loses a
    # nested search target, keeps the retired input field, or centers by
    # changing the saved bubble arrangement.
    personal, document = nested_scene(tmp_path)
    store = local_canvas(tmp_path)
    seeded(store, document)
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=personal))
        native.view.window.showNormal()
        native.view.window.resize(800, 560)
        canvas = native.view.panel
        assert not canvas.clear_context.isVisible()
        assert not canvas.toolbar.findChildren(QtWidgets.QPlainTextEdit)
        work = next(item for item in personal.catalog.works if item.definition.title.startswith("Atlas"))
        canvas.open_context(work.id)
        native.pump()
        canvas.search_button.click()
        native.pump()
        toolbar = canvas.toolbar
        assert_searching_island(canvas)
        assert work.definition.title in canvas.voice_hint.toolTip()
        assert canvas.voice_hint.microphone.pixmap() is not None
        assert "release to send" in canvas.voice_hint.toolTip()
        assert tuple(label.text() for label in canvas.voice_hint.findChildren(QtWidgets.QLabel)) == ("",)
        canvas.search.setText(personal.catalog.sources[0].id)
        QtTest.QTest.keyClick(canvas.search, Qt.Key.Key_Return)
        native.pump()
        assert canvas.selected == personal.catalog.sources[0].id
        assert not canvas.search.isVisible() and not canvas.search_button.isChecked()
        island = (canvas.voice_hint, canvas.clear_context, canvas.search_button, canvas.menu_button)
        assert all(control.isVisible() and toolbar.glass().contains(on_toolbar(toolbar, control)) for control in island)
        assert all(not first.geometry().intersects(second.geometry()) for first, second in pairwise(island))
        # Only temporary things sit beside the island: the Questions pill while questions wait, with their
        # count, and Recenter only once the view leaves the work.
        waiting = len(tuple(canvas.pending_questions()))
        assert canvas.questions.isVisible() == bool(waiting) and canvas.questions_button.text() == str(waiting)
        assert not canvas.recenter.isVisible(), "Recenter showed while the work is in view."
        before = store.read()
        canvas.canvas.centerOn(10000, 10000)
        native.pump()
        assert canvas.recenter.isVisible()
        assert canvas.recenter.x() + canvas.recenter.glass().right() + 6 == toolbar.x() + toolbar.glass().left()
        canvas.center_button.click()
        native.pump()
        assert not canvas.recenter.isVisible()
        visible = canvas.canvas.mapToScene(canvas.canvas.viewport().rect()).boundingRect()
        assert visible.contains(canvas.scene.itemsBoundingRect())
        bottom = canvas.canvas.mapFromScene(canvas.scene.itemsBoundingRect().bottomRight())
        assert canvas.canvas.viewport().mapTo(canvas.frame, bottom).y() < canvas.toolbar.y()
        assert store.read() == before
        assert_expands_in_place(native)


def test_canvas_gestures_pan_and_zoom_without_moving_saved_bubbles(tmp_path: Path) -> None:
    # Defect: relying on gestures ignores pixel-only trackpad input, double
    # counts its wheel deltas, or stops recognizing pinch/Control-wheel zoom.
    data, document = nested_bubbles()
    store = local_canvas(tmp_path)
    seeded(store, document)
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=PersonalView(data)))
        canvas = native.view.panel
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
        viewport = panel.view.panel.canvas
        for zoom in (1.6, 1.0, 0.6, 0.3, 0.15):
            viewport.setTransform(QtGui.QTransform().scale(zoom, zoom))
            for center in (QtCore.QPointF(0, 0), QtCore.QPointF(173, -91)):
                viewport.centerOn(center)
                panel.pump()
                image = viewport.viewport().grab().toImage()
                # Sample empty canvas away from the floating controls, in
                # native pixels (the real desktop may have a DPI scale).
                x0, y0 = image.width() // 2 - 160, image.height() // 2 - 100
                # Dots stand apart from the window in either scheme: lighter in dark, darker in light.
                ground = QtGui.QColor(panel.view.panel.theme.window).lightness()
                rows = tuple(
                    tuple(x for x in range(x0, x0 + 320) if abs(image.pixelColor(x, y).lightness() - ground) > 20) for y in range(y0, y0 + 200)
                )
                pixels = max(rows, key=len)
                dots = tuple(x for index, x in enumerate(pixels) if index == 0 or x > pixels[index - 1] + 1)
                gaps = tuple(b - a for a, b in pairwise(dots))
                assert len(dots) >= 4, (zoom, center, dots)
                assert all(16 <= gap <= 80 for gap in gaps), (zoom, center, gaps)
                assert max(gaps) - min(gaps) <= 1, (zoom, center, gaps)


def assert_source_mark_visible(panel: NativeCanvas, identity: str) -> None:
    # Defect: the selection outline fills over the app mark painted beneath it.
    view = panel.view.panel
    card = view.card(identity)
    assert card is not None
    image = QtGui.QImage(22, 22, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    view.scene.render(painter, QtCore.QRectF(0, 0, 22, 22), QtCore.QRectF(card.pos().x() + 16, card.pos().y() + 14, 22, 22))
    painter.end()
    surface = surface_fill(card.theme, card.surface)
    assert any(image.pixelColor(x, y) != surface for x in range(22) for y in range(22))


def assert_heading_surface(panel: NativeCanvas, identity: str) -> None:
    # Defect: the heading paints a dark rectangle behind the title
    # instead of using the same continuous surface as the notification bubble.
    card = panel.view.panel.card(identity)
    assert card is not None
    image = QtGui.QImage(20, 2, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    origin = card.mapToScene(card.title_label.pos())
    painter = QtGui.QPainter(image)
    panel.view.panel.scene.render(painter, QtCore.QRectF(0, 0, 20, 2), QtCore.QRectF(origin.x() + 4, origin.y() + 1, 20, 2))
    painter.end()
    surface = surface_fill(card.theme, card.surface)
    assert all(image.pixelColor(x, y) == surface for x in range(20) for y in range(2))


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
    seeded(store, document)
    with native_canvas(store) as panel:
        panel.publish(WorkSnapshot(personal=personal))
        canvas = panel.view.panel
        scene = canvas.scene
        assert len(canvas.cards) == 2 and canvas.card(work.id) is None
        context_frame = next(frame for frame in canvas.group_frames if frame.context.id == work.id)
        assert_context_header(context_frame)
        card = canvas.card(evidence.id)
        assert card is not None and card.app is App.KANBAN
        assert card.title_label.value == evidence.title and card.heading.text() == "Kanban ticket"
        root_position = drag_bubble(panel, evidence.id)
        canvas.inspect(question.id)
        editor = canvas.detail(question.id)
        assert isinstance(editor, QuestionDetail)
        clarification = editor.question.text()
        canvas.expand(None)
        press(canvas, "Collapse containers")
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


def on_toolbar(toolbar: QtWidgets.QWidget, control: QtWidgets.QWidget) -> QtCore.QRectF:
    """A control's rectangle in the toolbar's coordinates; the row sits in its own widget."""
    return QtCore.QRectF(QtCore.QPointF(control.mapTo(toolbar, QtCore.QPoint(0, 0))), QtCore.QSizeF(control.size()))


def assert_expands_in_place(native: NativeCanvas) -> None:
    """More grows the toolbar upward in place into its sections, keeping its foot; no menu pops up."""
    canvas, toolbar = native.view.panel, native.view.panel.toolbar
    foot = toolbar.y() + toolbar.height()
    canvas.menu_button.click()
    native.pump()
    contents = next(tile for tile in canvas.tiles if tile.accessibleName() == "Collapse containers")
    assert canvas.expanded and contents.isVisible() and toolbar.y() + toolbar.height() == foot
    assert toolbar.glass().contains(on_toolbar(toolbar, contents))
    canvas.menu_button.click()
    native.pump()
    assert not canvas.expanded and not canvas.tiles


def assert_searching_island(canvas: CanvasPanel) -> None:
    # Defect: the island leaves its fixed place at the window's foot, or search
    # crowds the speak and options symbols instead of taking the island over.
    toolbar = canvas.toolbar
    assert canvas.search.isVisible() and canvas.search_button.isChecked()
    assert canvas.frame.rect().contains(toolbar.geometry())
    assert abs(toolbar.geometry().center().x() - canvas.frame.rect().center().x()) <= 1
    assert canvas.frame.height() - (toolbar.y() + toolbar.glass().bottom()) == 14
    assert not canvas.voice_hint.isVisible() and not canvas.clear_context.isVisible() and not canvas.menu_button.isVisible()
    controls = (canvas.search_button, canvas.search)
    assert all(toolbar.glass().contains(on_toolbar(toolbar, control)) for control in controls)
    assert all(not first.geometry().intersects(second.geometry()) for first, second in pairwise(controls))
    assert all(abs(on_toolbar(toolbar, control).center().y() - toolbar.glass().center().y()) <= 1 for control in controls)


def assert_context_header(frame: CanvasGroup) -> None:
    # Defect: a long context title clips without ellipsis or crowds the native
    # controls because elision happens before their final geometry is measured.
    assert frame.title_label.display_text().endswith("…")
    assert frame.rect().contains(frame.title_label.mapRectToParent(frame.title_label.rect()))
    assert frame.rect().contains(frame.contents.mapRectToParent(frame.contents.rect()))


def assert_source_context(canvas: CanvasPanel, identity: str) -> None:
    assert canvas.selected is not None
    source_editor = canvas.detail(canvas.selected)
    assert isinstance(source_editor, SourceDetail)
    connected = source_editor.selected()
    assert connected is not None and connected.id == identity


def assert_inline_containment(canvas: CanvasPanel, parent: str) -> None:
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
    seeded(store, document)
    with native_canvas(store) as native:
        native.publish(WorkSnapshot(personal=PersonalView(data)))
        canvas = native.view.panel
        conversation = data.sources[0]
        card = canvas.card(conversation.id)
        assert card is not None and card.contents is not None and card.contents.disclosure.action.title == "Show 8 pieces"
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
        assert doc_card is not None and doc_card.app is App.DOCUMENT and doc_card.heading.text() == "Document"
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
    canvas = native.view.panel
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
    seeded(
        store,
        CanvasDocument(
            notes=(note,),
            collections=(group,),
            placements=(Placement(note.id, 0, 64), Placement(group.id, 520, 64)),
            pinned=frozenset((note.id, group.id)),
            collapsed=frozenset((group.id,)),
        ),
    )
    with native_canvas(store) as native:
        canvas = native.view.panel
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
            assert canvas.expanded
            labels = tuple(tile.accessibleName() for tile in canvas.tiles)
            assert "Focus" in labels and "Connect…" in labels and "Move to canvas" in labels
            canvas.collapse()
        canvas.inspect(note.id)
        assert card.detail_proxy is not None
        point = canvas.canvas.mapFromScene(card.detail_proxy.mapToScene(QtCore.QPointF(30, 30)))
        event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Reason.Mouse, point, canvas.canvas.viewport().mapToGlobal(point))
        QtCore.QCoreApplication.sendEvent(canvas.canvas.viewport(), event)
        assert canvas.expanded and canvas.selected == note.id
        canvas.collapse()
        canvas.remove_relation(store.read().relations[0])
        assert not store.read().relations and not canvas.connection_paths


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
            view = CanvasWindow.open(root, work, canvas)
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
