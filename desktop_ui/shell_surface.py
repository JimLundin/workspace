"""The desktop bar's compact sections: Canvas with the pinned slots, the desktop pager and the scrollable running applications.

Each target is a round control the bar paints itself, as the island's own
controls are, so no stylesheet can pad, re-font or restyle it.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final, assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.bar_control import KeyboardFocus
from desktop_ui.components import typeface
from desktop_ui.components.appearance import GlassLook, Look, SolidLook
from desktop_ui.components.text import color
from desktop_ui.desktop_pager import PagerDesktop, PagerView
from desktop_ui.island_layout import CONTROL, HEIGHT, ICON, PART_GAP
from desktop_ui.navigation import Navigation, PagerClick, Source
from desktop_ui.shell_items import WEB_APPS, PinnedApp, Shelf
from desktop_ui.vector_icons import icon
from desktop_ui.window_layout import App, Program, WorkspaceView
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


type Icon = Glyph | Pixels


@dataclass(frozen=True, slots=True)
class Stack:
    """Several icons overlapping left to right: a desktop's applications."""

    icons: tuple[Icon, ...]


STACK_STEP: Final = 12
"""Pixels between stacked icons' left edges; each 16 px icon overlaps the next by a quarter."""

type Face = Icon | Stack | str
"""A Fluent symbol in the bar's ink, an application's own icon, a stack of them, or text such as a desktop number or keycap."""


@dataclass(frozen=True, slots=True)
class Target:
    """One shell control as shown: its accessible name, its face, what a click does and whether it is the current selection."""

    name: str
    face: Face
    invoke: Callable[[Click], None]
    active: bool = field(default=False, kw_only=True)
    pick: Callable[[int, Click], None] | None = field(default=None, kw_only=True)
    """For a stack: a click on its icon at that index, instead of `invoke`."""


class ShellButton(KeyboardFocus):
    """One accessible target: a 28 px circle, or a pill for text wider than one, painting its face at 16 px."""

    def __init__(self, section: Section, target: Target) -> None:
        super().__init__(section.body)
        self.section = section
        self.target = target
        self.picture: QtGui.QPixmap | None = None
        self.pictures: tuple[QtGui.QPixmap | None, ...] = ()
        width = CONTROL
        match target.face:
            case Glyph():
                pass
            case Pixels() as image:
                self.picture = pixmap(image)
            case Stack(icons=icons):
                self.pictures = tuple(pixmap(each) if isinstance(each, Pixels) else None for each in icons)
                width = CONTROL + STACK_STEP * (len(icons) - 1)
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
        self.pressed_at = 0.0
        """Where the last press landed, which picks a stack's icon."""
        self.clicked.connect(lambda: self.choose(Click.LEFT))

    def icon_at(self, x: float) -> int:
        """The stacked icon under `x`: the one whose centre is nearest, as later icons cover earlier ones' right edges."""
        match self.target.face:
            case Stack(icons=icons) if icons:
                first = (self.width() - STACK_STEP * (len(icons) - 1)) / 2
                return max(0, min(len(icons) - 1, round((x - first) / STACK_STEP)))
            case _:
                return 0

    def choose(self, click: Click) -> None:
        if self.target.pick is not None:
            self.target.pick(self.icon_at(self.pressed_at), click)
        else:
            self.target.invoke(click)

    @override
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self.pressed_at = event.position().x()
        super().mousePressEvent(event)

    @override
    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.RightButton:
            self.choose(Click.RIGHT)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    @override
    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self.choose(Click.DOUBLE)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def paint_glyph(self, painter: QtGui.QPainter, name: str, face: QtCore.QRectF) -> None:
        appearance = self.section.appearance
        if appearance is None:
            return
        ink = appearance.lettering.ink
        painter.setOpacity(ink.opacity)
        symbol = icon(name, ink.color).pixmap(QtCore.QSize(ICON, ICON), self.devicePixelRatioF())
        painter.drawPixmap(face, symbol, QtCore.QRectF(symbol.rect()))

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
                self.paint_glyph(painter, name, face)
            case Pixels():
                if self.picture is not None:
                    painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
                    painter.drawPixmap(face, self.picture, QtCore.QRectF(self.picture.rect()))
            case Stack(icons=icons):
                painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
                first = face.translated(-STACK_STEP * (len(icons) - 1) / 2, 0)
                # Later icons draw over earlier ones, so the row reads left to right.
                for index, (each, picture) in enumerate(zip(icons, self.pictures, strict=True)):
                    spot = first.translated(STACK_STEP * index, 0)
                    match each:
                        case Glyph(name=name):
                            self.paint_glyph(painter, name, spot)
                        case Pixels():
                            if picture is not None:
                                painter.setOpacity(1)
                                painter.drawPixmap(spot, picture, QtCore.QRectF(picture.rect()))
                        case _:
                            assert_never(each)
            case str() as text:
                painter.setFont(page_font())
                painter.setPen(color(ink))
                painter.drawText(QtCore.QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, text)
            case _:
                assert_never(self.target.face)


class HorizontalScroll(QtWidgets.QScrollArea):
    """Qt owns overflow; vertical wheel input moves the horizontal icon strip, as horizontal input does natively."""

    @override
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        delta = event.angleDelta()
        if delta.x() or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            super().wheelEvent(event)
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


def app_icon(app: App, images: Mapping[str, Pixels | None]) -> Icon:
    """The icon the bar shows an app by: a web app's or the canvas's symbol, else the program's own icon."""
    match app:
        case PinnedApp():
            return Glyph(WEB_APPS[app].glyph + ".fill")
        case WorkspaceView.CANVAS:
            return Glyph("canvas")
        case Program(exe=exe):
            image = images.get(exe)
            return Glyph("window") if image is None else image
        case _:
            assert_never(app)


class ShellSections:
    """The surface keeps native buttons only for the current immutable snapshot.

    The pager is the bar's only toolbar: every desktop with its apps, each app a click target.
    """

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        self.pager = Section(parent)
        self.app_snapshot: tuple[Shelf, int] | None = None
        self.pager_view: tuple[PagerView, Mapping[str, Pixels | None]] | None = None
        self.icons: dict[str, Pixels] = {}
        """Each program's icon as last read, so an app that isn't running keeps its own face."""

    def sections(self) -> tuple[Section]:
        return (self.pager,)

    def desktops(self, view: PagerView, invoke: Callable[[Navigation], None], on_app: Callable[[App, Click], None]) -> None:
        """Each desktop with its apps; a click on an app goes to it (and so to its desktop).

        An empty desktop other than the current one is left out. Programs' icons come from
        the running apps, so a newly read icon redraws the pager too.
        """
        images: Mapping[str, Pixels | None] = frozendict(self.icons)
        if (view, images) == self.pager_view:
            return
        hints = view.hints

        def jump(index: int) -> Callable[[Click], None]:
            return pager_click(lambda: invoke(PagerClick(index, Source.PAGER)))

        def face(index: int, desktop: PagerDesktop) -> Face:
            """The held chord's letter, else the desktop's apps, else its number."""
            if (hint := hints.desktops[index] if index < len(hints.desktops) else None) is not None:
                return hint
            return Stack(tuple(app_icon(app, images) for app in desktop.apps)) if desktop.apps else desktop.label

        def pick(apps: tuple[App, ...]) -> Callable[[int, Click], None] | None:
            if not apps:
                return None
            return lambda index, click: on_app(apps[index], click)

        def pages() -> tuple[Target, ...]:
            return tuple(
                Target(desktop.name, face(index, desktop), jump(index), active=desktop.current, pick=pick(desktop.apps))
                for index, desktop in enumerate(view.desktops)
                if desktop.apps or desktop.current
            )

        self.pager.show_targets(pages() if len(view.desktops) > 1 else ())
        self.pager_view = (view, images)

    def applications(self, snapshot: tuple[Shelf, int]) -> None:
        """Remember the running apps' windows and icons; the pager draws them."""
        if snapshot == self.app_snapshot:
            return
        self.icons.update((app.identity, app.image) for app in snapshot[0].running if app.image is not None)
        self.app_snapshot = snapshot

    def place(self, left: int, width: int) -> None:
        """The pager from the screen's edge, stopping before the leftmost capsule at `left`."""
        self.pager.place(12, left - 12)
