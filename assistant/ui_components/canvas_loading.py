"""A compact, nonactivating indicator retained until the canvas paints a frame."""

from collections.abc import Callable

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.qt_ui import EventLoop
from assistant.view_publication import log_view
from winapi.appearance import animations_enabled
lazy from winapi.composition_spinner import CompositionSpinner


class CanvasLoading:
    """The UI owns target/dispatcher lifetime, including the native cursor fallback."""

    def __init__(self, root: QtWidgets.QApplication, *, paint_frame: Callable[[], None] | None = None) -> None:
        self.root: QtWidgets.QApplication = root
        self.paint_frame: Callable[[], None] = (
            (lambda: root.processEvents(QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)) if paint_frame is None else paint_frame
        )
        self.loop: EventLoop | None = None
        self.spinner: CompositionSpinner | None = None
        self.closed: bool = False
        self.wait_cursor: bool = False

    def show(self) -> None:
        self.loop = EventLoop(self.root, self.paint_frame)
        composition = self.loop.composition
        if composition is not None:
            try:
                self.spinner = CompositionSpinner(composition)
                self.spinner.show(animate=animations_enabled())
            except OSError as error:
                log_view(f"Canvas loading composition unavailable; using the native wait cursor: {error}")
                if self.spinner is not None:
                    self.spinner.close()
                    self.spinner = None
        if self.spinner is None:
            self.root.setOverrideCursor(QtGui.QCursor(Qt.CursorShape.WaitCursor))
            self.wait_cursor = True
        # Commit the small native surface before synchronous view construction.
        # Its HWND remains intact while Qt builds and paints the real canvas.
        self.paint_frame()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.spinner is not None:
            self.spinner.close()
        if self.wait_cursor:
            self.root.restoreOverrideCursor()
            self.wait_cursor = False
        if self.loop is not None:
            self.loop.close()
