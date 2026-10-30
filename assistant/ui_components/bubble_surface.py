"""The shared rounded bubble paint contract for desktop conversations and canvas."""

from dataclasses import dataclass, field

lazy from PySide6.QtCore import QRectF
lazy from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from assistant.ui_components.bubble_style import Palette


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
