"""The desktop bar's compact sections: Canvas with the pinned slots, the desktop pager and the scrollable running applications.

Each target is a round control the bar paints itself, as the island's own
controls are, so no stylesheet can pad, re-font or restyle it.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final, assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.bar_control import KeyboardFocus
from desktop_ui.components import typeface
from desktop_ui.components.appearance import GlassLook, Look, SolidLook
from desktop_ui.components.text import color
from desktop_ui.desktop_pager import PagerView
from desktop_ui.island_layout import CONTROL, HEIGHT, ICON, PART_GAP
from desktop_ui.navigation import Navigation, PagerClick, Source, StepDesktop
from desktop_ui.shell_items import WEB_APPS, Application, Item, Pinned, Shelf
from desktop_ui.vector_icons import icon
from winapi.icon_pixels import Pixels
from winapi.tray_host import Click

INSET: Final = (HEIGHT - CONTROL) // 2
"""Each end control sits concentric, this far inside its capsule."""
FACE_INSET: Final = (CONTROL - ICON) // 2
"""A symbol's inset inside its circle; text keeps the same inset, so a wide keycap widens its control into a pill."""


def pixmap(image: Pixels) -> QtGui.QPixmap:
    """A Qt copy of a shell icon's pixels."""
    copied = QtGui.QImage(image.bgra, image.size, image.size, image.size * 4, QtGui.QImage.Format.Format_ARGB32).copy()
    converted = QtGui.QPixmap()
    converted.convertFromImage(copied)
    return converted


@lru_cache(maxsize=1)
def page_font() -> QtGui.QFont:
    value = QtGui.QFont(typeface.FAMILY)
    value.setPixelSize(12)
    value.setWeight(QtGui.QFont.Weight.Medium)
    value.setFeature(QtGui.QFont.Tag("tnum"), 1)
    return value


@dataclass(frozen=True, slots=True)
class Glyph:
    name: str


type Face = Glyph | Pixels | str
"""A Fluent symbol in the bar's ink, an application's own icon, or text such as a desktop number or keycap."""


@dataclass(frozen=True, slots=True)
class Target:
    """One shell control as shown: its accessible name, its face, what a click does and whether it is the current selection."""

    name: str
    face: Face
    invoke: Callable[[Click], None]
    active: bool = field(default=False, kw_only=True)


class ShellButton(KeyboardFocus):
    """One accessible target: a 28 px circle, or a pill for text wider than one, painting its face at 16 px."""

    def __init__(self, section: Section, target: Target) -> None:
        super().__init__(section.body)
        self.section = section
        self.target = target
        self.picture: QtGui.QPixmap | None = None
        width = CONTROL
        match target.face:
            case Glyph():
                pass
            case Pixels() as image:
                self.picture = pixmap(image)
            case str() as text:
                width = max(CONTROL, math.ceil(QtGui.QFontMetricsF(page_font()).horizontalAdvance(text)) + 2 * FACE_INSET)
            case _:
                assert_never(target.face)
        self.setFixedSize(width, CONTROL)
        self.setToolTip(target.name)
        self.setAccessibleName(target.name)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)  # Qt repaints it as the pointer enters and leaves.
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(lambda: self.target.invoke(Click.LEFT))

    @override
    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.RightButton:
            self.target.invoke(Click.RIGHT)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    @override
    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self.target.invoke(Click.DOUBLE)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def snapped(self) -> QtCore.QPointF:
        """The 16 px face's corner on whole device pixels of the window, so a bitmap or symbol keeps its pixel edges."""
        scale = self.devicePixelRatioF()
        origin = QtCore.QPointF(self.mapTo(self.window(), QtCore.QPoint(0, 0)))
        corner = origin + QtCore.QPointF((self.width() - ICON) / 2, FACE_INSET)
        return QtCore.QPointF(round(corner.x() * scale) / scale, round(corner.y() * scale) / scale) - origin

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        appearance = self.section.appearance
        if appearance is None:
            return
        lettering = appearance.lettering
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.paint_feedback(painter, lettering, selected=self.target.active)
        ink = lettering.ink
        face = QtCore.QRectF(self.snapped(), QtCore.QSizeF(ICON, ICON))
        match self.target.face:
            case Glyph(name=name):
                painter.setOpacity(ink.opacity)
                symbol = icon(name, ink.color).pixmap(QtCore.QSize(ICON, ICON), self.devicePixelRatioF())
                painter.drawPixmap(face, symbol, QtCore.QRectF(symbol.rect()))
            case Pixels():
                if self.picture is not None:
                    painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
                    painter.drawPixmap(face, self.picture, QtCore.QRectF(self.picture.rect()))
            case str() as text:
                painter.setFont(page_font())
                painter.setPen(color(ink))
                painter.drawText(QtCore.QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, text)
            case _:
                assert_never(self.target.face)


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
    """A 34 px capsule of round controls, 3 px inside its ends and one part gap apart.

    Overflow stays reachable by scrolling horizontally; no icons are silently dropped.
    """

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.overflow = HorizontalScroll(self)
        self.body = QtWidgets.QWidget()
        self.overflow.setWidget(self.body)
        self.overflow.setWidgetResizable(False)
        self.overflow.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.overflow.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.overflow.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for widget in (self.overflow, self.overflow.viewport(), self.body):
            widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            widget.setAutoFillBackground(False)
        self.buttons: tuple[ShellButton, ...] = ()
        self.appearance: Look | None = None
        self.hide()

    def show_targets(self, targets: Sequence[Target]) -> None:
        """Replace the controls; only this section builds them, so none outlives its snapshot."""
        for button in self.buttons:
            button.hide()
            button.deleteLater()
        self.buttons = tuple(ShellButton(self, target) for target in targets)
        x = 0
        for button in self.buttons:
            button.move(x, INSET)
            button.show()
            x += button.width() + PART_GAP
        self.body.setFixedSize(max(0, x - PART_GAP), HEIGHT)

    def apply_look(self, appearance: Look) -> None:
        if appearance == self.appearance:
            return
        self.appearance = appearance
        for button in self.buttons:
            button.update()
        self.update()

    def place(self, left: int, right: int) -> None:
        self.setGeometry(left, 8, max(0, min(right - left, self.body.width() + 2 * INSET)), HEIGHT)
        self.overflow.setGeometry(INSET, 0, max(0, self.width() - 2 * INSET), HEIGHT)
        self.setVisible(bool(self.buttons) and right - left >= HEIGHT)

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        outline = QtGui.QPainterPath()
        outline.addRoundedRect(QtCore.QRectF(self.rect()), HEIGHT / 2, HEIGHT / 2)
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


def pager_click(choose: Callable[[], None]) -> Callable[[Click], None]:
    """A pager target acts on a left click or each click of a double-click; it has no menu."""

    def invoke(click: Click) -> None:
        match click:
            case Click.LEFT | Click.DOUBLE:
                choose()
            case Click.RIGHT:
                pass
            case _:
                assert_never(click)

    return invoke


def canvas_target(open_canvas: Callable[[], None]) -> Target:
    """Canvas opens on a left click; it has no menu, and a double-click's second press doesn't open it again."""

    def invoke(click: Click) -> None:
        match click:
            case Click.LEFT:
                open_canvas()
            case Click.RIGHT | Click.DOUBLE:
                pass
            case _:
                assert_never(click)

    return Target("Canvas · Open your work canvas", Glyph("canvas"), invoke)


class ShellSections:
    """The surface keeps native buttons only for the current immutable snapshot.

    Canvas leads the pinned web-app slots in one capsule; it shows even before the shell reports applications.
    """

    def __init__(self, parent: QtWidgets.QWidget, open_canvas: Callable[[], None]) -> None:
        self.canvas = canvas_target(open_canvas)
        self.pinned = Section(parent)
        self.pinned.show_targets((self.canvas,))
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
        hints = view.hints

        def jump(index: int) -> Callable[[Click], None]:
            return pager_click(lambda: invoke(PagerClick(index, Source.PAGER)))

        def pages() -> tuple[Target, ...]:
            return (
                Target("Previous desktop", hints.previous or Glyph("chevron-left"), pager_click(lambda: invoke(StepDesktop(-1, Source.PAGER)))),
                *(
                    Target(
                        desktop.name,
                        (hints.desktops[index] if index < len(hints.desktops) else None) or desktop.label,
                        jump(index),
                        active=desktop.current,
                    )
                    for index, desktop in enumerate(view.desktops)
                ),
                Target("Next desktop", hints.next or Glyph("chevron"), pager_click(lambda: invoke(StepDesktop(1, Source.PAGER)))),
            )

        self.pager.show_targets(pages() if len(view.desktops) > 1 else ())
        self.pager_view = view

    def applications(self, snapshot: tuple[Shelf, int], invoke: Callable[[Item, Click], None]) -> None:
        if snapshot == self.app_snapshot:
            return
        current, foreground = snapshot

        def target(item: Item) -> Target:
            active = any(window.handle == foreground for window in item.windows)

            def chosen(click: Click) -> None:
                invoke(item, click)

            match item:
                case Pinned(app=app, windows=()):
                    web = WEB_APPS[app]
                    return Target(f"{web.label} · Open {web.label} on the web", Glyph(web.glyph), chosen, active=active)
                case Pinned(app=app, windows=windows):
                    # The filled symbol marks a running slot, as active states fill elsewhere.
                    web = WEB_APPS[app]
                    return Target(f"{web.label} · {windows_label(len(windows))}", Glyph(web.glyph + ".fill"), chosen, active=active)
                case Application(identity=identity, windows=windows, image=image):
                    face = Glyph("window") if image is None else image
                    return Target(f"{identity.removesuffix('.exe')} · {windows_label(len(windows))}", face, chosen, active=active)
                case _:
                    assert_never(item)

        self.pinned.show_targets((self.canvas, *(target(item) for item in current.pinned)))
        self.apps.show_targets(tuple(target(item) for item in current.running))
        self.app_snapshot = snapshot

    def place(self, left: int, width: int) -> None:
        """Canvas and the pinned slots from the screen's edge, then the pager and running apps, stopping before the leftmost capsule at `left`."""
        self.pinned.place(12, left - 12)
        after = 12 if self.pinned.isHidden() else 12 + self.pinned.width() + 6
        self.pager.place(after, left - 12)
        after = after if self.pager.isHidden() else after + self.pager.width() + 6
        self.apps.place(after, max(after, min(left - 12, width // 3)))
