"""Compact headings elide; expanded headings wrap with the same measured font."""

import math

lazy from PySide6 import QtGui
lazy from PySide6.QtCore import QRectF, Qt
lazy from PySide6.QtGui import QFontMetricsF, QPainter, QPaintEvent
lazy from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QLabel, QStyleOptionGraphicsItem, QWidget

from assistant.qt_runtime import prepare
from assistant.ui_components.text import INSET, font

prepare()

TITLE_SIZE = 13.0


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
        painter.setPen(QtGui.QColor("#f6f3ff"))
        paint_heading(painter, self.rect(), self.value, expanded=self.expanded)
        painter.restore()


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
