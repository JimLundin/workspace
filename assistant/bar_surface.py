"""Small toolbar capsules using the conversation messages' native glass and ink."""

from collections.abc import Callable
from typing import assert_never

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.agent_window import log_view
from assistant.bar_geometry import SHOULDER, Segment, segment
from assistant.control_feedback import paint_feedback
from assistant.notifications import REVEAL_SECONDS, Tone, ease_out
from assistant.qt_runtime import prepare
from assistant.qt_ui import EventLoop
from assistant.toast_style import Ink, Palette, palette
from assistant.vector_icons import icon
from winapi import appearance, windows
from winapi.composition import Glass, borderless
from winapi.contours import Contour, Curve, End, Line, Move
from winapi.shapes import Rect

prepare()

BAR_HEIGHT = 28
CONTROL_HEIGHT = 24


class Control(QtWidgets.QToolButton):
    """Toolbar icons use square targets; captions earn their measured width."""

    def __init__(self, parent: Pill) -> None:
        super().__init__(parent)
        self.surface: Pill = parent
        self.setFixedHeight(CONTROL_HEIGHT)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)

    def setText(self, text: str) -> None:  # noqa: N802 -- Qt native interface
        super().setText(text)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if text else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.updateGeometry()

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802 -- Qt native interface
        if not self.text():
            return QtCore.QSize(CONTROL_HEIGHT, CONTROL_HEIGHT)
        # Own the compact icon/caption spacing instead of inheriting platform
        # button margins that leave a wide blank hover region after the count.
        return QtCore.QSize(CONTROL_HEIGHT + 4 + self.fontMetrics().horizontalAdvance(self.text()), CONTROL_HEIGHT)

    def minimumSizeHint(self) -> QtCore.QSize:  # noqa: N802 -- Qt native interface
        return self.sizeHint()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 -- Qt native interface
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        paint_feedback(self, painter, self.surface.ink.foreground)
        painter.setOpacity(1 if self.isEnabled() else .45)
        size = self.iconSize()
        left = (CONTROL_HEIGHT - size.width()) // 2
        self.icon().paint(painter, QtCore.QRect(left, (self.height() - size.height()) // 2, size.width(), size.height()))
        if self.text():
            painter.setPen(QtGui.QColor(self.surface.ink.foreground))
            painter.drawText(QtCore.QRect(CONTROL_HEIGHT - left + 4, 0, max(1, self.width() - CONTROL_HEIGHT - 4), self.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())

    def enterEvent(self, event: QtGui.QEnterEvent) -> None:  # noqa: N802 -- Qt native interface
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event: QtCore.QEvent) -> None:  # noqa: N802 -- Qt native interface
        super().leaveEvent(event)
        self.update()


def painter_path(contour: Contour) -> QtGui.QPainterPath:
    path = QtGui.QPainterPath()
    for node in contour:
        match node:
            case Move(x, y):
                path.moveTo(x, y)
            case Line(x, y):
                path.lineTo(x, y)
            case Curve(ax, ay, bx, by, x, y):
                path.cubicTo(ax, ay, bx, by, x, y)
            case End.CLOSE:
                path.closeSubpath()
            case _:
                assert_never(node)
    return path


class Pill(QtWidgets.QWidget):
    def __init__(self, loop: EventLoop, title: str, *, attached: bool = False) -> None:
        super().__init__()
        self.attached = attached
        self.joined_left = self.joined_right = False
        self.outline: Segment | None = None
        self.outline_size: tuple[int, int, bool, bool] | None = None
        self.anchor = QtCore.QPoint()
        self.origin = 0
        self.loop = loop
        # This Qt-owned timer merges native publications until the final state
        # of the current event turn. Layout/animation can change several joined
        # capsules before one painted frame; native COM paths must not observe
        # those intermediate shapes. The parent cancels delivery on disposal.
        self.glass_timer: QtCore.QTimer = QtCore.QTimer(self)
        self.glass_timer.setSingleShot(True)
        self.glass_timer.timeout.connect(self.publish_glass)
        self.layer: Glass | None = None
        self.colors = palette(Tone.REPLY)
        self.ink = Ink()
        self.frost = appearance.Frost.SMOKED
        self.glass = False
        self.look: tuple[Tone, appearance.Preference, appearance.Frost] | None = None
        self.bounds: Rect | None = None
        self.presented = False
        self.alpha: float = 0.0
        self.fade_from: float = 0.0
        self.fade_to: float = 0.0
        self.fade_started: float = 0.0
        self.buttons: list[tuple[Control, str]] = []
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.row = QtWidgets.QHBoxLayout(self)
        self.margins()
        self.row.setSpacing(1)
        self.setFixedHeight(BAR_HEIGHT)
        borderless(int(self.winId()))

    def margins(self) -> None:
        inset = SHOULDER + 5 if self.attached else 5
        self.row.setContentsMargins(inset, 2, inset, 2)

    def attached_width(self) -> int:
        return self.width() + (0 if self.attached else SHOULDER * 2)

    def shape(self) -> Segment | None:
        size = (self.width(), self.height(), self.joined_left, self.joined_right)
        if self.outline_size != size:
            self.outline_size = size
            self.outline = segment(size[0], size[1], left=self.joined_left, right=self.joined_right)
        return self.outline if self.attached else None

    def connections(self, *, left: bool = False, right: bool = False) -> None:
        if (left, right) != (self.joined_left, self.joined_right):
            self.joined_left, self.joined_right = left, right
            self.update()
            self.sync_glass()

    def button(self, name: str, text: str, tip: str, action: Callable[[], None]) -> Control:
        button = Control(self)
        button.setText(text)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setIconSize(QtCore.QSize(14, 14))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.clicked.connect(lambda: action())  # noqa: PLW0108  # Retain slotted callback owners.
        self.row.addWidget(button)
        self.buttons.append((button, name))
        self.recolor()
        return button

    def set_icon(self, button: QtWidgets.QToolButton, name: str) -> None:
        self.buttons = [(item, name if item is button else old) for item, old in self.buttons]
        button.setIcon(icon(name, self.ink.foreground))

    def material(self, tone: Tone, preference: appearance.Preference) -> None:
        look = (tone, preference, self.frost)
        if self.look == look:
            return
        self.look = look
        self.colors, self.ink = palette(tone), Ink()
        if isinstance(preference, appearance.Contrast):
            self.colors = Palette(preference.background, preference.foreground, preference.foreground, preference.background)
            self.ink = Ink(*(preference.foreground for _ in range(4)))
        elif preference is appearance.Material.GLASS and self.frost is appearance.Frost.BRIGHT:
            self.ink = Ink("#202435", "#3b3d50", "#234782", "#8e3144")
        if preference is appearance.Material.GLASS and self.layer is None and self.loop.composition is not None:
            try:
                self.layer = self.loop.composition.glass()
            except OSError as error:
                log_view(f"Toolbar glass unavailable; using solid material: {error}")
        self.glass = preference is appearance.Material.GLASS and self.layer is not None
        if not self.glass and not isinstance(preference, appearance.Contrast):
            self.ink = Ink()
        if self.layer is not None:
            self.layer.color(self.colors.tint, .82 if self.frost is appearance.Frost.SMOKED else .22)
            if not self.glass:
                self.layer.hide()
        self.recolor()
        self.update()
        self.sync_glass()

    def recolor(self) -> None:
        self.setStyleSheet(f"""
QToolButton {{ background: transparent; color: {self.ink.foreground}; border: 1px solid transparent;
 border-radius: 10px; padding: 0; font: 500 12px 'Segoe UI'; }}
QToolTip {{ background: {self.colors.surface}; color: {self.ink.foreground}; border: 1px solid {self.colors.edge}; padding: 6px; }}
""")
        for button, name in self.buttons:
            recording: object = button.property("recording")
            button.setIcon(icon(name, self.ink.error if recording is True else self.ink.foreground))

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        shape = self.shape()
        outline = painter_path(shape.fill) if shape is not None else QtGui.QPainterPath()
        if shape is None:
            radius = self.height() / 2
            outline.addRoundedRect(QtCore.QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), radius, radius)
        painter.fillPath(outline, QtGui.QColor(1, 1, 1, 1) if self.glass else QtGui.QColor(self.colors.surface))
        edge = QtGui.QColor(self.colors.edge)
        edge.setAlpha(85 if self.glass else 255)
        painter.setPen(QtGui.QPen(edge, 1))
        painter.drawPath(painter_path(shape.edge) if shape is not None else outline)

    def place(self, x: int, y: int, *, origin: int | None = None) -> None:
        self.anchor = QtCore.QPoint(x, y)
        self.origin = y if origin is None else origin
        self.move_frame()

    def move_frame(self) -> None:
        y = self.anchor.y()
        if self.presented or self.alpha > 0:
            hidden = self.origin - self.height()
            y = round(hidden + (y - hidden) * self.alpha)
        self.move(self.anchor.x(), y)
        self.sync_glass()

    def attach(self, attached: bool) -> None:
        if self.attached != attached:
            self.attached = attached
            self.margins()
            self.adjustSize()
            self.update()
            self.sync_glass()

    def show_activity(self, visible: bool, now: float, *, animate: bool) -> None:
        if visible == self.presented and self.fade_to == float(visible):
            return
        self.advance(now)
        self.presented = visible
        self.fade_from, self.fade_to, self.fade_started = self.alpha, float(visible), now
        if visible:
            self.move_frame()
            self.show()
        if not animate:
            self.alpha = self.fade_to
            self.fade_from = self.fade_to
        self.advance(now)

    def advance(self, now: float) -> bool:
        progress = min(1.0, max(0.0, (now - self.fade_started) / REVEAL_SECONDS))
        self.alpha = self.fade_from + (self.fade_to - self.fade_from) * ease_out(progress)
        if self.fade_from == self.fade_to:
            self.alpha = self.fade_to
        self.setWindowOpacity(self.alpha)
        if self.alpha == 0 and not self.presented:
            self.hide()
            if self.layer is not None:
                self.layer.hide()
        self.move_frame()
        return self.alpha != self.fade_to

    def sync_glass(self) -> None:
        if self.isVisible():
            self.bounds = windows.outer_rect(int(self.winId()))
            if not self.glass_timer.isActive():
                self.glass_timer.start(0)

    def publish_glass(self) -> None:
        if self.isVisible():
            self.bounds = windows.outer_rect(int(self.winId()))
            if self.glass and self.layer is not None:
                shape = self.shape()
                self.layer.position(self.bounds, self.devicePixelRatioF(), self.alpha, attached=self.attached,
                                    contour=shape.fill if shape is not None else None)
                self.layer.show(int(self.winId()))

    def dispose(self) -> None:
        self.glass_timer.stop()
        self.hide()
        if self.layer is not None:
            self.layer.close()
            self.layer = None
        self.deleteLater()
