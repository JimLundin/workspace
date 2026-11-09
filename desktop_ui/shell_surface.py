"""The desktop bar's pager: every desktop with its applications, each a round control in a scrollable capsule.

Each target is a round control the bar paints itself, as the island's own
controls are, so no stylesheet can pad, re-font or restyle it.
"""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from cell import Cell
from desktop_ui.bar_control import KeyboardFocus, font
from desktop_ui.components.appearance import Look
from desktop_ui.components.text import color, outline, paint_capsule
from desktop_ui.desktop_pager import PagerDesktop, PagerView
from desktop_ui.island_layout import SIZES, Capsule, on_pixels
from desktop_ui.navigation import JumpDesktop, Navigation
from desktop_ui.shell_items import WEB_APPS, PinnedApp, Shelf
from desktop_ui.vector_icons import paint_icon
from desktop_ui.window_layout import App, Program
from winapi.icon_pixels import Pixels
from winapi.tray_host import Click


def face_inset(capsule: Capsule) -> int:
    """A symbol's inset inside its circle; text keeps the same inset, so a wide keycap widens its control into a pill."""
    return round(capsule.control - capsule.icon) // 2


def pixmap(image: Pixels) -> QtGui.QPixmap:
    """A Qt copy of a shell icon's pixels."""
    copied = QtGui.QImage(image.bgra, image.size, image.size, image.size * 4, QtGui.QImage.Format.Format_ARGB32).copy()
    converted = QtGui.QPixmap()
    converted.convertFromImage(copied)
    return converted


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

type Face = Stack | str
"""A stack of icons (a desktop's applications), or text such as a desktop number or keycap."""


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
    """One accessible target: a control's circle, or a pill for text wider than one, painting its face at icon size."""

    def __init__(self, pager: Pager, target: Target) -> None:
        super().__init__(pager.body)
        self.pager = pager
        self.target = target
        self.pictures: tuple[QtGui.QPixmap | None, ...] = ()
        capsule = SIZES.capsule
        control = round(capsule.control)
        match target.face:
            case Stack(icons=icons):
                self.pictures = tuple(pixmap(each) if isinstance(each, Pixels) else None for each in icons)
                width = control + STACK_STEP * (len(icons) - 1)
            case str() as text:
                width = max(control, math.ceil(QtGui.QFontMetricsF(font(strong=False)).horizontalAdvance(text)) + 2 * face_inset(capsule))
            case _:
                assert_never(target.face)
        self.setFixedSize(width, control)
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
        self._choose_on(event, Qt.MouseButton.RightButton, Click.RIGHT, super().mouseReleaseEvent)

    @override
    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        self._choose_on(event, Qt.MouseButton.LeftButton, Click.DOUBLE, super().mouseDoubleClickEvent)

    def _choose_on(self, event: QtGui.QMouseEvent, button: Qt.MouseButton, click: Click, otherwise: Callable[[QtGui.QMouseEvent], None]) -> None:
        """Choose `click` for `button`; Qt handles any other button."""
        if event.button() is button:
            self.choose(click)
            event.accept()
        else:
            otherwise(event)

    def snapped(self) -> QtCore.QPointF:
        """The face's corner on whole device pixels of the window, so a bitmap or symbol keeps its pixel edges."""
        capsule = SIZES.capsule
        scale = self.devicePixelRatioF()
        origin = QtCore.QPointF(self.mapTo(self.window(), QtCore.QPoint(0, 0)))
        corner = origin + QtCore.QPointF((self.width() - capsule.icon) / 2, face_inset(capsule))
        return QtCore.QPointF(on_pixels(corner.x(), scale), on_pixels(corner.y(), scale)) - origin

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        appearance = self.pager.appearance
        if appearance is None:
            return
        lettering = appearance.lettering
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.paint_round(painter, lettering, selected=self.target.active)
        side = SIZES.capsule.icon
        face = QtCore.QRectF(self.snapped(), QtCore.QSizeF(side, side))
        match self.target.face:
            case Stack(icons=icons):
                painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
                first = face.translated(-STACK_STEP * (len(icons) - 1) / 2, 0)
                # Later icons draw over earlier ones, so the row reads left to right.
                for index, (each, picture) in enumerate(zip(icons, self.pictures, strict=True)):
                    spot = first.translated(STACK_STEP * index, 0)
                    match each:
                        case Glyph(name=name):
                            paint_icon(painter, name, lettering.ink, spot)
                        case Pixels():
                            if picture is not None:
                                painter.setOpacity(1)
                                painter.drawPixmap(spot, picture, QtCore.QRectF(picture.rect()))
                        case _:
                            assert_never(each)
            case str() as text:
                painter.setFont(font(strong=False))
                painter.setPen(color(lettering.ink))
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
    """The icon the bar shows an app by: a web app's symbol, else the program's own icon."""
    match app:
        case PinnedApp():
            return Glyph(WEB_APPS[app].glyph + ".fill")
        case Program(exe=exe):
            image = images.get(exe)
            return Glyph("window") if image is None else image
        case _:
            assert_never(app)


@dataclass(frozen=True, slots=True)
class _Paged:
    view: tuple[PagerView, Mapping[str, Pixels | None]] | None = None
    """What the controls show now, with the icons they were drawn from."""
    icons: frozendict[str, Pixels] = frozendict()
    """Each program's icon as last read, so an app that isn't running keeps its own face."""


class Pager(QtWidgets.QWidget):
    """The bar's only toolbar: every desktop with its apps, each app a click target, in a capsule of round controls.

    The controls are concentric at the capsule's ends and one part gap apart; overflow stays reachable by
    scrolling horizontally, so no icons are silently dropped. Native buttons exist only for the current snapshot.
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
        self.paged = Cell(_Paged())
        self.hide()

    def show_targets(self, targets: tuple[Target, ...]) -> None:
        """Replace the controls; only the pager builds them, so none outlives its snapshot."""
        for button in self.buttons:
            button.hide()
            button.deleteLater()
        self.buttons = tuple(ShellButton(self, target) for target in targets)
        capsule = SIZES.capsule
        gap = round(capsule.part_gap)
        x = 0
        for button in self.buttons:
            button.move(x, round(capsule.inset))
            button.show()
            x += button.width() + gap
        self.body.setFixedSize(max(0, x - gap), round(capsule.height))

    def remember_icons(self, shelf: Shelf) -> None:
        """The running apps' icons, which the pager draws its programs by."""
        read = frozendict((app.identity, app.image) for app in shelf.running if app.image is not None)
        self.paged.update(lambda paged: _Paged(paged.view, paged.icons | read))

    def desktops(self, view: PagerView, invoke: Callable[[Navigation], None], on_app: Callable[[App, Click], None]) -> bool:
        """Each desktop with its apps, a click on an app going to it (and so to its desktop); whether the pager changed.

        An empty desktop other than the current one is left out. Programs' icons come from
        the running apps, so a newly read icon redraws the pager too.
        """
        images: Mapping[str, Pixels | None] = self.paged.get().icons
        if (view, images) == self.paged.get().view:
            return False
        hints = view.hints

        def jump(index: int) -> Callable[[Click], None]:
            return pager_click(lambda: invoke(JumpDesktop(index)))

        def face(index: int, desktop: PagerDesktop) -> Face:
            """The held chord's letter, else the desktop's apps, else its number."""
            if (hint := hints.desktops[index] if index < len(hints.desktops) else None) is not None:
                return hint
            return Stack(tuple(app_icon(app, images) for app in desktop.apps)) if desktop.apps else desktop.label

        def pick(apps: tuple[App, ...]) -> Callable[[int, Click], None] | None:
            if not apps:
                return None
            return lambda index, click: on_app(apps[index], click)

        pages = tuple(
            Target(desktop.name, face(index, desktop), jump(index), active=desktop.current, pick=pick(desktop.apps))
            for index, desktop in enumerate(view.desktops)
            if desktop.apps or desktop.current
        )
        self.show_targets(pages if len(view.desktops) > 1 else ())
        self.paged.update(lambda paged: _Paged((view, images), paged.icons))
        return True

    def apply_look(self, appearance: Look) -> None:
        if appearance == self.appearance:
            return
        self.appearance = appearance
        for button in self.buttons:
            button.update()
        self.update()

    def place(self, left: int, right: int) -> None:
        top, height, inset = round(SIZES.bar.top), round(SIZES.capsule.height), round(SIZES.capsule.inset)
        self.setGeometry(left, top, max(0, min(right - left, self.body.width() + 2 * inset)), height)
        self.overflow.setGeometry(inset, 0, max(0, self.width() - 2 * inset), height)
        self.setVisible(bool(self.buttons) and right - left >= height)

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        if self.appearance is not None:
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            paint_capsule(painter, outline(QtCore.QRectF(self.rect()), self.height() / 2), self.appearance)
