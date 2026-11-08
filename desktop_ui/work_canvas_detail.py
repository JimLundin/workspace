"""In-place native card details and revision-bound drafts, owned by Qt."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from cell import Cell
from contracts.canvas_activity import Attention, CanvasAction, CanvasQuestion, CanvasUpdate
from contracts.meeting_presentation import meeting_text
from contracts.meetings import MeetingConversation
from contracts.personal_work import (
    Catalog,
    DismissWork,
    DocumentSource,
    KanbanSource,
    MeetingSource,
    OpenWorkSource,
    OutlookSource,
    SaveWork,
    Source,
    TeamsSource,
    UnlinkWork,
    WebPageSource,
    WorkDefinition,
    WorkState,
    WorkThread,
)
from contracts.task import TextAnswer
from contracts.work_canvas_context import context_path
from contracts.work_canvas_model import CanvasDocument, CanvasNote
from contracts.work_commands import ReadMeeting
from desktop_ui.components.controls import button, label
from desktop_ui.components.widgets import Editor, column, replace_text, row
from desktop_ui.keymap import AGENT_HOLD
from desktop_ui.work_window import WorkWindow


def when(at: float | None) -> str:
    if at is None:
        return "—"
    try:
        return datetime.fromtimestamp(at).strftime("%Y-%m-%d %H:%M")
    except OverflowError, OSError, ValueError:
        return "Outside the local calendar"


def detail_frame(height: int, style: str) -> QtWidgets.QWidget:
    """Set the final canvas style/width before source text triggers Qt layout.

    Details live in graphics proxies, which inherit no stylesheet, so each
    receives the canvas scheme's style before it loads any text.
    """
    frame = QtWidgets.QWidget()
    frame.setStyleSheet(style)
    frame.setFixedSize(448, height)
    return frame


@dataclass(frozen=True, slots=True)
class _Editing:
    current: WorkThread | WorkDefinition
    original: WorkThread | None = None
    """The saved work an edit started from; None for a new work."""
    pending: SaveWork | None = None
    """The save sent and not yet seen published."""


@dataclass(frozen=True, slots=True)
class WorkDetail:
    work: WorkWindow
    frame: QtWidgets.QWidget
    info: QtWidgets.QWidget
    text: Editor
    edit_button: QtWidgets.QToolButton
    done: QtWidgets.QToolButton
    editor: QtWidgets.QWidget
    title: QtWidgets.QLineEdit
    goal: Editor
    summary: Editor
    next_step: Editor
    project: QtWidgets.QLineEdit
    state: QtWidgets.QComboBox
    _editing: Cell[_Editing]

    # Four inputs: the command owner, the content, the canvas style that must
    # precede text layout, and the optional continuation only a saved work offers.
    @classmethod
    def build(
        cls, work: WorkWindow, content: WorkThread | WorkDefinition, style: str, *, on_continue: Callable[[], None] | None = None
    ) -> WorkDetail:
        frame = detail_frame(475, style)
        layout = column(frame)
        info = QtWidgets.QWidget()
        info_layout = column(info)
        text = Editor(readonly=True)
        info_layout.addWidget(text)
        actions = row()

        # Each control acts on the detail made just after it.
        def act(method: Callable[[WorkDetail], None]) -> Callable[[], None]:
            return lambda: method(detail)

        edit_button = button("Edit work", act(WorkDetail.edit))
        done = button("Mark done", act(WorkDetail.change_state))
        actions.addWidget(edit_button)
        actions.addWidget(done)
        actions.addWidget(button("Dismiss work", act(WorkDetail.dismiss)))
        if on_continue is not None:
            actions.addWidget(button("Continue with agent", on_continue))
        info_layout.addLayout(actions)
        layout.addWidget(info)
        editor = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(editor)
        title = QtWidgets.QLineEdit()
        goal, summary, next_step = Editor(), Editor(), Editor()
        project = QtWidgets.QLineEdit()
        state = QtWidgets.QComboBox()
        state.addItems([value.value.capitalize() for value in WorkState])
        for caption, widget in (
            ("Title", title),
            ("Goal", goal),
            ("Situation", summary),
            ("Next step", next_step),
            ("Project", project),
            ("State", state),
        ):
            widget.setAccessibleName("Work " + caption.lower())
            form.addRow(caption, widget)
        for field_editor in (goal, summary, next_step):
            field_editor.setFixedHeight(80)
        edit_actions = row()
        edit_actions.addWidget(button("Save work", act(WorkDetail.save), name="primary"))
        edit_actions.addWidget(button("Cancel edit", act(WorkDetail.cancel)))
        form.addRow(edit_actions)
        layout.addWidget(editor)
        editor.hide()
        detail = cls(work, frame, info, text, edit_button, done, editor, title, goal, summary, next_step, project, state, Cell(_Editing(content)))
        match content:
            case WorkThread():
                detail.refresh(content)
            case WorkDefinition():
                detail.edit()
        return detail

    @property
    def current(self) -> WorkThread | WorkDefinition:
        return self._editing.get().current

    @property
    def pending(self) -> SaveWork | None:
        return self._editing.get().pending

    def refresh(self, content: WorkThread) -> None:
        editing = self._editing.update(lambda editing: replace(editing, current=content))
        definition = content.definition
        replace_text(
            self.text,
            f"Goal\n{definition.goal}\n\nCurrent situation\n{definition.summary or 'No summary yet.'}"
            + f"\n\nNext step\n{definition.next_step or 'No next step identified.'}\n\nUpdated {when(content.updated_at)}",
        )
        self.done.setText("Reopen" if definition.state is WorkState.DONE else "Mark done")
        # Background publications refresh information, never replace edit fields.
        pending, original = editing.pending, editing.original
        if (
            pending is not None
            and definition == pending.definition
            and content.links == pending.links
            and (original is None or content.revision > original.revision)
        ):
            self.cancel()

    def edit(self) -> None:
        match self.current:
            case WorkThread(definition=definition) as original:
                self._editing.update(lambda editing: replace(editing, original=original))
            case WorkDefinition() as definition:
                self._editing.update(lambda editing: replace(editing, original=None))
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
        self._editing.update(lambda editing: replace(editing, original=None, pending=None))

    def save(self) -> None:
        definition = WorkDefinition(
            self.title.text(),
            self.goal.toPlainText(),
            self.summary.toPlainText(),
            self.next_step.toPlainText(),
            tuple(WorkState)[self.state.currentIndex()],
            self.project.text(),
        )
        original = self._editing.get().original
        command = SaveWork(definition, original.links if original else (), original.id if original else None, original.revision if original else None)
        if self.work.send(command):
            self._editing.update(lambda editing: replace(editing, pending=command))

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


@dataclass(frozen=True, slots=True)
class _Reading:
    current: Source
    conversation: MeetingConversation | None = None
    """Qt owns this bounded reading cursor. No audio or full transcript is copied into the catalog."""
    catalog: Catalog = field(default_factory=Catalog)
    ancestry: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class SourceDetail:
    work: WorkWindow
    frame: QtWidgets.QWidget
    text: Editor
    more: QtWidgets.QToolButton
    connections: QtWidgets.QComboBox
    reason: Editor
    open: QtWidgets.QToolButton
    unlink: QtWidgets.QToolButton
    _reading: Cell[_Reading]

    # Four inputs, as WorkDetail: the canvas style must precede the source text's layout.
    @classmethod
    def build(cls, work: WorkWindow, content: Source, style: str, *, on_context: Callable[[str], None] | None = None) -> SourceDetail:
        frame = detail_frame(475, style)
        layout = column(frame)
        text = Editor(readonly=True)
        text.setAccessibleName("Observed source content")
        layout.addWidget(text, 3)

        # Each control acts on the detail made just after it.
        def act(method: Callable[[SourceDetail], None]) -> Callable[[], None]:
            return lambda: method(detail)

        more = button("Read more conversation", act(SourceDetail.read_more))
        more.setVisible(False)
        layout.addWidget(more)
        layout.addWidget(label("Connected work", "muted"))
        connections = QtWidgets.QComboBox()
        connections.setAccessibleName("Work connected to this source")
        layout.addWidget(connections)
        reason = Editor(readonly=True)
        reason.setAccessibleName("Why this source is connected")
        layout.addWidget(reason, 1)
        actions = row()
        opener = button("Open in Edge", act(SourceDetail.open_source))
        unlink = button("Remove connection", act(SourceDetail.remove))
        actions.addWidget(opener)
        actions.addWidget(unlink)
        if on_context is not None:
            layout.addWidget(button("Show work on canvas", lambda: detail.open_context(on_context)))
        layout.addLayout(actions)

        def reasoned(_index: int) -> None:
            detail.render_reason()

        connections.currentIndexChanged.connect(reasoned)
        # Resolve the source editor's inherited font and final wrapping width
        # before loading full mail text, rather than wrapping again on embedding.
        frame.ensurePolished()
        layout.activate()
        detail = cls(work, frame, text, more, connections, reason, opener, unlink, Cell(_Reading(content)))
        return detail

    @property
    def current(self) -> Source:
        return self._reading.get().current

    def refresh(self, content: Source, catalog: Catalog, document: CanvasDocument) -> None:
        ancestry = frozenset(context_path(content.id, catalog, document)) | {content.id}
        reading = self._reading.update(lambda reading: replace(reading, current=content, catalog=catalog, ancestry=ancestry))
        match content:
            case MeetingSource(meeting=meeting):
                self.open.setText("Open transcript")
                if reading.conversation is None or reading.conversation.meeting.revision != meeting.revision:
                    self.read_conversation(0)
            case DocumentSource() | WebPageSource():
                self.open.setText("Open original")
                replace_text(self.text, f"Observed {when(content.observed_at)}\n\n{content.url}\n\n{content.excerpt}")
            case TeamsSource() | OutlookSource() | KanbanSource():
                self.open.setText("Open in Edge")
                replace_text(self.text, f"Observed {when(content.observed_at)}\n\n{content.excerpt}")
        previous: object = self.connections.currentData()
        self.connections.clear()
        for item in catalog.works:
            if item.id in ancestry or any(link.source_id in ancestry for link in item.links):
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
                return next((item for item in self._reading.get().catalog.works if item.id == identity), None)
            case _:
                return None

    def open_context(self, callback: Callable[[str], None]) -> None:
        selected = self.selected()
        if selected is not None:
            callback(selected.id)

    def render_reason(self) -> None:
        reading = self._reading.get()
        work = self.selected()
        association = next((link for link in work.links if link.source_id in reading.ancestry), None) if work else None
        reason = (
            ("Through the containing bubble: " if association.source_id != reading.current.id else "") + association.reason if association else None
        )
        replace_text(self.reason, reason if reason else "Collected inside this work context." if work else "No work is connected yet.")
        self.unlink.setEnabled(association is not None and association.source_id == reading.current.id)

    def remove(self) -> None:
        work = self.selected()
        if work is not None:
            self.work.send(UnlinkWork(work.id, self.current.id, work.revision))

    def open_source(self) -> None:
        match self.current:
            case MeetingSource(id=identity):
                self.work.send(OpenWorkSource(identity))
            case DocumentSource(url=url):
                if not QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)):
                    self.work.problem("Windows could not open this document.")
            case current:
                self.work.send(OpenWorkSource(current.parent_id or current.id))

    def read_conversation(self, offset: int) -> None:
        match self.current:
            case MeetingSource(meeting=meeting):
                # The assistant owns the meeting's journal; its page arrives in `show_page`.
                if not self.work.send(ReadMeeting(meeting.transcript_path, offset)):
                    self.show_page(meeting.transcript_path, None)
            case _:
                pass

    def show_page(self, transcript_path: str, page: MeetingConversation | None) -> None:
        """The assistant's answer to `read_conversation`, if it is still this detail's meeting."""
        match self.current:
            case MeetingSource(meeting=meeting) if meeting.transcript_path == transcript_path:
                if page is None:
                    replace_text(self.text, "This meeting's conversation could not be read. Check access to its saved folder and try again.")
                    self.more.setVisible(False)
                    return
                self._reading.update(lambda reading: replace(reading, conversation=page))
                replace_text(self.text, meeting_text(page))
                self.more.setVisible(page.next_offset is not None)
            case _:
                pass

    def read_more(self) -> None:
        conversation = self._reading.get().conversation
        if conversation is not None and conversation.next_offset is not None:
            self.read_conversation(conversation.next_offset)


@dataclass(frozen=True, slots=True)
class NoteDetail:
    current: CanvasNote
    save: Callable[[CanvasNote], None]
    frame: QtWidgets.QWidget
    title: QtWidgets.QLineEdit
    text: Editor

    @classmethod
    def build(cls, content: CanvasNote, save: Callable[[CanvasNote], None], style: str) -> NoteDetail:
        frame = detail_frame(475, style)
        layout = column(frame)
        title = QtWidgets.QLineEdit(content.title)
        title.setAccessibleName("Note title")
        text = Editor()
        text.setAccessibleName("Canvas note")
        text.setPlainText(content.text)
        detail = cls(content, save, frame, title, text)
        layout.addWidget(title)
        layout.addWidget(text)
        layout.addWidget(button("Save note", detail.commit, name="primary"))
        return detail

    def commit(self) -> None:
        self.save(replace(self.current, title=self.title.text(), text=self.text.toPlainText()))


@dataclass(frozen=True, slots=True)
class UpdateDetail:
    locate: Callable[[str], None]
    frame: QtWidgets.QWidget
    text: Editor
    open: QtWidgets.QToolButton
    _current: Cell[CanvasUpdate | CanvasAction]

    @classmethod
    def build(cls, content: CanvasUpdate | CanvasAction, locate: Callable[[str], None], style: str) -> UpdateDetail:
        frame = detail_frame(300, style)
        layout = column(frame)
        text = Editor(readonly=True)
        text.setAccessibleName("Agent findings")
        layout.addWidget(text)

        # Each control acts on the detail made just after it.
        def act(method: Callable[[UpdateDetail], None]) -> Callable[[], None]:
            return lambda: method(detail)

        opener = button("Open work thread", act(UpdateDetail.open_work))
        layout.addWidget(opener)
        detail = cls(locate, frame, text, opener, Cell(content))
        detail.refresh(content)
        return detail

    def refresh(self, content: CanvasUpdate | CanvasAction) -> None:
        self._current.set(content)
        replace_text(self.text, content.text)
        self.open.setVisible(bool(content.work_ids))

    def open_work(self) -> None:
        if work_ids := self._current.get().work_ids:
            self.locate(work_ids[0])


@dataclass(frozen=True, slots=True)
class _Asked:
    current: CanvasQuestion
    last_reply: str | None = None


@dataclass(frozen=True, slots=True)
class QuestionDetail:
    """Qt owns content-sized reading and the last visible spoken reply.

    Voice dispatch belongs to Ui; this surface contains no input widgets. The
    last reply stays visible if the task transport rejects it after submission.
    """

    frame: QtWidgets.QWidget
    question: QtWidgets.QLabel
    response: QtWidgets.QLabel
    status: QtWidgets.QLabel
    _asked: Cell[_Asked]

    @classmethod
    def build(cls, content: CanvasQuestion, style: str) -> QuestionDetail:
        frame = detail_frame(1, style)
        layout = column(frame)
        layout.setSpacing(12)
        question = label(content.text)
        question.setWordWrap(True)
        question.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        question.setAccessibleName("Agent clarification")
        layout.addWidget(question)
        response = label("")
        response.setWordWrap(True)
        response.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        response.setAccessibleName("Your spoken reply")
        layout.addWidget(response)
        status = label("", "muted")
        status.setWordWrap(True)
        layout.addWidget(status)
        frame.ensurePolished()
        detail = cls(frame, question, response, status, Cell(_Asked(content)))
        detail.refresh(content)
        return detail

    def refresh(self, content: CanvasQuestion) -> None:
        self.question.setText(content.text)
        match content.reply:
            case Attention.WAITING:
                last_reply = self._asked.update(lambda asked: replace(asked, current=content)).last_reply
                self.status.setText(AGENT_HOLD + " to reply · release to send")
                self.response.setText("Previous reply\n" + last_reply if last_reply is not None else "")
            case TextAnswer(text=text):
                self._asked.set(_Asked(content, text))
                self.response.setText("You replied\n" + text)
                self.status.setText("Context sent to the agent.")
            case Attention.CLOSED:
                last_reply = self._asked.update(lambda asked: replace(asked, current=content)).last_reply
                self.response.setText("You replied\n" + last_reply if last_reply is not None else "")
                self.status.setText("The agent is no longer waiting for this clarification.")
        self.response.setVisible(bool(self.response.text()))
        for text_label in (self.question, self.response, self.status):
            text_label.setFixedHeight(max(1, text_label.heightForWidth(self.frame.width())))
        layout = self.frame.layout()
        if layout is not None:
            layout.activate()
            self.frame.setFixedHeight(layout.sizeHint().height())


type CardDetail = WorkDetail | SourceDetail | NoteDetail | UpdateDetail | QuestionDetail
