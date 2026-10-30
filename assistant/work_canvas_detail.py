"""In-place native card details and revision-bound drafts, owned by Qt."""

from collections.abc import Callable
from dataclasses import replace

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.agent_session import Answered
from assistant.canvas_activity import Attention, CanvasAction, CanvasQuestion, CanvasUpdate
from assistant.keymap import PHYSICAL_NAMES
from assistant.ui_components.appearance import ACCENT, CANVAS_STYLE
from assistant.ui_components.controls import button, label
from assistant.ui_components.widgets import Editor, column, replace_text, row
from assistant.work_canvas_context import context_path
from assistant.work_canvas_model import CanvasDocument, CanvasNote
from assistant.work_window import WorkWindow, when
from automation.personal_work import (
    Catalog,
    DismissWork,
    OpenWorkSource,
    SaveWork,
    SourceKind,
    UnlinkWork,
    WorkDefinition,
    WorkSource,
    WorkState,
    WorkThread,
)
from miryoku.layout import AGENT


def detail_frame(height: int) -> QtWidgets.QWidget:
    """Set the final canvas style/width before source text triggers Qt layout."""
    frame = QtWidgets.QWidget()
    frame.setStyleSheet(CANVAS_STYLE)
    frame.setFixedSize(432, height)
    return frame


class WorkDetail:
    def __init__(self, work: WorkWindow, content: WorkThread | WorkDefinition, *, on_continue: Callable[[], None] | None = None) -> None:
        self.work: WorkWindow = work
        self.current: WorkThread | WorkDefinition = content
        self.original: WorkThread | None = None
        self.pending: SaveWork | None = None
        self.frame: QtWidgets.QWidget = detail_frame(475)
        layout = column(self.frame)
        self.info: QtWidgets.QWidget = QtWidgets.QWidget()
        info = column(self.info)
        self.text: Editor = Editor(readonly=True)
        info.addWidget(self.text)
        actions = row()
        self.edit_button: QtWidgets.QToolButton = button("Edit work", self.edit)
        self.done: QtWidgets.QToolButton = button("Mark done", self.change_state)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.done)
        actions.addWidget(button("Dismiss work", self.dismiss))
        if on_continue is not None:
            actions.addWidget(button("Continue with agent", on_continue))
        info.addLayout(actions)
        layout.addWidget(self.info)
        self.editor: QtWidgets.QWidget = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(self.editor)
        self.title: QtWidgets.QLineEdit = QtWidgets.QLineEdit()
        self.goal: Editor = Editor()
        self.summary: Editor = Editor()
        self.next_step: Editor = Editor()
        self.project: QtWidgets.QLineEdit = QtWidgets.QLineEdit()
        self.state: QtWidgets.QComboBox = QtWidgets.QComboBox()
        self.state.addItems([state.value.capitalize() for state in WorkState])
        for caption, widget in (
            ("Title", self.title),
            ("Goal", self.goal),
            ("Situation", self.summary),
            ("Next step", self.next_step),
            ("Project", self.project),
            ("State", self.state),
        ):
            widget.setAccessibleName("Work " + caption.lower())
            form.addRow(caption, widget)
        for editor in (self.goal, self.summary, self.next_step):
            editor.setFixedHeight(80)
        edit_actions = row()
        edit_actions.addWidget(button("Save work", self.save, name="primary"))
        edit_actions.addWidget(button("Cancel edit", self.cancel))
        form.addRow(edit_actions)
        layout.addWidget(self.editor)
        self.editor.hide()
        match content:
            case WorkThread():
                self.refresh(content)
            case WorkDefinition():
                self.edit()

    def refresh(self, content: WorkThread) -> None:
        self.current = content
        definition = content.definition
        replace_text(
            self.text,
            f"Goal\n{definition.goal}\n\nCurrent situation\n{definition.summary or 'No summary yet.'}"
            + f"\n\nNext step\n{definition.next_step or 'No next step identified.'}\n\nUpdated {when(content.updated_at)}",
        )
        self.done.setText("Reopen" if definition.state is WorkState.DONE else "Mark done")
        # Background publications refresh information, never replace edit fields.
        if (
            self.pending is not None
            and definition == self.pending.definition
            and content.links == self.pending.links
            and (self.original is None or content.revision > self.original.revision)
        ):
            self.cancel()

    def edit(self) -> None:
        match self.current:
            case WorkThread(definition=definition) as original:
                self.original = original
            case WorkDefinition() as definition:
                self.original = None
        self.title.setText(definition.title)
        self.goal.setPlainText(definition.goal)
        self.summary.setPlainText(definition.summary)
        self.next_step.setPlainText(definition.next_step)
        self.project.setText(definition.project)
        self.state.setCurrentIndex(tuple(WorkState).index(definition.state))
        self.info.hide()
        self.editor.show()

    def cancel(self) -> None:
        self.editor.hide()
        self.info.show()
        self.original = None
        self.pending = None

    def save(self) -> None:
        definition = WorkDefinition(
            self.title.text(),
            self.goal.toPlainText(),
            self.summary.toPlainText(),
            self.next_step.toPlainText(),
            tuple(WorkState)[self.state.currentIndex()],
            self.project.text(),
        )
        original = self.original
        command = SaveWork(definition, original.links if original else (), original.id if original else None, original.revision if original else None)
        if self.work.send(command):
            self.pending = command

    def change_state(self) -> None:
        match self.current:
            case WorkThread() as content:
                state = WorkState.ACTIVE if content.definition.state is WorkState.DONE else WorkState.DONE
                self.work.send(SaveWork(replace(content.definition, state=state), content.links, content.id, content.revision))
            case WorkDefinition():
                pass

    def dismiss(self) -> None:
        match self.current:
            case WorkThread() as work:
                self.work.send(DismissWork(work.id, work.revision, "Dismissed by the user."))
            case WorkDefinition():
                pass


class SourceDetail:
    def __init__(self, work: WorkWindow, content: WorkSource, *, on_context: Callable[[str], None] | None = None) -> None:
        self.work: WorkWindow = work
        self.current: WorkSource = content
        self.catalog: Catalog = Catalog()
        self.ancestry: frozenset[str] = frozenset()
        self.frame: QtWidgets.QWidget = detail_frame(475)
        layout = column(self.frame)
        self.text: Editor = Editor(readonly=True)
        self.text.setAccessibleName("Observed source content")
        layout.addWidget(self.text, 3)
        layout.addWidget(label("Connected work", "muted"))
        self.connections: QtWidgets.QComboBox = QtWidgets.QComboBox()
        self.connections.setAccessibleName("Work connected to this source")
        layout.addWidget(self.connections)
        self.reason: Editor = Editor(readonly=True)
        self.reason.setAccessibleName("Why this source is connected")
        layout.addWidget(self.reason, 1)
        actions = row()
        self.open: QtWidgets.QToolButton = button("Open in Edge", self.open_source)
        self.unlink: QtWidgets.QToolButton = button("Remove connection", self.remove)
        actions.addWidget(self.open)
        actions.addWidget(self.unlink)
        if on_context is not None:
            layout.addWidget(button("Show work on canvas", lambda: self.open_context(on_context)))
        layout.addLayout(actions)
        self.connections.currentIndexChanged.connect(self.render_reason)
        # Resolve the source editor's inherited font and final wrapping width
        # before loading full mail text, rather than wrapping again on embedding.
        self.frame.ensurePolished()
        layout.activate()

    def refresh(self, content: WorkSource, catalog: Catalog, document: CanvasDocument) -> None:
        self.current, self.catalog = content, catalog
        self.ancestry = frozenset(context_path(content.id, catalog, document)) | {content.id}
        self.open.setText("Open original" if content.kind in (SourceKind.DOCUMENT, SourceKind.WEB_PAGE) else "Open in Edge")
        replace_text(
            self.text,
            f"Observed {when(content.observed_at)}\n\n{content.url}\n\n{content.excerpt}"
            if content.kind in (SourceKind.DOCUMENT, SourceKind.WEB_PAGE)
            else f"Observed {when(content.observed_at)}\n\n{content.excerpt}",
        )
        previous: object = self.connections.currentData()
        self.connections.clear()
        for item in catalog.works:
            if item.id in self.ancestry or any(link.source_id in self.ancestry for link in item.links):
                self.connections.addItem(item.definition.title, item.id)
        for index in range(self.connections.count()):
            candidate: object = self.connections.itemData(index)
            if candidate == previous:
                self.connections.setCurrentIndex(index)
                break
        self.render_reason()

    def select_context(self, identity: str) -> None:
        for index in range(self.connections.count()):
            observed: object = self.connections.itemData(index)
            if observed == identity:
                self.connections.setCurrentIndex(index)
                return

    def selected(self) -> WorkThread | None:
        observed: object = self.connections.currentData()
        match observed:
            case str() as identity:
                return next((item for item in self.catalog.works if item.id == identity), None)
            case _:
                return None

    def open_context(self, callback: Callable[[str], None]) -> None:
        selected = self.selected()
        if selected is not None:
            callback(selected.id)

    def render_reason(self) -> None:
        work = self.selected()
        association = next((link for link in work.links if link.source_id in self.ancestry), None) if work else None
        reason = ("Through the containing bubble: " if association.source_id != self.current.id else "") + association.reason if association else None
        replace_text(self.reason, reason if reason else "Collected inside this work context." if work else "No work is connected yet.")
        self.unlink.setEnabled(association is not None and association.source_id == self.current.id)

    def remove(self) -> None:
        work = self.selected()
        if work is not None:
            self.work.send(UnlinkWork(work.id, self.current.id, work.revision))

    def open_source(self) -> None:
        if self.current.kind is SourceKind.DOCUMENT:
            if not QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.current.url)):
                self.work.problem("Windows could not open this document.")
        else:
            self.work.send(OpenWorkSource(self.current.parent_id or self.current.id))


class NoteDetail:
    def __init__(self, content: CanvasNote, save: Callable[[CanvasNote], None]) -> None:
        self.current: CanvasNote = content
        self.save: Callable[[CanvasNote], None] = save
        self.frame: QtWidgets.QWidget = detail_frame(475)
        layout = column(self.frame)
        self.title: QtWidgets.QLineEdit = QtWidgets.QLineEdit(content.title)
        self.title.setAccessibleName("Note title")
        self.text: Editor = Editor()
        self.text.setAccessibleName("Canvas note")
        self.text.setPlainText(content.text)
        layout.addWidget(self.title)
        layout.addWidget(self.text)
        layout.addWidget(button("Save note", self.commit, name="primary"))

    def commit(self) -> None:
        self.save(replace(self.current, title=self.title.text(), text=self.text.toPlainText()))


class UpdateDetail:
    def __init__(self, content: CanvasUpdate | CanvasAction, locate: Callable[[str], None]) -> None:
        self.current: CanvasUpdate | CanvasAction = content
        self.locate: Callable[[str], None] = locate
        self.frame: QtWidgets.QWidget = detail_frame(300)
        layout = column(self.frame)
        self.text: Editor = Editor(readonly=True)
        self.text.setAccessibleName("Agent findings")
        layout.addWidget(self.text)
        self.open: QtWidgets.QToolButton = button("Open work thread", self.open_work)
        layout.addWidget(self.open)
        self.refresh(content)

    def refresh(self, content: CanvasUpdate | CanvasAction) -> None:
        self.current = content
        replace_text(self.text, content.text)
        self.open.setVisible(bool(content.work_ids))

    def open_work(self) -> None:
        if self.current.work_ids:
            self.locate(self.current.work_ids[0])


class QuestionDetail:
    """Qt owns content-sized reading and the last visible spoken reply.

    Voice dispatch belongs to Ui; this surface contains no input widgets. The
    last reply stays visible if the task transport rejects it after submission.
    """

    def __init__(self, content: CanvasQuestion) -> None:
        self.current: CanvasQuestion = content
        self.last_reply: str | None = None
        self.frame: QtWidgets.QWidget = detail_frame(1)
        layout = column(self.frame)
        layout.setSpacing(12)
        self.question: QtWidgets.QLabel = label(content.text)
        self.question.setWordWrap(True)
        self.question.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.question.setAccessibleName("Agent clarification")
        layout.addWidget(self.question)
        self.response: QtWidgets.QLabel = label("")
        self.response.setWordWrap(True)
        self.response.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.response.setAccessibleName("Your spoken reply")
        layout.addWidget(self.response)
        self.status: QtWidgets.QLabel = label("", "muted")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"QLabel {{ color: {ACCENT}; font-size: 11px; }}")
        layout.addWidget(self.status)
        self.frame.ensurePolished()
        self.refresh(content)

    def refresh(self, content: CanvasQuestion) -> None:
        self.current = content
        self.question.setText(content.text)
        match content.reply:
            case Attention.WAITING:
                self.status.setText("Hold " + PHYSICAL_NAMES[AGENT] + " to reply · release to send")
                self.response.setText("Previous reply\n" + self.last_reply if self.last_reply is not None else "")
            case Answered(text=text):
                self.last_reply = text
                self.response.setText("You replied\n" + text)
                self.status.setText("Context sent to the agent.")
            case Attention.CLOSED:
                self.response.setText("You replied\n" + self.last_reply if self.last_reply is not None else "")
                self.status.setText("The agent is no longer waiting for this clarification.")
        self.response.setVisible(bool(self.response.text()))
        for text in (self.question, self.response, self.status):
            text.setFixedHeight(max(1, text.heightForWidth(self.frame.width())))
        layout = self.frame.layout()
        if layout is not None:
            layout.activate()
            self.frame.setFixedHeight(layout.sizeHint().height())


type CardDetail = WorkDetail | SourceDetail | NoteDetail | UpdateDetail | QuestionDetail
