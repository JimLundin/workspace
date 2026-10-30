"""The rounded bubble shared by floating notifications and canvas: surface, source badge and title."""

import math
from dataclasses import dataclass, field

lazy from PySide6 import QtGui
lazy from PySide6.QtCore import QRect, QRectF, Qt
lazy from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPaintEvent, QPen
lazy from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QLabel, QStyleOptionGraphicsItem, QWidget

import assistant.feed_icons
from assistant.feed_origin import App, Origin
from assistant.qt_runtime import prepare
from assistant.ui_components.appearance import INK, Palette
from assistant.ui_components.text import INSET, font

prepare()

TITLE_SIZE = 13.0


@dataclass(frozen=True, slots=True)
class BubbleAppearance:
    colors: Palette
    glass: bool = field(default=False, kw_only=True)


def paint_surface(painter: QPainter, bounds: QRectF, appearance: BubbleAppearance) -> QColor:
    """Qt owns the paint target; the same outline and solid fallback serve both hosts."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    outline = QPainterPath()
    outline.addRoundedRect(bounds.adjusted(8.5, 8.5, -0.5, -0.5), 26, 26)
    painter.fillPath(outline, QColor(1, 1, 1, 1) if appearance.glass else QColor(appearance.colors.surface))
    edge = QColor(appearance.colors.edge)
    edge.setAlpha(85 if appearance.glass else 255)
    painter.setPen(QPen(edge, 1))
    painter.drawPath(outline)
    return edge


def badge_origins(origins: tuple[Origin, ...], app: App = App.WORKSPACE) -> tuple[Origin, ...]:
    """A bubble without explicit sources shows the badge of the app that owns its content."""
    return origins or (Origin(app, app.value),)


def badge_width(origins: tuple[Origin, ...]) -> int:
    return 28 + 18 * (min(3, len(origins)) - 1)


def paint_origins(painter: QPainter, origins: tuple[Origin, ...], colors: Palette) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for index, origin in reversed(tuple(enumerate(origins[:3]))):
        x = index * 18
        painter.setPen(QPen(QColor(colors.edge), 1))
        painter.setBrush(QColor(colors.surface))
        painter.drawEllipse(QRectF(x + 0.5, 0.5, 27, 27))
        assistant.feed_icons.icon(origin.app).paint(painter, QRect(x + 5, 5, 18, 18))
    painter.restore()


def heading_height(text: str, width: int, *, expanded: bool) -> int:
    metrics = QFontMetricsF(font(TITLE_SIZE, bold=True))
    if expanded:
        return math.ceil(metrics.boundingRect(QRectF(0, 0, max(1, width), 10000), Qt.TextFlag.TextWordWrap.value, text).height())
    return math.ceil(metrics.height())


def heading_text(text: str, width: int, *, expanded: bool) -> str:
    return text if expanded else QFontMetricsF(font(TITLE_SIZE, bold=True)).elidedText(text, Qt.TextElideMode.ElideRight, width)


def paint_heading(painter: QPainter, rect: QRectF, text: str, *, expanded: bool) -> None:
    # Painter/target rectangle and full text/disclosure mode are the complete
    # native heading paint contract shared by widget and graphics adapters.
    painter.setFont(font(TITLE_SIZE, bold=True))
    flags = Qt.AlignmentFlag.AlignLeft.value | Qt.AlignmentFlag.AlignVCenter.value
    if expanded:
        flags |= Qt.TextFlag.TextWordWrap.value
    painter.drawText(rect, flags, heading_text(text, round(rect.width()), expanded=expanded))


def heading_width(width: int, badge: int, *, stopping: bool, disclosing: bool) -> int:
    """Agent/proposal titles share the fixed dismiss edge and optional controls."""
    right = width - INSET - 26
    edge = width - 32
    if stopping:
        edge = right - 28
        right -= 32
    if disclosing:
        edge = right - 28
    return max(1, edge - 8 - INSET - badge)


class CanvasHeading(QGraphicsRectItem):
    """The graphics scene owns this painted heading without an embedded QWidget."""

    def __init__(self, parent: QGraphicsItem) -> None:
        super().__init__(parent)
        self.value: str = ""
        self.expanded: bool = False
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def load(self, text: str, width: float, *, expanded: bool) -> int:
        self.value, self.expanded = text, expanded
        height = heading_height(text, round(width), expanded=expanded)
        self.setRect(0, 0, width, height)
        self.setToolTip(text)
        self.update()
        return height

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        painter.save()
        painter.setClipRect(self.rect())
        painter.setPen(QColor(INK))
        paint_heading(painter, self.rect(), self.value, expanded=self.expanded)
        painter.restore()


class FeedTitle(QLabel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        # Qt owns mutable presentation; these flags select its current paint/layout.
        self.flow: bool = False
        self.expanded: bool = False

    def display_text(self) -> str:
        return heading_text(self.text(), self.width(), expanded=self.expanded)

    def heightForWidth(self, width: int) -> int:
        if not self.flow:
            return super().heightForWidth(width)
        return heading_height(self.text(), width, expanded=self.expanded)

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self.flow:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setPen(self.palette().color(QtGui.QPalette.ColorRole.WindowText))
        paint_heading(painter, QRectF(self.rect()), self.text(), expanded=self.expanded)
        painter.end()
