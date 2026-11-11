"""The desktop bar's pager: every desktop with its applications, each a round control in a scrollable capsule.

Each target is a round control the bar paints itself, as the island's own
controls are, so no stylesheet can pad, re-font or restyle it.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import accumulate
from typing import assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from cell import Cell
from desktop_ui.bar_control import KeyboardFocus, paint_feedback
from desktop_ui.components.appearance import Lettering, Look
from desktop_ui.components.text import color, inter, outline, paint_capsule
from desktop_ui.desktop_pager import PagerDesktop, PagerView
from desktop_ui.island_layout import Capsule, Sizes, on_pixels
from desktop_ui.navigation import JumpDesktop, Navigation
from desktop_ui.shell_items import PinnedApp, Shelf
from desktop_ui.vector_icons import paint_icon
from desktop_ui.window_layout import App, Program
from winapi.icon_pixels import Pixels
from winapi.tray_host import Click


def face_inset(capsule: Capsule) -> int:
    """An app icon's inset inside its circle; text keeps the same inset, so a wide keycap widens its control into a pill."""
    return round(capsule.control - capsule.app_icon) // 2


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
    """Several icons side by side, an app gap apart: a desktop's applications."""

    icons: tuple[Icon, ...]


def step(capsule: Capsule) -> float:
    """From one of a desktop's icons to the next."""
    return capsule.app_icon + capsule.app_gap


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
        capsule = pager.sizes.capsule
        control = round(capsule.control)
        match target.face:
            case Stack(icons=icons):
                self.pictures = tuple(pixmap(each) if isinstance(each, Pixels) else None for each in icons)
                width = control + round(step(capsule) * (len(icons) - 1))
            case str() as text:
                advance = QtGui.QFontMetricsF(inter(pager.sizes.type.reading)).horizontalAdvance(text)
                width = max(control, math.ceil(advance) + 2 * face_inset(capsule))
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
        self.hovered = 0
        """The stacked icon under the pointer, which alone lights."""
        self.setMouseTracking(True)
        self.clicked.connect(lambda: self.choose(Click.LEFT))

    def icon_at(self, x: float) -> int:
        """The desktop's icon under `x`: the one whose centre is nearest, so the gap between two splits evenly."""
        match self.target.face:
            case Stack(icons=icons) if icons:
                pitch = step(self.pager.sizes.capsule)
                first = (self.width() - pitch * (len(icons) - 1)) / 2
                return max(0, min(len(icons) - 1, round((x - first) / pitch)))
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
    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if (index := self.icon_at(event.position().x())) != self.hovered:
            self.hovered = index
            self.update()
        super().mouseMoveEvent(event)

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

    def paint_lit(self, painter: QtGui.QPainter, lettering: Lettering) -> None:
        """Press and hover light only the app under the pointer in a desktop of several; the keyboard ring holds the whole desktop."""
        whole = QtCore.QRectF(self.rect())
        match self.target.face:
            case Stack(icons=icons) if len(icons) > 1 and self.underMouse():
                pitch, radius = step(self.pager.sizes.capsule), self.height() / 2
                centre = (self.width() - pitch * (len(icons) - 1)) / 2 + pitch * self.hovered
                circle = QtCore.QRectF(centre - radius, 0, 2 * radius, self.height())
                paint_feedback(painter, lettering, circle, radius, pressed=self.isDown(), hovered=True)
                paint_feedback(painter, lettering, whole, radius, pressed=False, hovered=False, ringed=self.focus_ringed)
            case _:
                paint_feedback(
                    painter, lettering, whole, self.height() / 2, pressed=self.isDown(), hovered=self.underMouse(), ringed=self.focus_ringed
                )

    def snapped(self) -> QtCore.QPointF:
        """The face's corner on whole device pixels of the window, so a bitmap or symbol keeps its pixel edges."""
        capsule = self.pager.sizes.capsule
        scale = self.devicePixelRatioF()
        origin = QtCore.QPointF(self.mapTo(self.window(), QtCore.QPoint(0, 0)))
        corner = origin + QtCore.QPointF((self.width() - capsule.app_icon) / 2, face_inset(capsule))
        return QtCore.QPointF(on_pixels(corner.x(), scale), on_pixels(corner.y(), scale)) - origin

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        appearance = self.pager.appearance
        if appearance is None:
            return
        lettering = appearance.lettering
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        capsule = self.pager.sizes.capsule
        self.paint_lit(painter, lettering)
        side = capsule.app_icon
        face = QtCore.QRectF(self.snapped(), QtCore.QSizeF(side, side))
        if self.target.active:
            # The current desktop: a dot under its apps, as a dock marks a running app.
            below = QtCore.QPointF(self.width() / 2, self.height() - face_inset(capsule) / 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color(lettering.ink))
            painter.drawEllipse(below, capsule.current_dot, capsule.current_dot)
        match self.target.face:
            case Stack(icons=icons):
                painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
                pitch = step(self.pager.sizes.capsule)
                first = face.translated(-pitch * (len(icons) - 1) / 2, 0)
                for index, (each, picture) in enumerate(zip(icons, self.pictures, strict=True)):
                    spot = first.translated(round(pitch * index), 0)
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
                painter.setFont(inter(self.pager.sizes.type.reading))
                painter.setPen(color(lettering.ink))
                painter.drawText(QtCore.QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, text)
            case _:
                assert_never(self.target.face)


@dataclass(frozen=True, slots=True)
class Row:
    """The pager's controls along its strip."""

    lefts: tuple[int, ...]
    width: int


def spaced_row(widths: Sequence[int], capsule: Capsule) -> Row:
    """Controls of `widths` left to right, a slot gap apart: with each control's own inset, desktops
    sit well apart from each other while a desktop's apps keep their small app gap, so space alone groups them.
    """
    gap = round(capsule.slot_gap)
    lefts = tuple(accumulate((width + gap for width in widths[:-1]), initial=0))[: len(widths)]
    ends = tuple(left + width for left, width in zip(lefts, widths, strict=True))
    return Row(lefts, ends[-1] if ends else 0)


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


def app_icon(app: App, images: Mapping[str, Pixels | None], symbols: Mapping[PinnedApp, str]) -> Icon:
    """The icon the bar shows an app by: a web app's symbol, else the program's own icon."""
    match app:
        case PinnedApp():
            return Glyph(symbols[app] + ".fill")
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

    def __init__(self, parent: QtWidgets.QWidget, sizes: Sizes) -> None:
        super().__init__(parent)
        self.sizes = sizes
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.overflow = HorizontalScroll(self)
        self.appearance: Look | None = None
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
        self.paged = Cell(_Paged())
        self.hide()

    def show_targets(self, targets: tuple[Target, ...]) -> None:
        """Replace the controls; only the pager builds them, so none outlives its snapshot."""
        for button in self.buttons:
            button.hide()
            button.deleteLater()
        self.buttons = tuple(ShellButton(self, target) for target in targets)
        capsule = self.sizes.capsule
        row = spaced_row(tuple(button.width() for button in self.buttons), capsule)
        for button, x in zip(self.buttons, row.lefts, strict=True):
            button.move(x, round(capsule.inset))
            button.show()
        self.body.setFixedSize(row.width, round(capsule.height))

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
            return Stack(tuple(app_icon(app, images, view.symbols) for app in desktop.apps)) if desktop.apps else desktop.label

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
        sizes = self.sizes
        top, height, inset = round(sizes.bar.top), round(sizes.capsule.height), round(sizes.capsule.inset)
        self.setGeometry(left, top, max(0, min(right - left, self.body.width() + 2 * inset)), height)
        self.overflow.setGeometry(inset, 0, max(0, self.width() - 2 * inset), height)
        self.setVisible(bool(self.buttons) and right - left >= height)

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        if self.appearance is not None:
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            paint_capsule(painter, outline(QtCore.QRectF(self.rect()), self.height() / 2), self.appearance)
