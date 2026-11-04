"""The desktop bar's compact sections: pinned slots, the desktop pager and the scrollable running applications."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.components import typeface
from desktop_ui.components.appearance import GlassLook, Lettering, Look, SolidLook
from desktop_ui.components.text import color
from desktop_ui.desktop_pager import PagerView
from desktop_ui.navigation import Navigation, PagerClick, Source, StepDesktop
from desktop_ui.shell_items import WEB_APPS, Application, Item, Pinned, Shelf
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
        self.glyph: str | None = None
        self.setFixedSize(32, 32)
        self.setIconSize(QtCore.QSize(22, 22))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(lambda: self.invoke(Click.LEFT))

    def display(self, title: str, face: Pixels | str, *, active: bool) -> None:
        """`face` is the application's own icon, or a symbol painted in the bar's ink."""
        self.active = active
        self.setToolTip(title)
        self.setAccessibleName(title)
        match face:
            case Pixels():
                self.glyph = None
                self.setIcon(QtGui.QIcon(pixmap(face)))
            case str():
                self.glyph = face
                self.setIcon(icon(face, "#eeeeee", 22))

    def apply_look(self, lettering: Lettering) -> None:
        if self.glyph is not None:
            self.setIcon(icon(self.glyph, lettering.ink.color, 22))
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


def page_font() -> QtGui.QFont:
    value = QtGui.QFont(typeface.FAMILY)
    value.setPixelSize(12)
    value.setWeight(QtGui.QFont.Weight.Medium)
    value.setFeature(QtGui.QFont.Tag("tnum"), 1)
    return value


@dataclass(frozen=True, slots=True)
class Glyph:
    name: str


@dataclass(frozen=True, slots=True)
class Page:
    """One pager target as shown: its accessible name, its face (a symbol or text) and whether it's current."""

    name: str
    face: Glyph | str
    active: bool = field(default=False, kw_only=True)


class PageButton(QtWidgets.QToolButton):
    """One pager target: a desktop's number, an end's chevron, or the keycap reaching it while the Apps layer is up."""

    def __init__(self, parent: QtWidgets.QWidget, invoke: Callable[[], None]) -> None:
        super().__init__(parent)
        self.active = False
        self.glyph: str | None = None
        self.setFont(page_font())
        self.setIconSize(QtCore.QSize(16, 16))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(invoke)

    def display(self, page: Page) -> None:
        self.active = page.active
        self.setToolTip(page.name)
        self.setAccessibleName(page.name)
        match page.face:
            case Glyph(name=name):
                self.glyph = name
                self.setText("")
                self.setIcon(icon(name, "#eeeeee", 16))
                self.setFixedSize(24, 32)
            case str() as text:
                self.glyph = None
                self.setText(text)
                self.setIcon(QtGui.QIcon())
                self.setFixedSize(max(24, self.fontMetrics().horizontalAdvance(text) + 14), 32)

    def apply_look(self, lettering: Lettering) -> None:
        if self.glyph is not None:
            self.setIcon(icon(self.glyph, lettering.ink.color, 16))
        background = lettering.press.css if self.active else "transparent"
        self.setStyleSheet(
            f"QToolButton {{border:0; border-radius:8px; background:{background}; color:{lettering.ink.css};}}"
            f"QToolButton:hover {{background:{lettering.hover.css};}}"
            f"QToolButton:pressed {{background:{lettering.press.css};}}"
            f"QToolButton:focus {{border:1px solid {lettering.ink.css};}}"
        )


class HorizontalScroll(QtWidgets.QScrollArea):
    """Qt owns overflow; vertical wheel input moves the horizontal icon strip, and a horizontal swipe goes on to the bar."""

    @override
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        delta = event.angleDelta()
        if delta.x() or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            event.ignore()
            return
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.y())
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
        self.buttons: tuple[IconButton | PageButton, ...] = ()
        self.appearance: Look | None = None
        self.hide()

    def reset(self) -> None:
        for button in self.buttons:
            self.row.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.buttons = ()

    def finish(self, buttons: tuple[IconButton | PageButton, ...]) -> None:
        self.buttons = buttons
        for button in buttons:
            self.row.addWidget(button)
            if self.appearance is not None:
                button.apply_look(self.appearance.lettering)
        self.body.setFixedSize(max(12, sum(button.width() + 2 for button in buttons) + 10), 32)

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


def windows_label(count: int) -> str:
    return f"{count} window" if count == 1 else f"{count} windows"


class ShellSections:
    """The surface keeps native buttons only for the current immutable snapshot."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        self.pinned = Section(parent)
        self.pager = Section(parent)
        self.apps = Section(parent)
        self.app_snapshot: tuple[Shelf, int] | None = None
        self.pager_view: PagerView | None = None

    def sections(self) -> tuple[Section, Section, Section]:
        return self.pinned, self.pager, self.apps

    def desktops(self, view: PagerView, invoke: Callable[[Navigation], None]) -> None:
        """Previous, each desktop, then next; a pager of one desktop stays hidden."""
        if view == self.pager_view:
            return
        section = self.pager
        hints = view.hints
        if len(view.desktops) <= 1:
            # Targets built here and left out of the section would show once it does, stacked at its origin.
            section.reset()
            section.finish(())
            self.pager_view = view
            return

        def button(page: Page, choose: Callable[[], None]) -> PageButton:
            created = PageButton(section.body, choose)
            created.display(page)
            return created

        def jump(index: int) -> Callable[[], None]:
            return lambda: invoke(PagerClick(index, Source.PAGER))

        previous = button(Page("Previous desktop", hints.previous or Glyph("chevron-left")), lambda: invoke(StepDesktop(-1, Source.PAGER)))
        following = button(Page("Next desktop", hints.next or Glyph("chevron")), lambda: invoke(StepDesktop(1, Source.PAGER)))
        pages = tuple(
            button(
                Page(desktop.name, (hints.desktops[index] if index < len(hints.desktops) else None) or desktop.label, active=desktop.current),
                jump(index),
            )
            for index, desktop in enumerate(view.desktops)
        )
        section.reset()
        section.finish((previous, *pages, following))
        self.pager_view = view

    def applications(self, snapshot: tuple[Shelf, int], invoke: Callable[[Item, Click], None]) -> None:
        if snapshot == self.app_snapshot:
            return
        current, foreground = snapshot

        def button(section: Section, item: Item) -> IconButton:
            created = IconButton(section.body, lambda click: invoke(item, click))
            active = any(window.handle == foreground for window in item.windows)
            match item:
                case Pinned(app=app, windows=()):
                    web = WEB_APPS[app]
                    created.display(f"{web.label} · Open {web.label} on the web", web.glyph, active=active)
                case Pinned(app=app, windows=windows):
                    # The filled symbol marks a running slot, as active states fill elsewhere.
                    web = WEB_APPS[app]
                    created.display(f"{web.label} · {windows_label(len(windows))}", web.glyph + ".fill", active=active)
                case Application(identity=identity, windows=windows, image=image):
                    face = "window" if image is None else image
                    created.display(f"{identity.removesuffix('.exe')} · {windows_label(len(windows))}", face, active=active)
                case _:
                    assert_never(item)
            return created

        for section, items in ((self.pinned, current.pinned), (self.apps, current.running)):
            section.reset()
            section.finish(tuple(button(section, item) for item in items))
        self.app_snapshot = snapshot

    def place(self, left: int, width: int, *, start: int = 12) -> None:
        """Pinned slots follow Canvas from `start`, then the pager and running apps, stopping before the leftmost capsule at `left`."""
        self.pinned.place(start, left - 12)
        after = start if self.pinned.isHidden() else start + self.pinned.width() + 6
        self.pager.place(after, left - 12)
        after = after if self.pager.isHidden() else after + self.pager.width() + 6
        self.apps.place(after, max(after, min(left - 12, width // 3)))
