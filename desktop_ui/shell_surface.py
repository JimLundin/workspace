"""The desktop bar's compact sections: the pinned slots, the desktop pager and the scrollable running applications.

Each target is a round control the bar paints itself, as the island's own
controls are, so no stylesheet can pad, re-font or restyle it.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Final, assert_never, override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from cell import Cell
from desktop_ui import ui_spec
from desktop_ui.bar_control import KeyboardFocus
from desktop_ui.components.appearance import Look
from desktop_ui.components.text import color, inter, outline, paint_capsule
from desktop_ui.desktop_pager import PagerDesktop, PagerView
from desktop_ui.island_layout import on_pixels
from desktop_ui.navigation import Navigation, PagerClick, Source
from desktop_ui.shell_items import WEB_APPS, PinnedApp, Shelf
from desktop_ui.vector_icons import icon
from desktop_ui.window_layout import App, Program
from winapi.icon_pixels import Pixels
from winapi.tray_host import Click


def face_inset(capsule: ui_spec.Capsule) -> int:
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
    """One accessible target: a control's circle, or a pill for text wider than one, painting its face at icon size."""

    def __init__(self, section: Section, target: Target) -> None:
        super().__init__(section.body)
        self.section = section
        self.target = target
        self.picture: QtGui.QPixmap | None = None
        self.pictures: tuple[QtGui.QPixmap | None, ...] = ()
        capsule = section.sizes.capsule
        control = round(capsule.control)
        width = control
        match target.face:
            case Glyph():
                pass
            case Pixels() as image:
                self.picture = pixmap(image)
            case Stack(icons=icons):
                self.pictures = tuple(pixmap(each) if isinstance(each, Pixels) else None for each in icons)
                width = control + STACK_STEP * (len(icons) - 1)
            case str() as text:
                width = max(
                    control,
                    math.ceil(QtGui.QFontMetricsF(inter(12, QtGui.QFont.Weight.Medium, tabular=True)).horizontalAdvance(text))
                    + 2 * face_inset(capsule),
                )
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

    def paint_glyph(self, painter: QtGui.QPainter, name: str, face: QtCore.QRectF) -> None:
        appearance = self.section.appearance
        if appearance is None:
            return
        ink = appearance.lettering.ink
        painter.setOpacity(ink.opacity)
        side = round(self.section.sizes.capsule.icon)
        symbol = icon(name, ink.color).pixmap(QtCore.QSize(side, side), self.devicePixelRatioF())
        painter.drawPixmap(face, symbol, QtCore.QRectF(symbol.rect()))

    def snapped(self) -> QtCore.QPointF:
        """The face's corner on whole device pixels of the window, so a bitmap or symbol keeps its pixel edges."""
        capsule = self.section.sizes.capsule
        scale = self.devicePixelRatioF()
        origin = QtCore.QPointF(self.mapTo(self.window(), QtCore.QPoint(0, 0)))
        corner = origin + QtCore.QPointF((self.width() - capsule.icon) / 2, face_inset(capsule))
        return QtCore.QPointF(on_pixels(corner.x(), scale), on_pixels(corner.y(), scale)) - origin

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
        side = self.section.sizes.capsule.icon
        face = QtCore.QRectF(self.snapped(), QtCore.QSizeF(side, side))
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
                painter.setFont(inter(12, QtGui.QFont.Weight.Medium, tabular=True))
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
    """A capsule of round controls, concentric at its ends and one part gap apart.

    Overflow stays reachable by scrolling horizontally; no icons are silently dropped.
    """

    def __init__(self, parent: QtWidgets.QWidget, sizes: ui_spec.Sizes) -> None:
        super().__init__(parent)
        self.sizes = sizes
        self.targets: tuple[Target, ...] = ()
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
        self.targets = tuple(targets)
        self.buttons = tuple(ShellButton(self, target) for target in self.targets)
        capsule = self.sizes.capsule
        gap = round(capsule.part_gap)
        x = 0
        for button in self.buttons:
            button.move(x, round(capsule.inset))
            button.show()
            x += button.width() + gap
        self.body.setFixedSize(max(0, x - gap), round(capsule.height))

    def use(self, sizes: ui_spec.Sizes) -> None:
        """Rebuild the controls at new sizes; the next `place` positions the capsule."""
        if sizes != self.sizes:
            self.sizes = sizes
            self.show_targets(self.targets)

    def apply_look(self, appearance: Look) -> None:
        if appearance == self.appearance:
            return
        self.appearance = appearance
        for button in self.buttons:
            button.update()
        self.update()

    def place(self, left: int, right: int) -> None:
        top, height, inset = round(self.sizes.bar.top), round(self.sizes.capsule.height), round(self.sizes.capsule.inset)
        self.setGeometry(left, top, max(0, min(right - left, self.body.width() + 2 * inset)), height)
        self.overflow.setGeometry(inset, 0, max(0, self.width() - 2 * inset), height)
        self.setVisible(bool(self.buttons) and right - left >= height)

    @override
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        if self.appearance is not None:
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            paint_capsule(painter, outline(QtCore.QRectF(self.rect()), self.height() / 2), self.appearance)


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
class _Shelved:
    app_snapshot: tuple[Shelf, int] | None = None
    pager_view: tuple[PagerView, Mapping[str, Pixels | None]] | None = None
    icons: frozendict[str, Pixels] = frozendict()
    """Each program's icon as last read, so an app that isn't running keeps its own face."""


@dataclass(frozen=True, slots=True)
class ShellSections:
    """The surface keeps native buttons only for the current immutable snapshot.

    The pager is the bar's only toolbar: every desktop with its apps, each app a click target.
    """

    pager: Section
    _state: Cell[_Shelved] = field(default_factory=lambda: Cell(_Shelved()), init=False, repr=False)

    @classmethod
    def build(cls, parent: QtWidgets.QWidget, sizes: ui_spec.Sizes) -> ShellSections:
        return cls(Section(parent, sizes))

    def desktops(self, view: PagerView, invoke: Callable[[Navigation], None], on_app: Callable[[App, Click], None]) -> bool:
        """Each desktop with its apps, a click on an app going to it (and so to its desktop); whether the pager changed.

        An empty desktop other than the current one is left out. Programs' icons come from
        the running apps, so a newly read icon redraws the pager too.
        """
        images: Mapping[str, Pixels | None] = self._state.get().icons
        if (view, images) == self._state.get().pager_view:
            return False
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
        self._state.set(replace(self._state.get(), pager_view=(view, images)))
        return True

    def applications(self, snapshot: tuple[Shelf, int]) -> bool:
        """Remember the running apps' windows and icons, which the pager draws; whether they changed."""
        if snapshot == self._state.get().app_snapshot:
            return False
        shelved = self._state.get()
        read = frozendict((app.identity, app.image) for app in snapshot[0].running if app.image is not None)
        self._state.set(replace(shelved, app_snapshot=snapshot, icons=shelved.icons | read))
        return True

    def place(self, left: int, width: int) -> None:
        """The pager from the screen's edge, stopping before the leftmost capsule at `left`."""
        self.pager.place(12, left - 12)
