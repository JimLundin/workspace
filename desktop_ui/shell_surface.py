"""Compact scrollable app and tray sections on the desktop bar."""

from collections.abc import Callable
from typing import assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.components.appearance import GlassLook, Lettering, Look, Shade, SolidLook
from desktop_ui.shell_items import Application
from desktop_ui.vector_icons import icon
from winapi.icon_pixels import Pixels
from winapi.shapes import Rect
from winapi.tray_host import Click, Entry, Located


class IconButton(QtWidgets.QToolButton):
    """One accessible shell item; Qt owns its icon and pointer state."""

    def __init__(self, parent: QtWidgets.QWidget, invoke: Callable[[Click], None]) -> None:
        super().__init__(parent)
        self.invoke = invoke
        self.active: bool = False
        self.fallback: bool = False
        self.setFixedSize(32, 32)
        self.setIconSize(QtCore.QSize(22, 22))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(lambda: self.invoke(Click.LEFT))

    def display(self, title: str, image: Pixels | None, *, active: bool) -> None:
        self.active = active
        self.fallback = image is None
        self.setToolTip(title)
        self.setAccessibleName(title)
        if image is not None:
            copied = QtGui.QImage(image.bgra, image.size, image.size, image.size * 4, QtGui.QImage.Format.Format_ARGB32).copy()
            pixmap = QtGui.QPixmap()
            pixmap.convertFromImage(copied)
            self.setIcon(QtGui.QIcon(pixmap))
        else:
            self.setIcon(icon("window", "#eeeeee", 22))

    def apply_look(self, lettering: Lettering) -> None:
        if self.fallback:
            self.setIcon(icon("window", lettering.ink.color, 22))
        background = lettering.press.css if self.active else "transparent"
        self.setStyleSheet(
            f"QToolButton {{border:0; border-radius:8px; background:{background};}}"
            f"QToolButton:hover {{background:{lettering.hover.css};}}"
            f"QToolButton:pressed {{background:{lettering.press.css};}}"
            f"QToolButton:focus {{border:1px solid {lettering.ink.css};}}"
        )

    @override
    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.RightButton:
            self.invoke(Click.RIGHT)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    @override
    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self.invoke(Click.DOUBLE)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class Section(QtWidgets.QScrollArea):
    """Overflow stays reachable by scrolling horizontally; no icons are silently dropped."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.body = QtWidgets.QWidget()
        self.row = QtWidgets.QHBoxLayout(self.body)
        self.row.setContentsMargins(4, 0, 4, 0)
        self.row.setSpacing(2)
        self.setWidget(self.body)
        self.setWidgetResizable(False)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QScrollArea {background:rgba(24,24,28,225); border:1px solid rgba(255,255,255,30); border-radius:17px;}"
            "QScrollArea > QWidget > QWidget {background:transparent;}"
        )
        self.buttons: tuple[IconButton, ...] = ()
        self.appearance: Look | None = None
        self.viewport().setAutoFillBackground(False)
        self.body.setAutoFillBackground(False)
        self.hide()

    def reset(self) -> None:
        for button in self.buttons:
            self.row.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.buttons = ()

    def finish(self, buttons: tuple[IconButton, ...]) -> None:
        self.buttons = buttons
        for button in buttons:
            self.row.addWidget(button)
            if self.appearance is not None:
                button.apply_look(self.appearance.lettering)
        self.body.setFixedSize(max(8, len(buttons) * 34 + 6), 32)

    def apply_look(self, appearance: Look) -> None:
        if appearance == self.appearance:
            return
        self.appearance = appearance
        match appearance:
            case SolidLook(fill=fill, edge=edge):
                pass
            case GlassLook():
                fill, edge = Shade("#000000", 1 / 255), Shade("#000000", 0)
            case _:
                assert_never(appearance)
        self.setStyleSheet(
            f"QScrollArea {{background:{fill.css}; border:1px solid {edge.css}; border-radius:17px;}}"
            "QScrollArea > QWidget > QWidget {background:transparent;}"
        )
        for button in self.buttons:
            button.apply_look(appearance.lettering)

    def place(self, left: int, right: int) -> None:
        self.setGeometry(left, 8, max(0, min(right - left, self.body.width() + 2)), 34)
        self.setVisible(bool(self.buttons) and right - left >= 34)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - (event.angleDelta().x() or event.angleDelta().y()))
        event.accept()


class ShellSections:
    """The surface keeps native buttons only for the current immutable snapshot."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        self.apps = Section(parent)
        self.tray = Section(parent)
        self.app_snapshot: tuple[tuple[Application, ...], int] | None = None
        self.tray_snapshot: tuple[Entry, ...] | None = None

    def applications(self, snapshot: tuple[tuple[Application, ...], int], invoke: Callable[[Application, Click], None]) -> None:
        if snapshot == self.app_snapshot:
            return
        self.apps.reset()
        apps, foreground = snapshot

        def button(app: Application) -> IconButton:
            created = IconButton(self.apps.body, lambda click: invoke(app, click))
            created.display(
                app.identity.removesuffix(".exe") + " · " + str(len(app.windows)) + " windows",
                app.image,
                active=any(window.handle == foreground for window in app.windows),
            )
            return created

        self.apps.finish(tuple(button(app) for app in apps))
        self.app_snapshot = snapshot

    def notifications(self, entries: tuple[Entry, ...], invoke: Callable[[Entry, Click], None]) -> None:
        if entries == self.tray_snapshot:
            return
        self.tray.reset()

        def button(entry: Entry) -> IconButton:
            created = IconButton(self.tray.body, lambda click: invoke(entry, click))
            created.display(entry.tip or "Tray application", entry.image, active=False)
            return created

        self.tray.finish(tuple(button(entry) for entry in entries))
        self.tray_snapshot = entries

    def place(self, bounds: tuple[int, int], width: int) -> None:
        left, right = bounds
        self.apps.place(12, max(12, left - 12))
        tray_width = min(self.tray.body.width() + 2, max(0, width - right - 24))
        self.tray.place(width - 12 - tray_width, width - 12)

    def locations(self, outer: Rect, scale: float) -> tuple[Located, ...]:
        if self.tray_snapshot is None or not self.tray.isVisible():
            return ()
        parent = self.tray.window()

        def located(entry: Entry, button: IconButton) -> Located:
            point = button.mapTo(parent, QtCore.QPoint())
            left, top = outer.left + round(point.x() * scale), outer.top + round(point.y() * scale)
            return Located(entry, Rect(left, top, left + round(button.width() * scale), top + round(button.height() * scale)))

        return tuple(located(entry, button) for entry, button in zip(self.tray_snapshot, self.tray.buttons, strict=True))
