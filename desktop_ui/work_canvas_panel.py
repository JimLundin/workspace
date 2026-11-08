"""Local native work canvas backed by the saved work/source catalog.

Qt owns mutable graphics and editor lifetimes. Cards/details/groups are tuples;
positions and notes have their own local document, outside agent model input.
"""

import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import assert_never
from uuid import uuid4

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from cell import Cell
from contracts.canvas_activity import ROOT_CONTEXT, Attention, CanvasAction, CanvasInstruction, CanvasQuestion, CanvasRun, CanvasUpdate
from contracts.meetings import MeetingConversation
from contracts.personal_work import (
    AddDocument,
    AddWebPage,
    Association,
    DismissWork,
    DocumentSource,
    KanbanSource,
    MeetingSource,
    OutlookSource,
    PersonalView,
    RefreshPersonalWork,
    RestoreWork,
    SaveWork,
    TeamsSource,
    WebPageSource,
    WorkDefinition,
    WorkThread,
    reference_id,
)
from contracts.task import Control
from contracts.work_canvas_commands import PutRelation, RemoveRelation
from contracts.work_canvas_context import (
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
from contracts.work_canvas_contracts import CanvasEdits, Investigating, NotQueued, Queued, ResumeTask
from contracts.work_canvas_edits import (
    AddGroup,
    ArrangeView,
    Change,
    NestBubble,
    PlaceBubbles,
    PutInside,
    ReleasePositions,
    RenameGroup,
    Reveal,
    SaveNote,
    SetExpansion,
    UserEdit,
)
from contracts.work_canvas_model import (
    CanvasCollection,
    CanvasContent,
    CanvasDocument,
    CanvasNote,
    CanvasRelation,
    Placement,
    view_state,
)
from contracts.work_commands import ControlTask
from contracts.work_documents import LocalDocument, WebDocument
from desktop_ui import ui_spec
from desktop_ui.canvas_toolbar import (
    Act,
    Bubble,
    BubbleAction,
    CanvasTool,
    CanvasToolbarSpec,
    Dismissed,
    OnBubble,
    OnCanvas,
    OnRelationship,
    Open,
    RelationAction,
    Relationship,
    Restore,
    Role,
    Subject,
    row,
    sections,
)
from desktop_ui.components.appearance import GLASS_ACCENT, Tokens
from desktop_ui.components.canvas_bubble import CanvasBubble
from desktop_ui.components.canvas_chrome import CanvasFrame, CanvasSurface, CanvasToolbar, GlassCapsule, ScrollEdge, content_style
from desktop_ui.components.canvas_connection import ConnectionPath
from desktop_ui.components.canvas_look import CARD_RADIUS, SHADOW
from desktop_ui.components.controls import button, label
from desktop_ui.components.meaning import Tint
from desktop_ui.components.voice_legend import VoiceLegend
from desktop_ui.components.widgets import column
from desktop_ui.keymap import AGENT_HOLD
from desktop_ui.qt_ui import cancel, later
from desktop_ui.work_canvas_connections import connections
from desktop_ui.work_canvas_gestures import (
    BubbleDrag,
    BubbleTarget,
    CancelGesture,
    ClickBubble,
    ConnectBubbles,
    DrawingRelation,
    Gesture,
    GestureEffect,
    GestureInput,
    GestureResult,
    GestureScene,
    Idle,
    MovePreview,
    NoChange,
    PointerMoved,
    PointerReleased,
    PressBubble,
    PressConnector,
    RelationPreview,
    transition,
)
from desktop_ui.work_canvas_layout import Box, Measurements, ScenePoint, Size, layout
from desktop_ui.work_canvas_view import CanvasCard, CanvasGroup, CanvasViewport
from desktop_ui.work_window import WorkWindow
lazy from desktop_ui.work_canvas_detail import CardDetail, NoteDetail, QuestionDetail, SourceDetail, UpdateDetail, WorkDetail


@dataclass(frozen=True, slots=True)
class WindowControls:
    """The canvas window's own actions, offered in its toolbar."""

    maximize: Callable[[], None]
    close: Callable[[], None]


@dataclass(frozen=True, slots=True)
class _Canvas:
    document: CanvasDocument
    projection: CanvasScene
    last_spec: CanvasToolbarSpec
    """The toolbar's last good spec; a broken edit keeps it."""
    view: PersonalView = field(default_factory=PersonalView)
    scope: CanvasScope = field(default_factory=CanvasScope)
    visible_cards: tuple[CanvasCard, ...] = ()
    editors: tuple[tuple[str, QtWidgets.QDialog], ...] = ()
    cards: tuple[CanvasCard, ...] = ()
    details: tuple[tuple[str, CardDetail], ...] = ()
    group_frames: tuple[CanvasGroup, ...] = ()
    group_cache: tuple[CanvasGroup, ...] = ()
    connection_paths: tuple[ConnectionPath, ...] = ()
    rendered: tuple[PersonalView, CanvasDocument, CanvasScope] | None = None
    selected: str | None = None
    linking: WorkThread | None = None
    draft: WorkDetail | None = None
    draft_proxy: QtWidgets.QGraphicsProxyWidget | None = None
    draft_known: frozenset[str] = frozenset()
    positioned: bool = False
    focus_timer: QtCore.QTimer | None = None
    instruction_run: CanvasRun | None = None
    subject: Subject = None
    """What the expanded toolbar is about; None while it's collapsed or about the canvas."""
    expanded: bool = False
    pinned: tuple[QtWidgets.QToolButton, ...] = ()
    tiles: tuple[QtWidgets.QToolButton, ...] = ()
    has_context: bool = False


@dataclass(frozen=True, slots=True)
class _Toolbar:
    """The island at the window's foot and the pills beside it."""

    scroll_edge: ScrollEdge
    toolbar: CanvasToolbar
    voice_hint: VoiceLegend
    clear_context: QtWidgets.QToolButton
    search_button: QtWidgets.QToolButton
    search: QtWidgets.QLineEdit
    find_shortcut: QtGui.QShortcut
    menu_button: QtWidgets.QToolButton
    recenter: GlassCapsule
    center_button: QtWidgets.QToolButton
    questions: GlassCapsule
    questions_button: QtWidgets.QToolButton
    status: QtWidgets.QLabel


def _toolbar(frame: CanvasSurface, theme: Tokens, act: Callable[[Callable[[CanvasPanel], None]], Callable[[], None]]) -> _Toolbar:
    # The island bar's rule at the window's foot: one island at rest (speak, search, more);
    # only temporary things sit beside it, Recenter once the view leaves the work and
    # the tinted Questions pill while questions wait.
    scroll_edge = ScrollEdge(frame, theme)
    toolbar = CanvasToolbar(frame, theme)
    heading = toolbar.content
    voice_hint = VoiceLegend(AGENT_HOLD, toolbar.surface.look.lettering.ink)
    heading.addWidget(voice_hint)
    clear_context = toolbar.button("close", "Ask about the whole canvas", act(CanvasPanel.clear_selection))
    clear_context.setIconSize(QtCore.QSize(12, 12))
    clear_context.hide()
    heading.addWidget(clear_context)
    search_button = toolbar.button("search", "Find on canvas (Ctrl+F)", act(CanvasPanel.toggle_search))
    search_button.setCheckable(True)
    heading.addWidget(search_button)
    search = QtWidgets.QLineEdit(toolbar)
    search.setObjectName("canvasSearch")
    search.setPlaceholderText("Find on canvas")
    search.setAccessibleName("Find on canvas")
    search.setFixedWidth(240)
    search.hide()
    search.returnPressed.connect(act(CanvasPanel.find))
    heading.addWidget(search)
    find_shortcut = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Find, frame)
    find_shortcut.activated.connect(act(CanvasPanel.show_search))
    menu_button = toolbar.button("more", "Canvas actions", act(CanvasPanel.toggle_expanded))
    menu_button.setCheckable(True)
    heading.addWidget(menu_button)
    recenter = GlassCapsule(frame, theme, Tint.NONE)
    center_button = recenter.button("center", "Center this canvas", act(CanvasPanel.fit))
    recenter.content.addWidget(center_button)
    questions = GlassCapsule(frame, theme, Tint.ATTENTION)
    questions_button = questions.button("chat", "Agent clarifications", act(CanvasPanel.show_questions))
    questions_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    questions_button.setProperty("caption", True)
    questions.content.addWidget(questions_button)
    recenter.hide()
    questions.hide()
    status = label("", "muted")
    status.setParent(frame)
    return _Toolbar(
        scroll_edge,
        toolbar,
        voice_hint,
        clear_context,
        search_button,
        search,
        find_shortcut,
        menu_button,
        recenter,
        center_button,
        questions,
        questions_button,
        status,
    )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class CanvasPanel:
    """Everything the canvas does is reached from its toolbar, built from `spec/canvas.py`."""

    window_controls: WindowControls
    theme: Tokens
    """One scheme for the canvas's lifetime, so every bubble, detail and menu agree."""
    style: str
    work: WorkWindow
    edits: CanvasEdits
    frame: CanvasSurface
    layout: QtWidgets.QVBoxLayout
    scene: QtWidgets.QGraphicsScene
    canvas: CanvasViewport
    interaction: CanvasInteraction
    _toolbar: _Toolbar
    _state: Cell[_Canvas]
    """Qt's thread alone reads and replaces it."""

    @classmethod
    def build(cls, parent: CanvasFrame, work: WorkWindow, canvas: CanvasEdits, window: WindowControls) -> CanvasPanel:
        theme = parent.theme
        style = content_style(theme)
        frame = CanvasSurface(parent)
        frame.setStyleSheet(style)
        layout = column(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        scene = QtWidgets.QGraphicsScene(frame)
        scene.setSceneRect(-2000, -2000, 10000, 10000)
        viewport = CanvasViewport(scene, theme)
        layout.addWidget(viewport)

        # The controls and gestures act on the panel made just after them.
        def act(method: Callable[[CanvasPanel], None]) -> Callable[[], None]:
            return lambda: method(panel)

        toolbar = _toolbar(frame, theme, act)
        document = canvas.read()
        state = _Canvas(document, project(PersonalView().catalog, document, CanvasScope()), ui_spec.canvas_toolbar(reload=False))
        interaction = CanvasInteraction(lambda: panel)
        panel = cls(window, theme, style, work, canvas, frame, layout, scene, viewport, interaction, toolbar, Cell(state))
        frame.resized.connect(panel.position_chrome)
        viewport.resized.connect(panel.reflow)
        for bar in (viewport.horizontalScrollBar(), viewport.verticalScrollBar()):
            bar.valueChanged.connect(act(CanvasPanel.update_recenter))
            bar.rangeChanged.connect(act(CanvasPanel.update_recenter))
        panel.update_voice_context()
        return panel

    @property
    def scroll_edge(self) -> ScrollEdge:
        return self._toolbar.scroll_edge

    @property
    def toolbar(self) -> CanvasToolbar:
        return self._toolbar.toolbar

    @property
    def voice_hint(self) -> VoiceLegend:
        return self._toolbar.voice_hint

    @property
    def clear_context(self) -> QtWidgets.QToolButton:
        return self._toolbar.clear_context

    @property
    def search_button(self) -> QtWidgets.QToolButton:
        return self._toolbar.search_button

    @property
    def search(self) -> QtWidgets.QLineEdit:
        return self._toolbar.search

    @property
    def find_shortcut(self) -> QtGui.QShortcut:
        return self._toolbar.find_shortcut

    @property
    def menu_button(self) -> QtWidgets.QToolButton:
        return self._toolbar.menu_button

    @property
    def recenter(self) -> GlassCapsule:
        return self._toolbar.recenter

    @property
    def center_button(self) -> QtWidgets.QToolButton:
        return self._toolbar.center_button

    @property
    def questions(self) -> GlassCapsule:
        return self._toolbar.questions

    @property
    def questions_button(self) -> QtWidgets.QToolButton:
        return self._toolbar.questions_button

    @property
    def status(self) -> QtWidgets.QLabel:
        return self._toolbar.status

    @property
    def toolbar_layout(self) -> QtWidgets.QHBoxLayout:
        return self._toolbar.toolbar.content

    @property
    def cards(self) -> tuple[CanvasCard, ...]:
        return self._state.get().cards

    @property
    def connection_paths(self) -> tuple[ConnectionPath, ...]:
        return self._state.get().connection_paths

    @property
    def details(self) -> tuple[tuple[str, CardDetail], ...]:
        return self._state.get().details

    @property
    def document(self) -> CanvasDocument:
        return self._state.get().document

    @property
    def draft(self) -> WorkDetail | None:
        return self._state.get().draft

    @property
    def draft_known(self) -> frozenset[str]:
        return self._state.get().draft_known

    @property
    def draft_proxy(self) -> QtWidgets.QGraphicsProxyWidget | None:
        return self._state.get().draft_proxy

    @property
    def editors(self) -> tuple[tuple[str, QtWidgets.QDialog], ...]:
        return self._state.get().editors

    @property
    def expanded(self) -> bool:
        return self._state.get().expanded

    @property
    def focus_timer(self) -> QtCore.QTimer | None:
        return self._state.get().focus_timer

    @property
    def group_cache(self) -> tuple[CanvasGroup, ...]:
        return self._state.get().group_cache

    @property
    def group_frames(self) -> tuple[CanvasGroup, ...]:
        return self._state.get().group_frames

    @property
    def has_context(self) -> bool:
        return self._state.get().has_context

    @property
    def instruction_run(self) -> CanvasRun | None:
        return self._state.get().instruction_run

    @property
    def last_spec(self) -> CanvasToolbarSpec:
        return self._state.get().last_spec

    @property
    def linking(self) -> WorkThread | None:
        return self._state.get().linking

    @property
    def pinned(self) -> tuple[QtWidgets.QToolButton, ...]:
        return self._state.get().pinned

    @property
    def positioned(self) -> bool:
        return self._state.get().positioned

    @property
    def projection(self) -> CanvasScene:
        return self._state.get().projection

    @property
    def rendered(self) -> tuple[PersonalView, CanvasDocument, CanvasScope] | None:
        return self._state.get().rendered

    @property
    def scope(self) -> CanvasScope:
        return self._state.get().scope

    @property
    def selected(self) -> str | None:
        return self._state.get().selected

    @property
    def subject(self) -> Subject:
        return self._state.get().subject

    @property
    def tiles(self) -> tuple[QtWidgets.QToolButton, ...]:
        return self._state.get().tiles

    @property
    def view(self) -> PersonalView:
        return self._state.get().view

    @property
    def visible_cards(self) -> tuple[CanvasCard, ...]:
        return self._state.get().visible_cards

    def toolbar_spec(self) -> CanvasToolbarSpec:
        """The toolbar's spec as its module says now; a broken edit keeps the last good one."""
        try:
            new_last_spec = ui_spec.canvas_toolbar()
            self._state.set(replace(self._state.get(), last_spec=new_last_spec))
        except ui_spec.SpecError as error:
            self.work.problem(f"The canvas toolbar kept its last good spec: {error}")
        return self.last_spec

    def bubble_subject(self, identity: str | None) -> Bubble | None:
        current = next((each for each in containers(self.view.catalog, self.document) if each.id == identity), None)
        match current:
            case None:
                return None
            case WorkThread():
                return Bubble(current.id, container_title(current), Role.WORK)
            case CanvasCollection():
                return Bubble(current.id, container_title(current), Role.GROUP)
            case _:
                return Bubble(current.id, container_title(current), Role.OTHER)

    def related(self, subject: Subject) -> tuple[Relationship, ...]:
        """The selected bubble's relationships, by their place among the canvas's."""
        match subject:
            case Bubble(identity=identity):
                relations = self.document.relations
                return tuple(Relationship(index, each.reason) for index, each in enumerate(relations) if identity in (each.start, each.end))
            case Relationship() | None:
                return ()
            case _:
                assert_never(subject)

    def refresh_toolbar(self) -> None:
        """Rebuild the row's pinned tiles and, while expanded, its sections, from the spec as it is now."""
        spec = self.toolbar_spec()
        collapsed = self.scope.mode is CanvasMode.CONTEXTS
        selected = self.bubble_subject(self.selected)
        for each in self.pinned:
            each.hide()
            each.deleteLater()
        place = self.toolbar_layout.indexOf(self.search_button)
        new_pinned = tuple(self.toolbar.tile_button(tile, self.perform) for tile in row(spec, selected, self.related(selected), collapsed=collapsed))
        self._state.set(replace(self._state.get(), pinned=new_pinned))
        for offset, each in enumerate(self.pinned):
            self.toolbar_layout.insertWidget(place + offset, each)
        subject = self.subject if self.subject is not None else selected
        groups = sections(spec, subject, self.related(subject), self.dismissed(), collapsed=collapsed) if self.expanded else ()
        # The expanded toolbar keeps the window's top margin and the status line above it.
        room = self.frame.height() - 14 - 120
        new_tiles = self.toolbar.show_sections(groups, self.perform, room)
        self._state.set(replace(self._state.get(), tiles=new_tiles))
        self.menu_button.setChecked(self.expanded)
        self.position_chrome()

    def dismissed(self) -> tuple[Dismissed, ...]:
        return tuple(Dismissed(each.work.id, each.work.definition.title) for each in self.view.catalog.dismissed)

    def expand(self, subject: Subject) -> None:
        """Open the toolbar in place on `subject`'s actions, then the canvas's."""
        self._state.set(replace(self._state.get(), subject=subject, expanded=True))
        self.refresh_toolbar()
        if self.tiles:
            self.tiles[0].setFocus()

    def collapse(self) -> None:
        self._state.set(replace(self._state.get(), subject=None, expanded=False))
        self.refresh_toolbar()

    def toggle_expanded(self) -> None:
        if self.expanded:
            self.collapse()
        else:
            self.expand(None)

    def perform(self, act: Act) -> None:
        """A tile was pressed: act, then collapse, unless it opened a relationship's own tiles."""
        match act:
            case Open(relationship=relationship):
                self.expand(relationship)
                return
            case OnCanvas(action=action):
                self.collapse()
                self.canvas_action(action)
            case OnBubble(action=action, identity=identity):
                self.collapse()
                self.bubble_action(action, identity)
            case OnRelationship(action=action, index=index):
                self.collapse()
                if index < len(self.document.relations):
                    relation = self.document.relations[index]
                    match action:
                        case RelationAction.EDIT:
                            self.edit_relation(relation)
                        case RelationAction.REMOVE:
                            self.remove_relation(relation)
                        case _:
                            assert_never(action)
            case Restore(work=work):
                self.collapse()
                self.work.send(RestoreWork(work))
            case _:
                assert_never(act)

    def canvas_action(self, action: CanvasTool) -> None:
        match action:
            case CanvasTool.CENTER:
                self.fit()
            case CanvasTool.CONTENTS:
                self.toggle_contents()
            case CanvasTool.ARRANGE_THREADS:
                self.reflow()
            case CanvasTool.ARRANGE_ALL:
                self.release_positions()
            case CanvasTool.REFRESH:
                self.refresh()
            case CanvasTool.NEW_CONTEXT:
                self.create()
            case CanvasTool.NEW_GROUP:
                self.create_group()
            case CanvasTool.NOTE:
                self.create_note()
            case CanvasTool.DOCUMENT:
                self.create_document()
            case CanvasTool.DOCUMENT_LINK:
                self.create_document_link()
            case CanvasTool.WEB_REFERENCE:
                self.create_web_reference()
            case CanvasTool.CONNECT_SOURCE:
                self.start_connection()
            case CanvasTool.CHOOSE_GROUP:
                self.choose_group()
            case CanvasTool.MAXIMIZE:
                self.window_controls.maximize()
            case CanvasTool.CLOSE:
                self.window_controls.close()
            case _:
                assert_never(action)

    def update_voice_context(self) -> None:
        current = topology(self.view.catalog, self.document).by_id.get(self.selected) if self.selected is not None else None
        context = container_title(current) if current is not None else "whole canvas"
        self.voice_hint.setToolTip("Ask agent · " + context + "\n" + AGENT_HOLD + " with Workspace's layout enabled; release to send.")
        self._state.set(replace(self._state.get(), has_context=current is not None))
        self.position_chrome()

    def clear_selection(self) -> None:
        self._state.set(replace(self._state.get(), selected=None))
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
            started = self.edits.start(pending)
        except (OSError, ValueError, sqlite3.Error) as error:
            self.work.problem("The local canvas could not be saved: " + str(error))
            return False
        self._state.set(replace(self._state.get(), document=started.document))
        match started:
            case NotQueued(reason=reason):
                # Retrying reuses this saved binding instead of adding another.
                self._state.set(replace(self._state.get(), instruction_run=pending))
                self.status.setText("Could not queue the instruction: " + reason)
                return False
            case Queued():
                self._state.set(replace(self._state.get(), instruction_run=None))
                self.status.setText("Instruction queued. The agent will build on this canvas.")
                return True

    def position_chrome(self) -> None:
        # Searching turns the island into its field; speaking and options return afterwards.
        searching = not self.search.isHidden()
        self.voice_hint.setVisible(not searching)
        self.clear_context.setVisible(self.has_context and not searching)
        self.menu_button.setVisible(not searching)
        for capsule in (self.toolbar, self.recenter, self.questions):
            capsule.content.activate()
            capsule.adjustSize()
        # The island stays centred 14 px above the window's foot; temporary pills sit 6 px beside its glass.
        foot = self.frame.height() - 14 + SHADOW.bottom()
        self.toolbar.move((self.frame.width() - self.toolbar.width()) // 2, foot - self.toolbar.height())
        gap = 6 - SHADOW.left() - SHADOW.right()
        self.recenter.move(self.toolbar.x() - gap - self.recenter.width(), foot - self.recenter.height())
        self.questions.move(self.toolbar.x() + self.toolbar.width() + gap, foot - self.questions.height())
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setGeometry(24, self.toolbar.y() + SHADOW.top() - 28, self.frame.width() - 48, 20)
        viewport = self.canvas.geometry()
        self.scroll_edge.setGeometry(viewport.left(), viewport.bottom() + 1 - 90, viewport.width(), 90)
        for widget in (self.scroll_edge, self.recenter, self.toolbar, self.questions, self.status):
            widget.raise_()
        if (self.visible_cards or self.group_frames) and not self.positioned:
            self.home()

    def update_recenter(self) -> None:
        """Recenter appears only once the view has left the work, as Maps shows its location button."""
        visible = self.canvas.mapToScene(self.canvas.viewport().rect()).boundingRect()
        bubbles = tuple(self.bubbles())
        away = bool(bubbles) and not any(bubble.sceneBoundingRect().intersects(visible) for bubble in bubbles)
        if away != self.recenter.isVisible():
            self.recenter.setVisible(away)

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
        self._state.set(replace(self._state.get(), positioned=True))

    def run_refused(self, run: CanvasRun, reason: str) -> None:
        """The assistant saved this instruction but couldn't queue it: keep it for a retry."""
        if isinstance(run.intent, CanvasInstruction):
            self._state.set(replace(self._state.get(), instruction_run=run))
            self.status.setText("Could not queue the instruction: " + reason)

    def meeting_page(self, transcript_path: str, page: MeetingConversation | None) -> None:
        """A meeting's conversation page the assistant read, for the detail that asked."""
        for _, detail in self.details:
            if isinstance(detail, SourceDetail):
                detail.show_page(transcript_path, page)

    def show_document(self, document: CanvasDocument) -> None:
        """Render a document the canvas owner committed or observed."""
        if document == self.document:
            return
        self._state.set(replace(self._state.get(), document=document))
        self.render(self.view)

    def commit(self, change: Change) -> bool:
        try:
            new_document = self.edits.commit(UserEdit(self.scope, change))
            self._state.set(replace(self._state.get(), document=new_document))
        except ValueError as error:
            self.work.problem(str(error))
            return False
        except (OSError, sqlite3.Error) as error:
            self.work.problem("The local canvas could not be saved: " + str(error))
            return False
        return True

    def sync_cards(self, content: tuple[CanvasContent, ...], visible: frozenset[str]) -> None:
        """Qt retains created bubbles/drafts and materializes only visible pieces."""
        identities = frozenset(item.id for item in content)
        for removed in self.cards:
            if removed.content.id not in identities and removed.scene() is self.scene:
                self.scene.removeItem(removed)
        new_cards = tuple(card for card in self.cards if card.content.id in identities)
        self._state.set(replace(self._state.get(), cards=new_cards))
        for item in content:
            card = self.card(item.id)
            if card is None:
                if item.id not in visible:
                    continue
                card = CanvasCard(item, self)
                position = next((position for position in self.document.placements if position.id == item.id), None)
                if position is not None:
                    card.setPos(position.x, position.y)
                self._state.set(replace(self._state.get(), cards=(*self.cards, card)))
            elif card.content != item:
                # Content updates preserve native identity, positions and drafts.
                card.refresh(item)
            if item.id in visible and card.scene() is not self.scene:
                self.scene.addItem(card)
            elif item.id not in visible and card.scene() is self.scene:
                self.scene.removeItem(card)
            self.refresh_detail(item)
        new_visible_cards = tuple(card for card in self.cards if card.content.id in visible)
        self._state.set(replace(self._state.get(), visible_cards=new_visible_cards))

    def render(self, view: PersonalView) -> None:
        self.status.setToolTip(view.status)
        self.status.setText("" if not self.linking else "Select a source to connect")
        if self.rendered == (view, self.document, self.scope):
            return
        self.interaction.cancel()
        self._state.set(replace(self._state.get(), view=view))
        if self.expanded:
            self.refresh_toolbar()
        indexed = topology(view.catalog, self.document)
        retained = frozenset(indexed.by_id)
        if self.selected not in retained:
            self._state.set(replace(self._state.get(), selected=None))
        self.update_voice_context()
        new_group_cache = tuple(group for group in self.group_cache if group.context.id in retained)
        self._state.set(replace(self._state.get(), group_cache=new_group_cache))
        for identity, dialog in self.editors:
            if identity not in retained:
                dialog.hide()
        new_editors = tuple(pair for pair in self.editors if pair[0] in retained)
        self._state.set(replace(self._state.get(), editors=new_editors))
        new_details = tuple(pair for pair in self.details if pair[0] in retained)
        self._state.set(replace(self._state.get(), details=new_details))
        new_projection = project(view.catalog, self.document, self.scope)
        self._state.set(replace(self._state.get(), projection=new_projection))
        self._state.set(replace(self._state.get(), scope=self.projection.scope))
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
        self.questions_button.setText(str(pending))
        self.questions.setVisible(bool(pending))
        self.reflow()
        self.position_chrome()
        self.canvas.setSceneRect(self.scene.itemsBoundingRect().adjusted(-1500, -1500, 1500, 1500))
        if not self.positioned and (self.visible_cards or self.group_frames):
            self.home()
        self.update_recenter()
        self.reconcile_draft()
        self._state.set(replace(self._state.get(), rendered=(view, self.document, self.scope)))

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
            case SourceDetail() as source, (
                TeamsSource() | OutlookSource() | KanbanSource() | DocumentSource() | WebPageSource() | MeetingSource()
            ) as current:
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
        self._state.set(replace(self._state.get(), selected=identity))
        self.update_voice_context()
        card = self.card(identity)

        if self.linking is not None and card is not None:
            match card.content:
                case TeamsSource() | OutlookSource() | KanbanSource() | DocumentSource() | WebPageSource() | MeetingSource() as source:
                    work = self.linking
                    self._state.set(replace(self._state.get(), linking=None))
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
        self._state.set(replace(self._state.get(), focus_timer=None))
        bubble = next((bubble for bubble in self.bubbles() if bubble.identity == identity), None)
        if bubble is not None:
            self.select(identity)
            bounds = bubble.sceneBoundingRect()
            visible_height = self.canvas.viewport().height() / self.canvas.transform().m11()
            self.canvas.centerOn(bounds.center().x(), bounds.top() + min(bounds.height() / 2, visible_height / 2 - 100))

    def queue_location(self, identity: str) -> None:
        cancel(self.focus_timer)
        new_focus_timer = later(self.frame, 0, lambda: self.locate(identity))
        self._state.set(replace(self._state.get(), focus_timer=new_focus_timer))

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
                case TeamsSource() | OutlookSource() | KanbanSource() | DocumentSource() | WebPageSource() | MeetingSource() as content:
                    detail = SourceDetail.build(self.work, content, self.style, on_context=self.open_context)
                    detail.refresh(content, self.view.catalog, self.document)
                case CanvasNote() as content:
                    detail = NoteDetail.build(content, self.save_note, self.style)
                case CanvasUpdate() | CanvasAction() as content:
                    detail = UpdateDetail.build(content, self.open_at, self.style)
                case CanvasQuestion() as content:
                    detail = QuestionDetail.build(content, self.style)
            self._state.set(replace(self._state.get(), details=(*self.details, (identity, detail))))
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
            detail = WorkDetail.build(self.work, work, self.style, on_continue=lambda: self.study_work(work.id))
            self._state.set(replace(self._state.get(), details=(*self.details, (work.id, detail))))
            dialog = QtWidgets.QDialog(self.frame)
            dialog.setWindowTitle("Work context · " + work.definition.title)
            dialog.setStyleSheet(self.style + f"QDialog {{ background: {self.theme.window}; }}")
            dialog.resize(520, 540)
            layout = column(dialog)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.addWidget(detail.frame)
            self._state.set(replace(self._state.get(), editors=(*self.editors, (work.id, dialog))))
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
                if not self.commit(released):
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
        self.commit(PutRelation(relation))
        self.draw_connections()
        self.status.setText("")

    def relation_menu(self, relation: CanvasRelation) -> None:
        """A right-clicked relationship opens the toolbar on its actions."""
        index = next((index for index, each in enumerate(self.document.relations) if each == relation), None)
        if index is not None:
            self.expand(Relationship(index, relation.reason))

    def edit_relation(self, relation: CanvasRelation) -> None:
        reason, accepted = QtWidgets.QInputDialog.getText(self.frame, "Relationship", "Relationship", text=relation.reason)
        if accepted and reason.strip():
            self.save_relation(replace(relation, reason=reason.strip()[:1200]))

    def remove_relation(self, relation: CanvasRelation) -> None:
        self.commit(RemoveRelation(relation.start, relation.end))
        self.draw_connections()

    def reflow(self) -> None:
        for card in self.visible_cards:
            card.setRect(0, 0, card.own_size.width(), card.own_size.height())
            card.setZValue(10 if card.expanded else 1)
        measurements = Measurements(
            frozendict((card.content.id, Size(card.own_size.width(), card.own_size.height())) for card in self.visible_cards),
            max(380, self.canvas.viewport().width() / 0.9 - 84),
        )
        state = view_state(self.document, self.scope.identity)
        arranged = layout(self.projection, state, measurements)
        if arranged.state != state:
            self.commit(ArrangeView(state, arranged.state))
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
                self._state.set(replace(self._state.get(), group_cache=(*self.group_cache, native)))
            else:
                native.refresh(group, bounds)
            if native.scene() is not self.scene:
                self.scene.addItem(native)
            native.setZValue(depth[group.id] - len(groups) - 1)
            current = (*current, native)
        self._state.set(replace(self._state.get(), group_frames=current))
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
                edge = ConnectionPath(connection, self.relation_menu, self.theme)
                self.scene.addItem(edge)
            edge.highlight(self.selected)
            current = (*current, edge)
        self._state.set(replace(self._state.get(), connection_paths=current))
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
        if self.expanded:
            self.collapse()
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
        self.commit(ReleasePositions.RELEASE)
        self.reflow()

    def reveal(self, identity: str) -> None:
        # A single scene owns all nested bubbles. Focusing reveals its ancestors
        # without replacing neighbors, saved pins or the scene's native objects.
        self.commit(Reveal(identity))
        new_scope = CanvasScope()
        self._state.set(replace(self._state.get(), scope=new_scope))
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
        new_scope = replace(self.scope, mode=mode)
        self._state.set(replace(self._state.get(), scope=new_scope))
        self._state.set(replace(self._state.get(), positioned=False))
        self.render(self.view)
        self.home()

    def context_menu(self, identity: str) -> None:
        """A right-clicked bubble is selected and opens the toolbar on its actions."""
        self.select(identity)
        self.expand(self.bubble_subject(identity))

    def bubble_action(self, action: BubbleAction, identity: str) -> None:
        """The tiles offered only what applies; Relationships became a tile per relationship."""
        match action:
            case BubbleAction.FOCUS:
                self.open_context(identity)
            case BubbleAction.CONTENTS:
                self.toggle_bubble(identity)
            case BubbleAction.CONNECT:
                self.interaction.start_relation(identity)
            case BubbleAction.CONTINUE:
                self.study_work(identity)
            case BubbleAction.EDIT_WORK:
                self.inspect(identity)
            case BubbleAction.DISMISS:
                self.dismiss_work(identity, "Dismissed by the user.")
            case BubbleAction.NOT_MINE:
                self.dismiss_work(identity, "This is not my responsibility.")
            case BubbleAction.RENAME_GROUP:
                self.rename_group(identity)
            case BubbleAction.PUT_INSIDE:
                self.choose_group()
            case BubbleAction.MOVE_TO_CANVAS:
                self.add_to_group(None, identity)
            case BubbleAction.RELATIONSHIPS:
                pass  # Its tiles open each relationship.
            case _:
                assert_never(action)

    def create_group(self) -> None:
        title, accepted = QtWidgets.QInputDialog.getText(self.frame, "New canvas group", "Group name")
        if accepted and title.strip():
            group = CanvasCollection("group:" + uuid4().hex, title.strip(), parent_id=self.selected)
            self.commit(AddGroup(group))
            self.render(self.view)
            self.open_context(group.id)

    def rename_group(self, identity: str) -> None:
        group = next((group for group in self.document.collections if group.id == identity), None)
        if group is not None:
            title, accepted = QtWidgets.QInputDialog.getText(self.frame, "Rename canvas group", "Group name", text=group.title)
            if accepted and title.strip():
                self.commit(RenameGroup(identity, title.strip()))
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
        visible = next((bubble for bubble in self.capture_gesture_scene().bubbles if bubble.id == identity), None)
        members = (
            visible.members
            if visible is not None
            else frozenset(item for item, path in topology(self.view.catalog, self.document).paths.items() if identity in path)
        )
        if self.commit(PutInside(identity, group_id, members)):
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
            self.commit(SetExpansion(identity, expanded=not group.expanded))
            new_scope = replace(self.scope, mode=CanvasMode.CONTENTS)
            self._state.set(replace(self._state.get(), scope=new_scope))
            self.render(self.view)
            revised = next((item for root in self.projection.groups for item in descendants(root) if item.id == identity), None)
            if not group.expanded and revised is not None and not revised.expanded:
                self.open_context(identity)
            else:
                self.locate(identity)

    def study_work(self, identity: str) -> None:
        try:
            continued = self.edits.continue_work(identity)
        except (OSError, ValueError, sqlite3.Error) as error:
            self.work.problem("The local canvas could not be saved: " + str(error))
            return
        match continued:
            case ResumeTask(task_id=task):
                self.work.send(ControlTask(task, Control.RESUME))
            case Investigating.ALREADY:
                self.status.setText("This work already has an investigation in progress.")
            case Queued(document=document):
                self._state.set(replace(self._state.get(), document=document))
            case NotQueued(document=document, reason=reason):
                self._state.set(replace(self._state.get(), document=document))
                self.status.setText("Could not queue the investigation: " + reason)

    def start_connection(self) -> None:
        work = next((work for work in self.view.catalog.works if work.id == self.selected), None)
        if work is not None:
            self._state.set(replace(self._state.get(), linking=None if self.linking is not None else work))
            self.status.setText("Select a source bubble to connect." if self.linking is not None else "Connection cancelled.")
        else:
            self.status.setText("Select a work bubble before connecting a source.")

    def refresh(self) -> None:
        self.work.send(RefreshPersonalWork.REFRESH)

    def fit(self) -> None:
        cancel(self.focus_timer)
        self._state.set(replace(self._state.get(), focus_timer=None))
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
        known = frozenset(item.id for item in self.view.catalog.works)
        draft = WorkDetail.build(self.work, WorkDefinition("New work", "Describe the outcome you are working towards."), self.style)
        # The draft is a solid card on the canvas, like the bubble it becomes.
        frame = QtWidgets.QFrame()
        frame.setObjectName("draft")
        frame.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        frame.setStyleSheet(
            self.style
            + f"QFrame#draft {{ background: {self.theme.solid}; border: 1px solid {self.theme.solid_edge.css}; border-radius: {CARD_RADIUS}px; }}"
        )
        frame.setFixedWidth(400)
        layout = column(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(label("New work", "title"))
        layout.addWidget(draft.frame)
        layout.addWidget(button("Discard new work", self.cancel_create))
        proxy = self.scene.addWidget(frame)
        self._state.set(replace(self._state.get(), draft_known=known, draft=draft, draft_proxy=proxy))
        proxy.setZValue(20)
        point = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        proxy.setPos(point.x() - 200, point.y() - 260)
        self.canvas.ensureVisible(proxy)
        draft.title.setFocus()

    def cancel_create(self) -> None:
        if self.draft_proxy is not None:
            self.scene.removeItem(self.draft_proxy)
            self.draft_proxy.deleteLater()
            self._state.set(replace(self._state.get(), draft_proxy=None))
        self._state.set(replace(self._state.get(), draft=None))

    def create_note(self) -> None:
        note = CanvasNote("note:" + uuid4().hex, "New note", context_id=self.selected)
        point = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        self.commit(SaveNote(note))
        self.render(self.view)
        self.apply_gesture(PlaceBubbles(note.id, (Placement(note.id, point.x() - 180, point.y() - 140),)))
        self.inspect(note.id)

    def save_note(self, note: CanvasNote) -> None:
        if self.commit(SaveNote(note)):
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
        self._link(("Add document link", "Document URL"), "Document title", AddDocument)

    def create_web_reference(self) -> None:
        self._link(("Add web reference", "Page URL"), "Web reference title", AddWebPage)

    def _link(self, asked: tuple[str, str], titled: str, add: Callable[[str, WebDocument], AddDocument | AddWebPage]) -> None:
        """Ask for a URL, then the name it shows on the canvas, and add it."""
        url, accepted = QtWidgets.QInputDialog.getText(self.frame, *asked)
        if accepted and url.strip():
            title, accepted = QtWidgets.QInputDialog.getText(self.frame, titled, "Name on canvas")
            if accepted and title.strip():
                try:
                    self.add_document(add(title.strip(), WebDocument(url.strip())))
                except ValueError as error:
                    self.work.problem(str(error))

    def dismiss_work(self, identity: str, reason: str) -> None:
        work = next((item for item in self.view.catalog.works if item.id == identity), None)
        if work is not None:
            self.work.send(DismissWork(work.id, work.revision, reason))

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
            self.commit(PutInside(reference_id(command), self.selected, frozenset()))


# Qt owns pointer capture and previews; immutable decisions own the gestures.
# No document/layout work occurs during pointer movement. The panel applies
# the single immutable commit effect on release.
@dataclass(frozen=True, slots=True)
class _Gesturing:
    gesture: Gesture = Idle.READY
    scene: GestureScene = field(default_factory=lambda: GestureScene((), None))
    """The bubbles as they stood when the gesture began."""
    relation_preview: QtWidgets.QGraphicsPathItem | None = None


@dataclass(frozen=True, slots=True)
class CanvasInteraction:
    _owner: Callable[[], CanvasPanel]
    _state: Cell[_Gesturing] = field(default_factory=lambda: Cell(_Gesturing()), init=False, repr=False)

    def _advance(self, event: GestureInput) -> GestureResult:
        gesturing = self._state.get()
        result = transition(gesturing.gesture, event, gesturing.scene)
        self._state.set(replace(gesturing, gesture=result.state))
        return result

    @property
    def owner(self) -> CanvasPanel:
        return self._owner()

    def press_bubble(self, identity: str, point: ScenePoint) -> None:
        match self._state.get().gesture:
            case DrawingRelation():
                return
            case _:
                scene = self.owner.capture_gesture_scene()
                self._state.update(lambda gesturing: replace(gesturing, scene=scene))
        target = next(bubble for bubble in scene.bubbles if bubble.id == identity)
        state = self.owner.gesture_placements()
        positions = tuple(position for position in state if position.id in target.members)
        drag = BubbleDrag(identity, point, positions, target.parent_id, target.members)
        self._advance(PressBubble(drag))

    def pointer(self, event: PointerMoved | PointerReleased | PressConnector) -> None:
        match event:
            case PressConnector():
                scene = self.owner.capture_gesture_scene()
                self._state.update(lambda gesturing: replace(gesturing, scene=scene))
            case PointerMoved(point=point):
                event = PointerMoved(point, QtWidgets.QApplication.startDragDistance() / self.owner.canvas.transform().m11())
            case _:
                pass
        result = self._advance(event)
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
        if (preview := self._state.get().relation_preview) is not None:
            self.owner.scene.removeItem(preview)
            self._state.update(lambda gesturing: replace(gesturing, relation_preview=None))
        for bubble in self.owner.bubbles():
            bubble.highlight_drop(active=False)

    def preview_relation(self, identity: str, point: ScenePoint) -> None:
        source = next(bubble for bubble in self.owner.bubbles() if bubble.identity == identity)
        first = source.mapToScene(source.connector.pos())
        preview = self._state.get().relation_preview
        if preview is None:
            preview = QtWidgets.QGraphicsPathItem()
            pen = QtGui.QPen(QtGui.QColor(GLASS_ACCENT), 2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            preview.setPen(pen)
            preview.setZValue(30)
            preview.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.owner.scene.addItem(preview)
            self._state.update(lambda gesturing: replace(gesturing, relation_preview=preview))
        path = QtGui.QPainterPath(first)
        path.lineTo(point.x, point.y)
        preview.setPath(path)

    def start_relation(self, identity: str) -> None:
        self.clear_gesture_preview()
        source = next(bubble for bubble in self.owner.bubbles() if bubble.identity == identity)
        point = source.mapToScene(source.connector.pos())
        self.pointer(PressConnector(identity, ScenePoint(point.x(), point.y())))
        self.owner.gesture_status("Click another bubble to connect; Escape cancels.")

    def cancel(self) -> bool:
        match self._state.get().gesture:
            case Idle():
                return False
            case _:
                result = self._advance(CancelGesture.CANCEL)
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
