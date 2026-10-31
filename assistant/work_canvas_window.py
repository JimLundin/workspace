"""Dedicated desktop canvas; agent administration is created only when requested.

Qt owns the mutable widget lifetimes. Both windows share the same immutable work
observations and command owner, keeping approvals and saved drafts on one path.
"""

from collections.abc import Callable

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.personal_work_panel import PersonalPanel
from assistant.ui_components.canvas_chrome import CanvasFrame, icon_button
from assistant.ui_components.paint_ready import PaintReady
from assistant.ui_components.text import font
from assistant.ui_components.widgets import column, show_window
from assistant.work_canvas import WorkCanvas
from assistant.work_snapshot import WorkSnapshot
from assistant.work_window import WorkWindow
lazy from assistant.meeting_panel import MeetingPanel
lazy from assistant.work_panel import WorkPanel


class CanvasWindow:
    def __init__(self, root: QtWidgets.QApplication, work: WorkWindow, canvas: WorkCanvas) -> None:
        self.root: QtWidgets.QApplication = root
        self.work: WorkWindow = work
        self.snapshot: WorkSnapshot = WorkSnapshot()
        self.preview_prepared: bool = False
        self.presentation: PaintReady | None = None
        self.administration: WorkPanel | None = None
        self.meetings: MeetingPanel | None = None
        self.window: CanvasFrame = CanvasFrame(self.hide, self.escape)
        # Qt resolves native fonts once during desktop preparation. The first
        # visible source preview must not pay that setup cost on a user click.
        QtGui.QFontMetricsF(font()).horizontalAdvance("Workspace")
        self.window.setWindowState(Qt.WindowState.WindowMaximized)
        self.personal: PersonalPanel = PersonalPanel(self.window, work, canvas)
        self.exit_button: QtWidgets.QToolButton = icon_button("close", "Close canvas", self.hide)
        self.personal.toolbar_layout.addWidget(self.exit_button)
        self.personal.position_chrome()
        layout = column(self.window)
        self.layout: QtWidgets.QVBoxLayout = layout
        layout.setSpacing(0)
        layout.addWidget(self.personal.frame)
        self.grip: QtWidgets.QSizeGrip = QtWidgets.QSizeGrip(self.personal.frame)
        self.personal.menu.addSeparator()
        self.personal.menu.addAction("Agent tasks and settings").triggered.connect(self.show_administration)
        self.personal.menu.addAction("Meetings").triggered.connect(self.show_meetings)
        self.personal.menu.addSeparator()
        window_menu = self.personal.menu.addMenu("Window")
        window_menu.addAction("Maximize or restore canvas").triggered.connect(self.maximize)
        window_menu.addAction("Close canvas").triggered.connect(self.hide)
        self.personal.frame.resized.connect(self.position_controls)
        self.position_controls()

    def position_controls(self) -> None:
        self.grip.setGeometry(self.personal.frame.width() - 20, self.personal.frame.height() - 20, 16, 16)
        self.grip.raise_()

    def maximize(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def render(self, snapshot: WorkSnapshot) -> None:
        self.snapshot = snapshot
        self.personal.render(snapshot.personal)
        if not self.preview_prepared and self.personal.visible_cards:
            # Warm the initial visible viewport while the startup view is hidden.
            # Font fallback/shaping stays on Qt; later offscreen previews remain
            # lazy, and normal publications never repeat this one-time painting.
            self.layout.activate()
            self.personal.layout.activate()
            viewport = self.personal.canvas.viewport()
            image = QtGui.QImage(viewport.size(), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(image)
            try:
                self.personal.scene.render(
                    painter,
                    QtCore.QRectF(image.rect()),
                    self.personal.canvas.mapToScene(viewport.rect()).boundingRect(),
                )
            finally:
                painter.end()
            self.preview_prepared = True
        if self.administration is not None:
            self.administration.render(snapshot)

    def show(self, *, focus: bool = True, on_presented: Callable[[], None] | None = None) -> None:
        if self.presentation is not None:
            self.presentation.cancel()
        self.presentation = PaintReady(self.personal.canvas.viewport(), on_presented) if on_presented is not None else None
        # Native maximization resizes several child surfaces synchronously.
        # Paint their final geometry once, after the window state is settled.
        self.window.setUpdatesEnabled(False)
        try:
            show_window(self.window, focus=focus, target=self.personal.canvas)
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
        if not self.personal.escape():
            self.hide()

    def close(self) -> None:
        if self.administration is not None:
            self.administration.close()
        elif self.meetings is not None:
            self.meetings.deleteLater()
        self.hide()
        self.window.deleteLater()
