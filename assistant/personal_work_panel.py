"""Local native work canvas backed by the saved work/source catalog.

Qt owns mutable graphics and editor lifetimes. Cards/details/groups are tuples;
positions and notes have their own local document, outside agent model input.
"""

import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.canvas_activity import ROOT_CONTEXT, Attention, CanvasAction, CanvasInstruction, CanvasQuestion, CanvasRun, CanvasUpdate
from assistant.keymap import PHYSICAL_NAMES
from assistant.qt_ui import cancel, later
from assistant.ui_components.canvas_bubble import CanvasBubble
from assistant.ui_components.canvas_chrome import CANVAS_STYLE, CanvasSurface, CanvasToolbar, icon_button
from assistant.ui_components.canvas_connection import ConnectionPath
from assistant.ui_components.controls import button, label
from assistant.ui_components.voice_legend import VoiceLegend
from assistant.ui_components.widgets import column, row
from assistant.work_canvas import Investigating, NotQueued, Queued, ResumeTask, WorkCanvas
from assistant.work_canvas_commands import PutRelation, RemoveRelation, UpdateCanvas, edited, revision
from assistant.work_canvas_connections import connections
from assistant.work_canvas_context import (
    CanvasInbox,
    CanvasMode,
    CanvasScene,
    CanvasScope,
    ContextGroup,
    container_title,
    containers,
    context_path,
    descendants,
    project,
    scene_contents,
    topology,
    visible_groups,
)
from assistant.work_canvas_gestures import (
    BubbleDrag,
    BubbleTarget,
    CancelGesture,
    ClickBubble,
    ConnectBubbles,
    DrawingRelation,
    Gesture,
    GestureEffect,
    GestureScene,
    Idle,
    MovePreview,
    NestBubble,
    NoChange,
    PlaceBubbles,
    PointerMoved,
    PointerReleased,
    PressBubble,
    PressConnector,
    RelationPreview,
    ScenePoint,
    transition,
)
from assistant.work_canvas_layout import Box, Measurements, Size, layout
from assistant.work_canvas_model import (
    CanvasCollection,
    CanvasContent,
    CanvasDocument,
    CanvasNote,
    CanvasRelation,
    CanvasViewState,
    Placement,
    nest,
    release_subtree,
    save_collection,
    save_note,
    save_view,
    toggle_expansion,
    view_state,
)
from assistant.work_canvas_view import CanvasCard, CanvasGroup, CanvasViewport
from assistant.work_window import ControlTask, WorkWindow
from automation.personal_work import (
    AddDocument,
    AddWebPage,
    Association,
    DismissWork,
    PersonalView,
    RefreshPersonalWork,
    RestoreWork,
    SaveWork,
    SourceKind,
    WorkDefinition,
    WorkSource,
    WorkThread,
    source_id,
)
from automation.task import Control
from automation.work_documents import LocalDocument, WebDocument, document_identity
from miryoku.layout import AGENT
lazy from assistant.work_canvas_detail import CardDetail, NoteDetail, QuestionDetail, SourceDetail, UpdateDetail, WorkDetail


class PersonalPanel:
    def __init__(self, parent: QtWidgets.QWidget, work: WorkWindow, canvas: WorkCanvas) -> None:
        self.work: WorkWindow = work
        self.work_canvas: WorkCanvas = canvas
        self.document: CanvasDocument = canvas.read()
        self.view: PersonalView = PersonalView()
        self.scope: CanvasScope = CanvasScope()
        self.projection: CanvasScene = project(self.view.catalog, self.document, self.scope)
        self.visible_cards: tuple[CanvasCard, ...] = ()
        self.editors: tuple[tuple[str, QtWidgets.QDialog], ...] = ()
        self.cards: tuple[CanvasCard, ...] = ()
        self.details: tuple[tuple[str, CardDetail], ...] = ()
        self.group_frames: tuple[CanvasGroup, ...] = ()
        self.group_cache: tuple[CanvasGroup, ...] = ()
        self.connection_paths: tuple[ConnectionPath, ...] = ()
        self.rendered: tuple[PersonalView, CanvasDocument, CanvasScope] | None = None
        self.selected: str | None = None
        self.linking: WorkThread | None = None
        self.draft: WorkDetail | None = None
        self.draft_proxy: QtWidgets.QGraphicsProxyWidget | None = None
        self.draft_known: frozenset[str] = frozenset()
        self.positioned: bool = False
        self.focus_timer: QtCore.QTimer | None = None
        self.instruction_run: CanvasRun | None = None
        self.frame: CanvasSurface = CanvasSurface(parent)
        self.frame.setStyleSheet(CANVAS_STYLE)
        layout = column(self.frame)
        self.layout: QtWidgets.QVBoxLayout = layout
        layout.setContentsMargins(8, 8, 8, 8)
        self.scene: QtWidgets.QGraphicsScene = QtWidgets.QGraphicsScene(self.frame)
        self.scene.setSceneRect(-2000, -2000, 10000, 10000)
        self.canvas: CanvasViewport = CanvasViewport(self.scene)
        self.interaction: CanvasInteraction = CanvasInteraction(self)
        layout.addWidget(self.canvas)
        self.create_context_controls()
        self.create_status()
        self.frame.resized.connect(self.position_chrome)
        self.canvas.resized.connect(self.reflow)
        self.update_voice_context()

    def create_context_controls(self) -> None:
        self.menu: QtWidgets.QMenu = QtWidgets.QMenu(self.frame)
        self.contents_action: QtGui.QAction = self.menu.addAction("Collapse containers", self.toggle_contents)
        arranging = self.menu.addMenu("Arrange")
        arranging.addAction("Arrange threads", self.reflow)
        arranging.addAction("Arrange all, including moved bubbles", self.release_positions)
        self.menu.addSeparator()
        self.menu.addAction("Refresh sources", self.refresh)
        adding = self.menu.addMenu("Add")
        adding.addAction("New work context", self.create)
        adding.addAction("New group", self.create_group)
        adding.addAction("Note", self.create_note)
        adding.addAction("Document…", self.create_document)
        adding.addAction("Document link…", self.create_document_link)
        adding.addAction("Web reference…", self.create_web_reference)
        self.dismissed_menu: QtWidgets.QMenu = self.menu.addMenu("Dismissed work")
        self.menu.aboutToShow.connect(self.refresh_dismissed)
        connections = self.menu.addMenu("Connections")
        connections.addAction("Connect source to this work", self.start_connection)
        connections.addAction("Put selected piece inside…", self.choose_group)
        self.toolbar: CanvasToolbar = CanvasToolbar(self.frame)
        heading = row(self.toolbar)
        self.toolbar_layout: QtWidgets.QHBoxLayout = heading
        heading.setContentsMargins(12, 6, 12, 6)
        heading.setSpacing(4)
        self.create_voice_controls()
        self.search_button: QtWidgets.QToolButton = icon_button("search", "Find on canvas (Ctrl+F)", self.toggle_search)
        self.search_button.setCheckable(True)
        heading.addWidget(self.search_button)
        self.search: QtWidgets.QLineEdit = QtWidgets.QLineEdit(self.toolbar)
        self.search.setObjectName("canvasSearch")
        self.search.setPlaceholderText("Find on canvas")
        self.search.setAccessibleName("Find on canvas")
        self.search.setFixedWidth(200)
        self.search.hide()
        self.search.returnPressed.connect(self.find)
        heading.addWidget(self.search)
        self.find_shortcut: QtGui.QShortcut = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Find, self.frame)
        self.find_shortcut.activated.connect(self.show_search)
        self.center_button: QtWidgets.QToolButton = icon_button("center", "Center this canvas", self.fit)
        heading.addWidget(self.center_button)
        self.questions_button: QtWidgets.QToolButton = icon_button("chat", "Agent clarifications", self.show_questions)
        heading.addWidget(self.questions_button)
        self.menu_button: QtWidgets.QToolButton = icon_button("more", "Canvas options", self.open_menu)
        heading.addWidget(self.menu_button)
        self.context_popup: QtWidgets.QMenu = QtWidgets.QMenu(self.frame)

    def create_voice_controls(self) -> None:
        self.voice_hint: VoiceLegend = VoiceLegend(PHYSICAL_NAMES[AGENT])
        self.toolbar_layout.addWidget(self.voice_hint)
        self.clear_context: QtWidgets.QToolButton = icon_button("close", "Ask about the whole canvas", self.clear_selection)
        self.clear_context.setFixedSize(20, 20)
        self.clear_context.setIconSize(QtCore.QSize(12, 12))
        self.clear_context.setStyleSheet("QToolButton { padding: 0; }")
        self.clear_context.hide()
        self.toolbar_layout.addWidget(self.clear_context)

    def create_status(self) -> None:
        self.status: QtWidgets.QLabel = label("", "muted")
        self.status.setParent(self.frame)

    def update_voice_context(self) -> None:
        current = topology(self.view.catalog, self.document).by_id.get(self.selected) if self.selected is not None else None
        context = container_title(current) if current is not None else "whole canvas"
        self.voice_hint.setToolTip(
            "Ask agent · " + context + "\nHold " + PHYSICAL_NAMES[AGENT] + " with Workspace's layout enabled; release to send."
        )
        self.clear_context.setVisible(current is not None)
        self.position_chrome()

    def clear_selection(self) -> None:
        self.selected = None
        self.update_voice_context()
        for bubble in self.bubbles():
            bubble.setSelected(False)
        for path in self.connection_paths:
            path.highlight(None)

    def send_instruction(self, text: str) -> bool:
        try:
            intent = CanvasInstruction(text)
        except ValueError as error:
            self.status.setText(str(error))
            return False
        pending = self.instruction_run
        if pending is None or pending.intent != intent:
            pending = CanvasRun("canvas:instruction:" + uuid4().hex, self.selected or ROOT_CONTEXT, intent)
        try:
            started = self.work_canvas.start(pending)
        except (OSError, ValueError, sqlite3.Error) as error:
            self.work.problem("The local canvas could not be saved: " + str(error))
            return False
        self.document = started.document
        match started:
            case NotQueued(reason=reason):
                # Retrying reuses this saved binding instead of adding another.
                self.instruction_run = pending
                self.status.setText("Could not queue the instruction: " + reason)
                return False
            case Queued():
                self.instruction_run = None
                self.status.setText("Instruction queued. The agent will build on this canvas.")
                return True

    def position_chrome(self) -> None:
        self.contents_action.setText("Show group contents" if self.scope.mode is CanvasMode.CONTEXTS else "Collapse containers")
        self.toolbar_layout.activate()
        self.toolbar.adjustSize()
        self.toolbar.move((self.frame.width() - self.toolbar.width()) // 2, self.frame.height() - self.toolbar.height() - 24)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setGeometry(24, self.toolbar.y() - 28, self.frame.width() - 48, 20)
        for widget in (self.toolbar, self.status):
            widget.raise_()
        if (self.visible_cards or self.group_frames) and not self.positioned:
            self.home()

    def open_menu(self) -> None:
        self.menu.popup(self.menu_button.mapToGlobal(self.menu_button.rect().topLeft()) - QtCore.QPoint(0, self.menu.sizeHint().height()))

    def toggle_search(self) -> None:
        if self.search.isHidden():
            self.show_search()
        else:
            self.hide_search()

    def show_search(self) -> None:
        self.search.show()
        self.search_button.setChecked(True)
        self.position_chrome()
        self.search.setFocus()
        self.search.selectAll()

    def hide_search(self) -> None:
        self.search.hide()
        self.search_button.setChecked(False)
        self.position_chrome()
        self.canvas.setFocus()

    def find(self) -> None:
        query = self.search.text().strip().casefold()
        match_item = next(
            (item for item in containers(self.view.catalog, self.document) if query and query in (item.id + " " + container_title(item)).casefold()),
            None,
        )
        if match_item is not None:
            self.open_at(match_item.id)
            self.hide_search()
        elif query:
            self.status.setText("No matching information on this canvas")

    def home(self) -> None:
        if self.frame.width() < 300 or not (self.visible_cards or self.group_frames):
            return
        bounds = self.scene.itemsBoundingRect()
        left, top = bounds.left(), bounds.top()
        self.canvas.setTransform(QtGui.QTransform().scale(0.9, 0.9))
        self.canvas.centerOn(left + self.canvas.viewport().width() / 1.8 - 42, top + self.canvas.viewport().height() / 1.8 - 110)
        self.positioned = True

    def commit(self, document: CanvasDocument) -> bool:
        if document == self.document:
            return True
        try:
            self.work_canvas.save(document)
        except (OSError, ValueError, sqlite3.Error) as error:
            self.work.problem("The local canvas could not be saved: " + str(error))
            return False
        self.document = document
        return True

    def sync_cards(self, content: tuple[CanvasContent, ...], visible: frozenset[str]) -> None:
        """Qt retains created bubbles/drafts and materializes only visible pieces."""
        identities = frozenset(item.id for item in content)
        for removed in self.cards:
            if removed.content.id not in identities and removed.scene() is self.scene:
                self.scene.removeItem(removed)
        self.cards = tuple(card for card in self.cards if card.content.id in identities)
        for item in content:
            card = self.card(item.id)
            if card is None:
                if item.id not in visible:
                    continue
                card = CanvasCard(item, self)
                position = next((position for position in self.document.placements if position.id == item.id), None)
                if position is not None:
                    card.setPos(position.x, position.y)
                self.cards = (*self.cards, card)
            elif card.content != item:
                # Content updates preserve native identity, positions and drafts.
                card.refresh(item)
            if item.id in visible and card.scene() is not self.scene:
                self.scene.addItem(card)
            elif item.id not in visible and card.scene() is self.scene:
                self.scene.removeItem(card)
            self.refresh_detail(item)
        self.visible_cards = tuple(card for card in self.cards if card.content.id in visible)

    def render(self, view: PersonalView) -> None:
        self.status.setToolTip(view.status)
        self.status.setText("" if not self.linking else "Select a source to connect")
        if self.rendered == (view, self.document, self.scope):
            return
        self.interaction.cancel()
        self.view = view
        indexed = topology(view.catalog, self.document)
        retained = frozenset(indexed.by_id)
        if self.selected not in retained:
            self.selected = None
        self.update_voice_context()
        self.group_cache = tuple(group for group in self.group_cache if group.context.id in retained)
        for identity, dialog in self.editors:
            if identity not in retained:
                dialog.hide()
        self.editors = tuple(pair for pair in self.editors if pair[0] in retained)
        self.details = tuple(pair for pair in self.details if pair[0] in retained)
        self.projection = project(view.catalog, self.document, self.scope)
        self.scope = self.projection.scope
        visible = frozenset(item.id for item in scene_contents(self.projection))
        self.sync_cards(indexed.pieces, visible)
        groups = frozendict((group.id, group) for root in self.projection.groups for group in descendants(root))
        for card in self.cards:
            group = groups.get(card.content.id)
            count = len(indexed.memberships[card.content.id]) + sum(
                collection.parent_id == card.content.id for collection in self.document.collections
            )
            card.set_contents(count, expanded=group.expanded if group is not None else self.scope.identity == card.content.id)
        for identity, editor in self.details:
            match editor:
                case WorkDetail():
                    current_work = next((item for item in view.catalog.works if item.id == identity), None)
                    if current_work is not None:
                        editor.refresh(current_work)
                case _:
                    pass
        pending = len(tuple(self.pending_questions()))
        self.questions_button.setToolTip(f"{pending} needs your input" if pending else "Agent clarifications")
        self.questions_button.setAccessibleName(self.questions_button.toolTip())
        self.reflow()
        self.position_chrome()
        self.canvas.setSceneRect(self.scene.itemsBoundingRect().adjusted(-1500, -1500, 1500, 1500))
        if not self.positioned and (self.visible_cards or self.group_frames):
            self.home()
        self.reconcile_draft()
        self.rendered = (view, self.document, self.scope)

    def reconcile_draft(self) -> None:
        if self.draft is not None and self.draft.pending is not None:
            saved = next(
                (item for item in self.view.catalog.works if item.id not in self.draft_known and item.definition == self.draft.pending.definition),
                None,
            )
            if saved is not None:
                self.cancel_create()
                self.open_context(saved.id)

    def refresh_detail(self, item: CanvasContent) -> None:
        detail = self.detail(item.id)
        match detail, item:
            case SourceDetail() as source, WorkSource() as current:
                source.refresh(current, self.view.catalog, self.document)
            case UpdateDetail() as editor, (CanvasUpdate() | CanvasAction()) as current:
                editor.refresh(current)
            case QuestionDetail() as editor, CanvasQuestion() as current:
                previous_height = editor.frame.height()
                editor.refresh(current)
                card = self.card(item.id)
                if card is not None and editor.frame.height() != previous_height:
                    card.relayout()
            case _:
                pass

    def card(self, identity: str) -> CanvasCard | None:
        return next((card for card in self.cards if card.content.id == identity), None)

    def detail(self, identity: str) -> CardDetail | None:
        return next((detail for key, detail in self.details if key == identity), None)

    def select(self, identity: str) -> None:
        self.selected = identity
        self.update_voice_context()
        card = self.card(identity)

        if self.linking is not None and card is not None:
            match card.content:
                case WorkSource() as source:
                    work, self.linking = self.linking, None
                    reason, accepted = QtWidgets.QInputDialog.getText(self.frame, "Connect source", "Why does this source belong to this work?")
                    if accepted and reason.strip():
                        links = (*work.links, Association(source.id, reason.strip()))
                        self.work.send(SaveWork(work.definition, links, work.id, work.revision))
                case _:
                    self.status.setText("Choose an Outlook, Teams, Kanban or document bubble to connect.")
        for item in self.bubbles():
            item.setSelected(item.identity == identity)
        for path in self.connection_paths:
            path.highlight(identity)

    def locate(self, identity: str) -> None:
        cancel(self.focus_timer)
        self.focus_timer = None
        bubble = next((bubble for bubble in self.bubbles() if bubble.identity == identity), None)
        if bubble is not None:
            self.select(identity)
            bounds = bubble.sceneBoundingRect()
            visible_height = self.canvas.viewport().height() / self.canvas.transform().m11()
            self.canvas.centerOn(bounds.center().x(), bounds.top() + min(bounds.height() / 2, visible_height / 2 - 100))

    def queue_location(self, identity: str) -> None:
        cancel(self.focus_timer)
        self.focus_timer = later(self.frame, 0, lambda: self.locate(identity))

    def inspect(self, identity: str) -> None:
        work = next((item for item in self.view.catalog.works if item.id == identity), None)
        if work is not None:
            self.edit_work(work)
            return
        card = self.card(identity)
        if card is None:
            return
        self.select(identity)
        detail = self.detail(identity)
        if detail is None:
            match card.content:
                case WorkSource() as content:
                    detail = SourceDetail(self.work, content, on_context=self.open_context)
                    detail.refresh(content, self.view.catalog, self.document)
                case CanvasNote() as content:
                    detail = NoteDetail(content, self.save_note)
                case CanvasUpdate() | CanvasAction() as content:
                    detail = UpdateDetail(content, self.open_at)
                case CanvasQuestion() as content:
                    detail = QuestionDetail(content)
            self.details = (*self.details, (identity, detail))
        match detail:
            case SourceDetail():
                contextual_work = next(
                    (
                        identity
                        for identity in reversed(context_path(identity, self.view.catalog, self.document))
                        if any(work.id == identity for work in self.view.catalog.works)
                    ),
                    None,
                )
                if contextual_work is not None:
                    detail.select_context(contextual_work)
            case _:
                pass
        card.show_detail(detail.frame)
        self.canvas.ensureVisible(card, 30, 30)

    def edit_work(self, work: WorkThread) -> None:
        detail = self.detail(work.id)
        dialog = next((window for identity, window in self.editors if identity == work.id), None)
        if detail is None:
            detail = WorkDetail(self.work, work, on_continue=lambda: self.study_work(work.id))
            self.details = (*self.details, (work.id, detail))
            dialog = QtWidgets.QDialog(self.frame)
            dialog.setWindowTitle("Work context · " + work.definition.title)
            dialog.setStyleSheet(CANVAS_STYLE + "QDialog { background: #262337; }")
            dialog.resize(520, 540)
            layout = column(dialog)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.addWidget(detail.frame)
            self.editors = (*self.editors, (work.id, dialog))
        if dialog is not None:
            dialog.show()
            dialog.raise_()

    def bubbles(self) -> Iterator[CanvasBubble]:
        yield from self.visible_cards
        yield from self.group_frames

    def click_bubble(self, identity: str) -> None:
        match topology(self.view.catalog, self.document).by_id.get(identity):
            case WorkThread() | CanvasCollection() | CanvasInbox():
                self.toggle_bubble(identity)
            case _:
                self.inspect(identity)

    def capture_gesture_scene(self) -> GestureScene:
        groups = frozendict((group.id, group) for root in self.projection.groups for group in descendants(root))
        parents = frozendict(
            (identity, group.id)
            for group in groups.values()
            for identity in (*(child.id for child in group.children), *(piece.id for piece in group.items))
        )

        def target(bubble: CanvasBubble) -> BubbleTarget:
            bounds = bubble.sceneBoundingRect()
            group = groups.get(bubble.identity)
            members = (
                frozenset(identity for child in descendants(group) for identity in (child.id, *(piece.id for piece in child.pieces)))
                if group is not None
                else frozenset((bubble.identity,))
            )
            return BubbleTarget(bubble.identity, Box(bounds.x(), bounds.y(), bounds.width(), bounds.height()), parents.get(bubble.identity), members)

        return GestureScene(tuple(target(bubble) for bubble in self.bubbles()), self.scope.identity)

    def gesture_placements(self) -> tuple[Placement, ...]:
        return view_state(self.document, self.scope.identity).placements

    def gesture_status(self, text: str) -> None:
        self.status.setText(text)

    def apply_gesture(self, effect: GestureEffect) -> None:
        match effect:
            case NoChange():
                pass
            case ClickBubble(id=identity):
                self.click_bubble(identity)
            case PlaceBubbles() | NestBubble() as released:
                try:
                    self.document = self.work_canvas.commit_gesture(self.scope, released)
                except ValueError as error:
                    self.work.problem(str(error))
                    self.reflow()
                    return
                except (OSError, sqlite3.Error) as error:
                    self.work.problem("The local canvas could not be saved: " + str(error))
                    self.reflow()
                    return
                match released:
                    case PlaceBubbles():
                        self.reflow()
                    case NestBubble():
                        self.render(self.view)
            case ConnectBubbles(start=start, end=end):
                self.save_relation(CanvasRelation(start, end))
            case MovePreview() | RelationPreview():
                raise RuntimeError("Native previews belong to CanvasInteraction.")

    def save_relation(self, relation: CanvasRelation) -> None:
        self.commit(edited(self.document, UpdateCanvas(revision(self.document), (PutRelation(relation),)), self.view.catalog))
        self.draw_connections()
        self.status.setText("")

    def relation_action(self, relation: CanvasRelation) -> Callable[[], None]:
        def show() -> None:
            self.relation_menu(relation)

        return show

    def relation_menu(self, relation: CanvasRelation) -> None:
        self.context_popup.clear()
        self.context_popup.addAction("Edit relationship…", lambda: self.edit_relation(relation))
        self.context_popup.addAction("Remove relationship", lambda: self.remove_relation(relation))
        self.context_popup.popup(QtGui.QCursor.pos())

    def edit_relation(self, relation: CanvasRelation) -> None:
        reason, accepted = QtWidgets.QInputDialog.getText(self.frame, "Relationship", "Relationship", text=relation.reason)
        if accepted and reason.strip():
            self.save_relation(replace(relation, reason=reason.strip()[:1200]))

    def remove_relation(self, relation: CanvasRelation) -> None:
        self.commit(edited(self.document, UpdateCanvas(revision(self.document), (RemoveRelation(relation.start, relation.end),)), self.view.catalog))
        self.draw_connections()

    def reflow(self) -> None:
        for card in self.visible_cards:
            card.setRect(0, 0, card.own_size.width(), card.own_size.height())
            card.setZValue(10 if card.expanded else 1)
        measurements = Measurements(
            frozendict((card.content.id, Size(card.own_size.width(), card.own_size.height())) for card in self.visible_cards),
            max(380, self.canvas.viewport().width() / 0.9 - 84),
        )
        arranged = layout(self.projection, view_state(self.document, self.scope.identity), measurements)
        document = save_view(self.document, arranged.state)
        if document != self.document:
            self.commit(document)
        positions = frozendict((position.id, position) for position in arranged.state.placements)
        for card in self.visible_cards:
            position = positions[card.content.id]
            card.setPos(position.x, position.y)
        previous = frozendict((frame.context.id, frame) for frame in self.group_cache)
        retained = frozenset(frame.identity for frame in arranged.frames)
        for old_frame in self.group_frames:
            if old_frame.context.id not in retained:
                self.scene.removeItem(old_frame)
        current: tuple[CanvasGroup, ...] = ()
        groups = frozendict((group.id, group) for root in self.projection.groups for group in visible_groups(root))
        depth = frozendict((child.id, index) for root in self.projection.groups for index, level in enumerate(self.levels(root)) for child in level)
        for frame in arranged.frames:
            group = groups[frame.identity]
            box = frame.box
            bounds = QtCore.QRectF(box.x, box.y, box.width, box.height)
            if group.content is not None:
                container_card = self.card(group.id)
                if container_card is not None:
                    container_card.contain(bounds, depth[group.id] - len(groups) - 1)
                continue
            native = previous.get(frame.identity)
            if native is None:
                native = CanvasGroup(group, bounds, self)
                self.group_cache = (*self.group_cache, native)
            else:
                native.refresh(group, bounds)
            if native.scene() is not self.scene:
                self.scene.addItem(native)
            native.setZValue(depth[group.id] - len(groups) - 1)
            current = (*current, native)
        self.group_frames = current
        self.draw_connections()
        self.canvas.setSceneRect(self.scene.itemsBoundingRect().adjusted(-1500, -1500, 1500, 1500))

    def draw_connections(self) -> None:
        observed = connections(self.view.catalog, self.projection, self.document.relations)
        previous = frozendict((path.connection, path) for path in self.connection_paths)
        for path in self.connection_paths:
            if path.connection not in observed:
                self.scene.removeItem(path)
        current: tuple[ConnectionPath, ...] = ()
        for connection in observed:
            edge = previous.get(connection)
            if edge is None:
                edge = ConnectionPath(connection, self.relation_menu)
                self.scene.addItem(edge)
            edge.highlight(self.selected)
            current = (*current, edge)
        self.connection_paths = current
        self.update_connection_geometry()

    def update_connection_geometry(self) -> None:
        bounds = frozendict((bubble.identity, bubble.sceneBoundingRect()) for bubble in self.bubbles())
        for edge in self.connection_paths:
            edge.connect(bounds[edge.connection.start], bounds[edge.connection.end])

    def levels(self, root: ContextGroup) -> Iterator[tuple[ContextGroup, ...]]:
        level: tuple[ContextGroup, ...] = (root,)
        while level:
            yield level
            level = tuple(child for group in level if group.expanded for child in group.children)

    def escape(self) -> bool:
        if self.interaction.cancel():
            return True
        if not self.search.isHidden():
            self.hide_search()
            return True
        if self.selected is not None:
            card = self.card(self.selected)
            if card is not None and card.expanded:
                self.inspect(self.selected)
                return True
            group = next((group for root in self.projection.groups for group in descendants(root) if group.id == self.selected), None)
            if group is not None and group.expanded:
                self.toggle_bubble(self.selected)
                return True
        return False

    def release_positions(self) -> None:
        self.commit(save_view(self.document, CanvasViewState(self.scope.identity)))
        self.reflow()

    def reveal(self, identity: str) -> None:
        # A single scene owns all nested bubbles. Focusing reveals its ancestors
        # without replacing neighbors, saved pins or the scene's native objects.
        document = self.document
        for ancestor in context_path(identity, self.view.catalog, document):
            document = toggle_expansion(document, None, ancestor, expanded=True)
        self.commit(document)
        self.scope = CanvasScope()
        self.render(self.view)

    def open_context(self, identity: str) -> None:
        if not context_path(identity, self.view.catalog, self.document):
            return
        self.reveal(identity)
        card = self.card(identity)
        if card is not None and not card.expanded:
            self.inspect(identity)
        self.canvas.setTransform(QtGui.QTransform().scale(0.9, 0.9))
        self.locate(identity)
        self.queue_location(identity)

    def toggle_contents(self) -> None:
        mode = CanvasMode.CONTEXTS if self.scope.mode is CanvasMode.CONTENTS else CanvasMode.CONTENTS
        self.scope = replace(self.scope, mode=mode)
        self.positioned = False
        self.render(self.view)
        self.home()

    def context_menu(self, identity: str) -> None:
        self.select(identity)
        self.context_popup.clear()
        self.context_popup.addAction("Focus bubble", lambda: self.open_context(identity))
        self.context_popup.addAction("Show / hide contents", lambda: self.toggle_bubble(identity))
        self.context_popup.addAction("Connect to another bubble…", lambda: self.interaction.start_relation(identity))
        current = next((item for item in containers(self.view.catalog, self.document) if item.id == identity), None)
        match current:
            case WorkThread():
                self.context_popup.addAction("Continue with agent", lambda: self.study_work(identity))
                self.context_popup.addAction("Edit work context", lambda: self.inspect(identity))
                self.context_popup.addAction("Dismiss work", lambda: self.dismiss_work(identity, "Dismissed by the user."))
                self.context_popup.addAction("This isn't my work", lambda: self.dismiss_work(identity, "This is not my responsibility."))
            case CanvasCollection():
                self.context_popup.addAction("Rename group", lambda: self.rename_group(identity))
            case _:
                pass
        self.context_popup.addAction("Put inside another bubble…", self.choose_group)
        self.context_popup.addAction("Move to canvas", lambda: self.add_to_group(None, identity))
        related = tuple(relation for relation in self.document.relations if identity in (relation.start, relation.end))
        if related:
            menu = self.context_popup.addMenu("Relationships")
            for relation in related:
                menu.addAction(relation.reason, self.relation_action(relation))
        self.context_popup.popup(QtGui.QCursor.pos())

    def create_group(self) -> None:
        title, accepted = QtWidgets.QInputDialog.getText(self.frame, "New canvas group", "Group name")
        if accepted and title.strip():
            group = CanvasCollection("group:" + uuid4().hex, title.strip(), parent_id=self.selected)
            self.commit(save_collection(self.document, group))
            self.render(self.view)
            self.open_context(group.id)

    def rename_group(self, identity: str) -> None:
        group = next((group for group in self.document.collections if group.id == identity), None)
        if group is not None:
            title, accepted = QtWidgets.QInputDialog.getText(self.frame, "Rename canvas group", "Group name", text=group.title)
            if accepted and title.strip():
                self.commit(save_collection(self.document, replace(group, title=title.strip())))
                self.render(self.view)

    def choose_group(self) -> None:
        if self.selected is None:
            self.status.setText("Select a piece or use a context's menu first.")
            return
        groups = tuple(item for item in containers(self.view.catalog, self.document) if item.id != self.selected)
        if not groups:
            self.status.setText("Add another piece before nesting this one.")
            return
        labels = tuple(container_title(group) + " · " + group.id[-8:] for group in groups)
        choice, accepted = QtWidgets.QInputDialog.getItem(self.frame, "Nest selected piece", "Put inside", labels, editable=False)
        if accepted:
            self.add_to_group(groups[labels.index(choice)].id, self.selected)

    def add_to_group(self, group_id: str | None, identity: str) -> None:
        try:
            visible = next((bubble for bubble in self.capture_gesture_scene().bubbles if bubble.id == identity), None)
            members = (
                visible.members
                if visible is not None
                else frozenset(item for item, path in topology(self.view.catalog, self.document).paths.items() if identity in path)
            )
            document = release_subtree(nest(self.document, group_id, identity), members | {identity})
            project(self.view.catalog, document, self.scope)
        except ValueError as error:
            self.work.problem(str(error))
            return
        self.commit(document)
        self.render(self.view)

    def pending_questions(self) -> Iterator[CanvasQuestion]:
        for item in topology(self.view.catalog, self.document).pieces:
            match item:
                case CanvasQuestion(reply=Attention.WAITING):
                    yield item
                case _:
                    pass

    def show_questions(self) -> None:
        questions = tuple(self.pending_questions())
        pending = next((item for item in questions if item.id != self.selected), questions[0] if questions else None)
        if pending is not None:
            self.open_at(pending.id)

    def open_at(self, identity: str) -> None:
        match topology(self.view.catalog, self.document).by_id.get(identity):
            case WorkThread() | CanvasCollection() | CanvasInbox():
                self.open_context(identity)
                return
            case None:
                return
            case _:
                self.reveal(identity)
        card = self.card(identity)
        if card is None or card not in self.visible_cards:
            return
        match card.content:
            case CanvasQuestion() if not card.expanded:
                self.inspect(identity)
            case _:
                pass
        self.canvas.setTransform(QtGui.QTransform().scale(0.9, 0.9))
        self.locate(identity)
        # First-show resize events can reflow after the redirect.
        self.queue_location(identity)

    def toggle_bubble(self, identity: str) -> None:
        group = next((group for root in self.projection.groups for group in descendants(root) if group.id == identity), None)
        if group is not None:
            self.commit(toggle_expansion(self.document, self.scope.identity, identity, expanded=not group.expanded))
            self.scope = replace(self.scope, mode=CanvasMode.CONTENTS)
            self.render(self.view)
            revised = next((item for root in self.projection.groups for item in descendants(root) if item.id == identity), None)
            if not group.expanded and revised is not None and not revised.expanded:
                self.open_context(identity)
            else:
                self.locate(identity)

    def study_work(self, identity: str) -> None:
        try:
            continued = self.work_canvas.continue_work(identity)
        except (OSError, ValueError, sqlite3.Error) as error:
            self.work.problem("The local canvas could not be saved: " + str(error))
            return
        match continued:
            case ResumeTask(task_id=task):
                self.work.send(ControlTask(task, Control.RESUME))
            case Investigating.ALREADY:
                self.status.setText("This work already has an investigation; open Agent tasks to inspect its progress or required input.")
            case Queued(document=document):
                self.document = document
            case NotQueued(document=document, reason=reason):
                self.document = document
                self.status.setText("Could not queue the investigation: " + reason)

    def start_connection(self) -> None:
        work = next((work for work in self.view.catalog.works if work.id == self.selected), None)
        if work is not None:
            self.linking = None if self.linking is not None else work
            self.status.setText("Select a source bubble to connect." if self.linking is not None else "Connection cancelled.")
        else:
            self.status.setText("Select a work bubble before connecting a source.")

    def refresh(self) -> None:
        self.work.send(RefreshPersonalWork.REFRESH)

    def fit(self) -> None:
        cancel(self.focus_timer)
        self.focus_timer = None
        if self.visible_cards or self.group_frames:
            # The floating toolbar consumes visible space without resizing the
            # scene. Fit into the remaining viewport so it covers no bubbles.
            bounds = self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
            clearance = self.toolbar.height() + 64
            width = max(1, self.canvas.viewport().width() - 48)
            height = max(1, self.canvas.viewport().height() - clearance)
            scale = min(width / bounds.width(), height / bounds.height())
            self.canvas.setTransform(QtGui.QTransform().scale(scale, scale))
            self.canvas.centerOn(bounds.center().x(), bounds.center().y() + clearance / (2 * scale))

    def create(self) -> None:
        if self.draft_proxy is not None:
            self.canvas.centerOn(self.draft_proxy)
            return
        self.draft_known = frozenset(item.id for item in self.view.catalog.works)
        self.draft = WorkDetail(self.work, WorkDefinition("New work", "Describe the outcome you are working towards."))
        frame = QtWidgets.QWidget()
        frame.setStyleSheet(CANVAS_STYLE + "QWidget { background: #262337; }")
        frame.setFixedWidth(400)
        layout = column(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(label("New work", "title"))
        layout.addWidget(self.draft.frame)
        layout.addWidget(button("Discard new work", self.cancel_create))
        self.draft_proxy = self.scene.addWidget(frame)
        self.draft_proxy.setZValue(20)
        point = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        self.draft_proxy.setPos(point.x() - 200, point.y() - 260)
        self.canvas.ensureVisible(self.draft_proxy)
        self.draft.title.setFocus()

    def cancel_create(self) -> None:
        if self.draft_proxy is not None:
            self.scene.removeItem(self.draft_proxy)
            self.draft_proxy.deleteLater()
            self.draft_proxy = None
        self.draft = None

    def create_note(self) -> None:
        note = CanvasNote("note:" + uuid4().hex, "New note", context_id=self.selected)
        point = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        document = save_note(self.document, note)
        self.commit(document)
        self.render(self.view)
        self.apply_gesture(PlaceBubbles(note.id, (Placement(note.id, point.x() - 180, point.y() - 140),)))
        self.inspect(note.id)

    def save_note(self, note: CanvasNote) -> None:
        try:
            document = save_note(self.document, note)
        except ValueError as error:
            self.work.problem(str(error))
            return
        self.commit(document)
        self.render(self.view)

    def create_document(self) -> None:
        path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(self.frame, "Add document to canvas", "", "Documents (*);;Text (*.txt *.md)")
        if path:
            file = Path(path)
            preview = ""
            if file.suffix.casefold() in (".txt", ".md", ".csv", ".log"):
                try:
                    with file.open(encoding="utf-8-sig", errors="replace") as stream:
                        preview = stream.read(6000)
                except OSError as error:
                    self.work.problem("Could not read the document preview: " + str(error))
            self.add_document(AddDocument(file.name[:240], LocalDocument(path), preview))

    def create_document_link(self) -> None:
        url, accepted = QtWidgets.QInputDialog.getText(self.frame, "Add document link", "Document URL")
        if accepted and url.strip():
            title, accepted = QtWidgets.QInputDialog.getText(self.frame, "Document title", "Name on canvas")
            if accepted and title.strip():
                try:
                    self.add_document(AddDocument(title.strip(), WebDocument(url.strip())))
                except ValueError as error:
                    self.work.problem(str(error))

    def create_web_reference(self) -> None:
        url, accepted = QtWidgets.QInputDialog.getText(self.frame, "Add web reference", "Page URL")
        if accepted and url.strip():
            title, accepted = QtWidgets.QInputDialog.getText(self.frame, "Web reference title", "Name on canvas")
            if accepted and title.strip():
                try:
                    self.add_document(AddWebPage(title.strip(), WebDocument(url.strip())))
                except ValueError as error:
                    self.work.problem(str(error))

    def dismiss_work(self, identity: str, reason: str) -> None:
        work = next((item for item in self.view.catalog.works if item.id == identity), None)
        if work is not None:
            self.work.send(DismissWork(work.id, work.revision, reason))

    def refresh_dismissed(self) -> None:
        self.dismissed_menu.clear()
        self.dismissed_menu.setEnabled(bool(self.view.catalog.dismissed))
        for dismissed in self.view.catalog.dismissed:
            action = self.dismissed_menu.addAction("Restore · " + dismissed.work.definition.title)
            action.setToolTip(dismissed.reason)
            action.triggered.connect(self.restore_work(dismissed.work.id))

    def restore_work(self, identity: str) -> Callable[[], None]:
        def restore() -> None:
            self.work.send(RestoreWork(identity))

        return restore

    def add_document(self, command: AddDocument | AddWebPage) -> None:
        work_id = next(
            (
                identity
                for identity in reversed(context_path(self.selected, self.view.catalog, self.document) if self.selected else ())
                if any(work.id == identity for work in self.view.catalog.works)
            ),
            None,
        )
        if self.work.send(replace(command, work_id=work_id)) and self.selected is not None and self.selected != work_id:
            match command:
                case AddWebPage():
                    kind = SourceKind.WEB_PAGE
                case AddDocument():
                    kind = SourceKind.DOCUMENT
            identity = source_id(kind, document_identity(command.reference.url))
            self.commit(nest(self.document, self.selected, identity))


# Qt owns pointer capture and previews; immutable decisions own the gestures.
# No document/layout work occurs during pointer movement. The panel applies
# the single immutable commit effect on release.
class CanvasInteraction:
    def __init__(self, owner: PersonalPanel) -> None:
        self.owner: PersonalPanel = owner
        self.gesture: Gesture = Idle.READY
        self.gesture_scene: GestureScene = GestureScene((), None)
        self.relation_preview: QtWidgets.QGraphicsPathItem | None = None

    def press_bubble(self, identity: str, point: ScenePoint) -> None:
        match self.gesture:
            case DrawingRelation():
                return
            case _:
                self.gesture_scene = self.owner.capture_gesture_scene()
        target = next(bubble for bubble in self.gesture_scene.bubbles if bubble.id == identity)
        state = self.owner.gesture_placements()
        positions = tuple(position for position in state if position.id in target.members)
        drag = BubbleDrag(identity, point, positions, target.parent_id, target.members)
        self.gesture = transition(self.gesture, PressBubble(drag), self.gesture_scene).state

    def pointer(self, event: PointerMoved | PointerReleased | PressConnector) -> None:
        match event:
            case PressConnector():
                self.gesture_scene = self.owner.capture_gesture_scene()
            case PointerMoved(point=point):
                event = PointerMoved(point, QtWidgets.QApplication.startDragDistance() / self.owner.canvas.transform().m11())
            case _:
                pass
        result = transition(self.gesture, event, self.gesture_scene)
        self.gesture = result.state
        match result.effect:
            case MovePreview(positions=positions, target_id=target):
                indexed = frozendict((position.id, position) for position in positions)
                for bubble in self.owner.bubbles():
                    position = indexed.get(bubble.identity)
                    if position is not None:
                        bubble.setPos(position.x, position.y)
                    bubble.highlight_drop(active=bubble.identity == target)
                self.owner.update_connection_geometry()
            case RelationPreview(source_id=identity, point=point, target_id=target):
                self.preview_relation(identity, point)
                for bubble in self.owner.bubbles():
                    bubble.highlight_drop(active=bubble.identity == target)
            case _ as effect:
                self.owner.apply_gesture(effect)
        match result.state:
            case Idle():
                self.clear_gesture_preview()
            case _:
                pass

    def clear_gesture_preview(self) -> None:
        if self.relation_preview is not None:
            self.owner.scene.removeItem(self.relation_preview)
            self.relation_preview = None
        for bubble in self.owner.bubbles():
            bubble.highlight_drop(active=False)

    def preview_relation(self, identity: str, point: ScenePoint) -> None:
        source = next(bubble for bubble in self.owner.bubbles() if bubble.identity == identity)
        first = source.mapToScene(source.connector.pos())
        if self.relation_preview is None:
            self.relation_preview = QtWidgets.QGraphicsPathItem()
            pen = QtGui.QPen(QtGui.QColor("#c4a5e8"), 2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self.relation_preview.setPen(pen)
            self.relation_preview.setZValue(30)
            self.relation_preview.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.owner.scene.addItem(self.relation_preview)
        path = QtGui.QPainterPath(first)
        path.lineTo(point.x, point.y)
        self.relation_preview.setPath(path)

    def start_relation(self, identity: str) -> None:
        self.clear_gesture_preview()
        source = next(bubble for bubble in self.owner.bubbles() if bubble.identity == identity)
        point = source.mapToScene(source.connector.pos())
        self.pointer(PressConnector(identity, ScenePoint(point.x(), point.y())))
        self.owner.gesture_status("Click another bubble to connect; Escape cancels.")

    def cancel(self) -> bool:
        match self.gesture:
            case Idle():
                return False
            case _:
                result = transition(self.gesture, CancelGesture.CANCEL, self.gesture_scene)
                self.gesture = result.state
                match result.effect:
                    case MovePreview(positions=positions):
                        indexed = frozendict((position.id, position) for position in positions)
                        for bubble in self.owner.bubbles():
                            position = indexed.get(bubble.identity)
                            if position is not None:
                                bubble.setPos(position.x, position.y)
                        self.owner.update_connection_geometry()
                    case _:
                        pass
                self.clear_gesture_preview()
                self.owner.gesture_status("")
                return True
