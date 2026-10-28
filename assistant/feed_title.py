"""Compact headings elide; expanded headings wrap with the same measured font."""

import math

from .qt import QFontMetricsF, QLabel, QPainter, QPaintEvent, QRectF, Qt, QtGui, QWidget
from .qt_text import INSET, font

TITLE_SIZE = 13.0


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
        if self.expanded:
            return self.text()
        return QFontMetricsF(font(TITLE_SIZE, bold=True)).elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())

    def heightForWidth(self, width: int) -> int:  # noqa: N802 -- Qt override
        if not self.flow:
            return super().heightForWidth(width)
        if self.expanded:
            return math.ceil(QFontMetricsF(font(TITLE_SIZE, bold=True)).boundingRect(
                QRectF(0, 0, max(1, width), 10000), Qt.TextFlag.TextWordWrap.value, self.text()).height())
        return math.ceil(QFontMetricsF(font(TITLE_SIZE, bold=True)).height())

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 -- Qt override
        if not self.flow:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setPen(self.palette().color(QtGui.QPalette.ColorRole.WindowText))
        painter.setFont(font(TITLE_SIZE, bold=True))
        flags = Qt.AlignmentFlag.AlignLeft.value | Qt.AlignmentFlag.AlignVCenter.value
        if self.expanded:
            flags |= Qt.TextFlag.TextWordWrap.value
        painter.drawText(QRectF(self.rect()), flags, self.display_text())
        painter.end()
