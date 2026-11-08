"""Dedicated desktop canvas window. Qt owns the mutable widget lifetimes."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from cell import Cell
from contracts.canvas_activity import CanvasRun
from contracts.desktop_attention import CanvasFocus
from contracts.meetings import MeetingConversation
from contracts.work_canvas_contracts import CanvasEdits
from contracts.work_canvas_model import CanvasDocument
from contracts.work_snapshot import WorkSnapshot
from desktop_ui.components.appearance import scheme, tokens
from desktop_ui.components.canvas_chrome import CanvasFrame
from desktop_ui.components.canvas_look import Role, face
from desktop_ui.components.paint_ready import PaintReady
from desktop_ui.components.widgets import column, show_window
from desktop_ui.work_canvas_panel import CanvasPanel, WindowControls
from desktop_ui.work_window import WorkWindow


@dataclass(frozen=True, slots=True)
class _Previewed:
    preview_prepared: bool = False
    """The initial visible viewport has been painted once while hidden."""
    presentation: PaintReady | None = None


@dataclass(frozen=True, slots=True, weakref_slot=True)
class CanvasWindow:
    root: QtWidgets.QApplication
    work: WorkWindow
    window: CanvasFrame
    panel: CanvasPanel
    layout: QtWidgets.QVBoxLayout
    grip: QtWidgets.QSizeGrip
    _previewed: Cell[_Previewed] = field(default_factory=lambda: Cell(_Previewed()), init=False, repr=False)

    @classmethod
    def open(cls, root: QtWidgets.QApplication, work: WorkWindow, canvas: CanvasEdits) -> CanvasWindow:
        # The frame and its controls act on the canvas window made just after them.
        def hide() -> None:
            shown.hide()

        def escape() -> None:
            shown.escape()

        def maximize() -> None:
            shown.maximize()

        window = CanvasFrame(hide, escape, tokens(scheme()))
        # Qt resolves native fonts once during desktop preparation. The first
        # visible source preview must not pay that setup cost on a user click.
        QtGui.QFontMetricsF(face(Role.BODY)).horizontalAdvance("Workspace")
        window.setWindowState(Qt.WindowState.WindowMaximized)
        # Window controls are the toolbar's Window section; the toolbar carries no duplicate Close.
        panel = CanvasPanel(window, work, canvas, WindowControls(maximize, hide))
        panel.position_chrome()
        layout = column(window)
        layout.setSpacing(0)
        layout.addWidget(panel.frame)
        grip = QtWidgets.QSizeGrip(panel.frame)
        shown = cls(root, work, window, panel, layout, grip)
        panel.frame.resized.connect(shown.position_controls)
        shown.position_controls()
        return shown

    @property
    def preview_prepared(self) -> bool:
        return self._previewed.get().preview_prepared

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

    def canvas_status(self, text: str) -> None:
        self.panel.status.setText(text)

    def run_refused(self, run: CanvasRun, reason: str) -> None:
        self.panel.run_refused(run, reason)

    def meeting_page(self, transcript_path: str, page: MeetingConversation | None) -> None:
        self.panel.meeting_page(transcript_path, page)

    def show_document(self, document: CanvasDocument) -> None:
        self.panel.show_document(document)

    def open_at(self, identity: str) -> None:
        self.panel.open_at(identity)

    def voice_pressed(self, *, pressed: bool) -> None:
        self.panel.voice_hint.set_pressed(pressed=pressed)

    def maximize(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def render(self, snapshot: WorkSnapshot) -> None:
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
            self._previewed.update(lambda previewed: replace(previewed, preview_prepared=True))

    def show(self, *, focus: bool = True, on_presented: Callable[[], None] | None = None) -> None:
        if (previous := self._previewed.get().presentation) is not None:
            previous.cancel()
        presentation = PaintReady(self.panel.canvas.viewport(), on_presented) if on_presented is not None else None
        self._previewed.update(lambda previewed: replace(previewed, presentation=presentation))
        # Native maximization resizes several child surfaces synchronously.
        # Paint their final geometry once, after the window state is settled.
        self.window.setUpdatesEnabled(False)
        try:
            show_window(self.window, focus=focus, target=self.panel.canvas)
        finally:
            self.window.setUpdatesEnabled(True)

    def hide(self) -> None:
        if (presentation := self._previewed.get().presentation) is not None:
            presentation.cancel()
        self.window.hide()
        self.work.cancel_show(self)

    def escape(self) -> None:
        if not self.panel.escape():
            self.hide()

    def close(self) -> None:
        self.hide()
        self.window.deleteLater()
