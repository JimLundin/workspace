"""Dedicated desktop canvas; agent administration is created only when requested.

Qt owns the mutable widget lifetimes. Both windows share the same immutable work
observations and command owner, keeping approvals and saved drafts on one path.
"""

from collections.abc import Callable
from pathlib import Path

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.work_canvas_contracts import CanvasEdits
from assistant.work_canvas_model import CanvasDocument
from assistant.work_snapshot import WorkSnapshot
from desktop_ui.components.appearance import scheme, tokens
from desktop_ui.components.canvas_chrome import CanvasFrame
from desktop_ui.components.canvas_look import Role, face
from desktop_ui.components.paint_ready import PaintReady
from desktop_ui.components.widgets import column, show_window
from desktop_ui.desktop_attention import CanvasFocus
from desktop_ui.work_canvas_panel import CanvasPanel, rounded
from desktop_ui.work_window import WorkWindow
lazy from assistant.meeting_workflow import MeetingSnapshot, MeetingWorkflow
lazy from desktop_ui.meeting_panel import MeetingPanel
lazy from desktop_ui.work_panel import WorkPanel


class CanvasWindow:
    def __init__(self, root: QtWidgets.QApplication, work: WorkWindow, canvas: CanvasEdits) -> None:
        self.root: QtWidgets.QApplication = root
        self.work: WorkWindow = work
        self.snapshot: WorkSnapshot = WorkSnapshot()
        self.preview_prepared: bool = False
        self.presentation: PaintReady | None = None
        self.administration: WorkPanel | None = None
        self.meetings: MeetingPanel | None = None
        self.window: CanvasFrame = CanvasFrame(self.hide, self.escape, tokens(scheme()))
        # Qt resolves native fonts once during desktop preparation. The first
        # visible source preview must not pay that setup cost on a user click.
        QtGui.QFontMetricsF(face(Role.BODY)).horizontalAdvance("Workspace")
        self.window.setWindowState(Qt.WindowState.WindowMaximized)
        self.panel: CanvasPanel = CanvasPanel(self.window, work, canvas)
        self.panel.position_chrome()
        layout = column(self.window)
        self.layout: QtWidgets.QVBoxLayout = layout
        layout.setSpacing(0)
        layout.addWidget(self.panel.frame)
        self.grip: QtWidgets.QSizeGrip = QtWidgets.QSizeGrip(self.panel.frame)
        self.panel.menu.addSeparator()
        self.panel.menu.addAction("Agent tasks and settings").triggered.connect(self.show_administration)
        self.panel.menu.addAction("Meetings").triggered.connect(self.show_meetings)
        self.panel.menu.addSeparator()
        # Window controls live in the options menu; the island carries no duplicate Close.
        window_menu = rounded(self.panel.menu.addMenu("Window"))
        window_menu.addAction("Maximize or restore canvas").triggered.connect(self.maximize)
        self.close_action: QtGui.QAction = window_menu.addAction("Close canvas")
        self.close_action.triggered.connect(self.hide)
        self.panel.frame.resized.connect(self.position_controls)
        self.position_controls()

    def position_controls(self) -> None:
        self.grip.setGeometry(self.panel.frame.width() - 20, self.panel.frame.height() - 20, 16, 16)
        self.grip.raise_()

    def focus(self) -> CanvasFocus:
        """Publish only the canvas observation needed by desktop attention policy."""
        return CanvasFocus(selected=self.panel.selected, visible=self.panel.frame.isVisible(), active=self.window.isActiveWindow())

    def instruct(self, text: str) -> bool:
        return self.panel.send_instruction(text)

    def reply_failed(self) -> None:
        self.panel.status.setText("This reply could not be sent. Your transcript is available with Copy latest transcript.")

    def show_document(self, document: CanvasDocument) -> None:
        self.panel.show_document(document)

    def open_at(self, identity: str) -> None:
        self.panel.open_at(identity)

    def voice_pressed(self, *, pressed: bool) -> None:
        self.panel.voice_hint.set_pressed(pressed=pressed)

    def configure_meetings(self, workflow: MeetingWorkflow, open_file: Callable[[Path], None]) -> None:
        """Create and retain the view's meeting widgets once, on Qt's thread."""
        if self.meetings is None:
            self.attach_meetings(MeetingPanel(workflow, open_file=open_file))

    def render_meetings(self, snapshot: MeetingSnapshot) -> None:
        if self.meetings is not None:
            self.meetings.render_snapshot(snapshot)

    def maximize(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def render(self, snapshot: WorkSnapshot) -> None:
        self.snapshot = snapshot
        self.panel.render(snapshot.personal)
        if not self.preview_prepared and self.panel.visible_cards:
            # Warm the initial visible viewport while the startup view is hidden.
            # Font fallback/shaping stays on Qt; later offscreen previews remain
            # lazy, and normal publications never repeat this one-time painting.
            self.layout.activate()
            self.panel.layout.activate()
            viewport = self.panel.canvas.viewport()
            image = QtGui.QImage(viewport.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(image)
            try:
                self.panel.scene.render(
                    painter,
                    QtCore.QRectF(image.rect()),
                    self.panel.canvas.mapToScene(viewport.rect()).boundingRect(),
                )
            finally:
                painter.end()
            self.preview_prepared = True
        if self.administration is not None:
            self.administration.render(snapshot)

    def show(self, *, focus: bool = True, on_presented: Callable[[], None] | None = None) -> None:
        if self.presentation is not None:
            self.presentation.cancel()
        self.presentation = PaintReady(self.panel.canvas.viewport(), on_presented) if on_presented is not None else None
        # Native maximization resizes several child surfaces synchronously.
        # Paint their final geometry once, after the window state is settled.
        self.window.setUpdatesEnabled(False)
        try:
            show_window(self.window, focus=focus, target=self.panel.canvas)
        finally:
            self.window.setUpdatesEnabled(True)

    def task_panel(self) -> WorkPanel:
        if self.administration is None:
            self.administration = WorkPanel(self.root, self.work)
            if self.meetings is not None:
                self.administration.attach_meetings(self.meetings)
            self.administration.render(self.snapshot)
        return self.administration

    def show_administration(self) -> None:
        self.task_panel().show()

    def attach_meetings(self, meetings: MeetingPanel) -> None:
        if self.meetings is None:
            self.meetings = meetings
            meetings.hide()
            if self.administration is not None:
                self.administration.attach_meetings(meetings)

    def show_meetings(self) -> None:
        if self.meetings is not None:
            panel = self.task_panel()
            panel.show_meetings()
            panel.show()

    def hide(self) -> None:
        if self.presentation is not None:
            self.presentation.cancel()
        self.window.hide()
        self.work.cancel_show(self)

    def escape(self) -> None:
        if not self.panel.escape():
            self.hide()

    def close(self) -> None:
        if self.administration is not None:
            self.administration.close()
        elif self.meetings is not None:
            self.meetings.deleteLater()
        self.hide()
        self.window.deleteLater()
