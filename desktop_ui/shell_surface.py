"""The desktop bar's compact scrollable section of running applications."""

from collections.abc import Callable
from typing import assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.components.appearance import GlassLook, Lettering, Look, SolidLook
from desktop_ui.components.text import color
from desktop_ui.shell_items import Application
from desktop_ui.vector_icons import icon
from winapi.icon_pixels import Pixels
from winapi.tray_host import Click


def pixmap(image: Pixels) -> QtGui.QPixmap:
    """A Qt copy of a shell icon's pixels."""
    copied = QtGui.QImage(image.bgra, image.size, image.size, image.size * 4, QtGui.QImage.Format.Format_ARGB32).copy()
    converted = QtGui.QPixmap()
    converted.convertFromImage(copied)
    return converted


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
            self.setIcon(QtGui.QIcon(pixmap(image)))
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


class HorizontalScroll(QtWidgets.QScrollArea):
    """Qt owns overflow; vertical wheel input moves the horizontal icon strip."""

    @override
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - (event.angleDelta().x() or event.angleDelta().y()))
        event.accept()


class Section(QtWidgets.QWidget):
    """Overflow stays reachable by scrolling horizontally; no icons are silently dropped."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.overflow = HorizontalScroll(self)
        self.body = QtWidgets.QWidget()
        self.row = QtWidgets.QHBoxLayout(self.body)
        self.row.setContentsMargins(6, 0, 6, 0)
        self.row.setSpacing(2)
        self.overflow.setWidget(self.body)
        self.overflow.setWidgetResizable(False)
        self.overflow.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.overflow.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.overflow.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for widget in (self.overflow, self.overflow.viewport(), self.body):
            widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            widget.setAutoFillBackground(False)
        self.buttons: tuple[IconButton, ...] = ()
        self.appearance: Look | None = None
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
        self.body.setFixedSize(max(12, len(buttons) * 34 + 10), 32)

    def apply_look(self, appearance: Look) -> None:
        if appearance == self.appearance:
            return
        self.appearance = appearance
        for button in self.buttons:
            button.apply_look(appearance.lettering)
        self.update()

    def place(self, left: int, right: int) -> None:
        self.setGeometry(left, 8, max(0, min(right - left, self.body.width() + 4)), 34)
        self.overflow.setGeometry(2, 1, max(0, self.width() - 4), 32)
        self.setVisible(bool(self.buttons) and right - left >= 34)

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        outline = QtGui.QPainterPath()
        outline.addRoundedRect(QtCore.QRectF(self.rect()), 17, 17)
        match self.appearance:
            case GlassLook():
                # GlassScene owns the material; this invisible fill keeps native hit testing.
                painter.fillPath(outline, QtGui.QColor(0, 0, 0, 1))
            case SolidLook(fill=fill, edge=edge):
                painter.fillPath(outline, color(fill))
                painter.setPen(QtGui.QPen(color(edge), 1))
                painter.drawPath(outline)
            case None:
                pass
            case _:
                assert_never(self.appearance)


class ShellSections:
    """The surface keeps native buttons only for the current immutable snapshot."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        self.apps = Section(parent)
        self.app_snapshot: tuple[tuple[Application, ...], int] | None = None

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

    def place(self, left: int, width: int, *, start: int = 12) -> None:
        """Apps follow Canvas from `start`, stopping before the leftmost capsule at `left`."""
        self.apps.place(start, max(start, min(left - 12, width // 3)))
