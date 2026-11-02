"""Native dialogs and their presentation through a small Qt-thread host."""

from collections.abc import Callable
from typing import Protocol

lazy import shiboken6
lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.qt_runtime import prepare
from winapi import windows
from winapi.shapes import Rect
lazy from assistant.geometry import region
lazy from desktop_ui.components.appearance import GLASS_ACCENT
lazy from desktop_ui.components.controls import button
lazy from desktop_ui.components.widgets import Editor, Window, column, row, show_window

prepare()


type Job = Callable[[QtWidgets.QApplication], None]


def bring_forward(window: QtWidgets.QWidget, focus: QtWidgets.QWidget) -> None:
    show_window(window, focus=True, target=focus)


def near_pointer(window: QtWidgets.QWidget, width: int, height: int) -> None:
    point = QtGui.QCursor.pos()
    display = QtWidgets.QApplication.screenAt(point) or window.screen()
    area = display.availableGeometry()
    window.resize(width, height)
    window.move(
        max(area.left(), min(point.x() - width // 2, area.right() - width)), max(area.top(), min(point.y() - height // 3, area.bottom() - height))
    )


class Presentation(Protocol):
    """Position and reveal native dialogs on their owning Qt thread."""

    def position(self, window: QtWidgets.QWidget, width: int, height: int) -> None: ...

    def reveal(self, window: QtWidgets.QWidget, focus: QtWidgets.QWidget) -> None: ...


class NativePresentation:
    __slots__ = ()

    def position(self, window: QtWidgets.QWidget, width: int, height: int) -> None:
        near_pointer(window, width, height)

    def reveal(self, window: QtWidgets.QWidget, focus: QtWidgets.QWidget) -> None:
        bring_forward(window, focus)


class DialogHost(Protocol):
    """Post dialog updates and present windows through their Qt-thread owner."""

    presentation: Presentation

    def post(self, job: Job) -> None: ...


class RegionPicker(QtWidgets.QWidget):
    def __init__(self, area: Rect, done: Callable[[Rect | None], object]) -> None:
        super().__init__()
        self.area, self.done = area, done
        self.start: QtCore.QPointF | None = None
        self.current: QtCore.QPointF | None = None
        self.finished = False
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        windows.move(int(self.winId()), area)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        dim = QtGui.QPainterPath()
        dim.addRect(QtCore.QRectF(self.rect()))
        if self.start is not None and self.current is not None:
            chosen = QtCore.QRectF(self.start, self.current).normalized()
            hole = QtGui.QPainterPath()
            hole.addRect(chosen)
            painter.fillPath(dim.subtracted(hole), QtGui.QColor(0, 0, 0, 92))
            painter.setPen(QtGui.QPen(QtGui.QColor(GLASS_ACCENT), 2))
            painter.drawRect(chosen)
        else:
            painter.fillPath(dim, QtGui.QColor(0, 0, 0, 92))

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.finish(None)
        else:
            self.start = self.current = event.position()
            self.update()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        self.current = event.position()
        self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self.start is not None and event.button() == Qt.MouseButton.LeftButton:
            scale = self.devicePixelRatioF()
            first = (self.area.left + round(self.start.x() * scale), self.area.top + round(self.start.y() * scale))
            last = (self.area.left + round(event.position().x() * scale), self.area.top + round(event.position().y() * scale))
            area = region(first, last)
            self.finish(area if area.width > 4 and area.height > 4 else None)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.finish(None)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.finish(None)
        event.accept()

    def finish(self, area: Rect | None) -> None:
        if not self.finished:
            self.finished = True
            self.hide()
            self.done(area)
            self.deleteLater()


class AnswerWindow:
    __slots__ = (
        "__weakref__",
        "entry",
        "follow_up",
        "host",
        "text",
        "window",
    )

    def __init__(self, host: DialogHost, title: str, follow_up: Callable[[str], None]) -> None:
        self.host: DialogHost = host
        self.follow_up: Callable[[str], None] = follow_up
        self.window = Window(title[:80], self.close, width=760, height=540)
        layout = column(self.window)
        layout.setContentsMargins(20, 18, 20, 18)
        self.text = Editor(readonly=True)
        layout.addWidget(self.text, 1)
        bottom = row()
        self.entry = QtWidgets.QLineEdit()
        self.entry.setPlaceholderText("Ask a follow-up…")
        self.entry.setEnabled(False)
        self.entry.returnPressed.connect(self.ask)
        bottom.addWidget(self.entry, 1)
        bottom.addWidget(button("Copy answer", self.copy_all, name="filled"))
        layout.addLayout(bottom)
        self.add(f"{title}\n\n", "accent")
        host.presentation.position(self.window, 760, 540)
        host.presentation.reveal(self.window, self.text)

    def close(self) -> None:
        self.window.hide()
        self.window.deleteLater()

    def add(self, text: str, tag: str = "") -> None:
        def job(_: QtWidgets.QApplication) -> None:
            if shiboken6.isValid(self.window):
                cursor = self.text.textCursor()
                cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
                cursor.insertText(text)
                self.text.setTextCursor(cursor)
                self.text.ensureCursorVisible()

        self.host.post(job)

    def all_text(self) -> str:
        return self.text.toPlainText()

    def copy_all(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self.all_text())

    def ask(self) -> None:
        if question := self.entry.text().strip():
            self.entry.clear()
            self.entry.setEnabled(False)
            self.add(f"\n\n{question}\n\n", "accent")
            self.follow_up(question)

    def write(self, text: str) -> None:
        self.add(text)

    def finish(self) -> None:
        def job(_: QtWidgets.QApplication) -> None:
            if shiboken6.isValid(self.window):
                self.entry.setEnabled(True)
                self.entry.setFocus()

        self.host.post(job)

    def fail(self, message: str) -> None:
        self.add(f"\n{message}\n", "error")
        self.finish()
