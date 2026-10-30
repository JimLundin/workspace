"""Measured native bubbles and spatial interaction on the desktop canvas.

Qt owns text layout, painting and drag state. Each text viewport is measured and
clipped to its own bounds; the bubble then sizes around those measured regions.
"""

import math
from typing import override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.canvas_activity import Attention, CanvasAction, CanvasQuestion, CanvasUpdate
from assistant.feed_origin import App, Origin
from assistant.notifications import Tone
from assistant.ui_components.appearance import Palette, palette
from assistant.ui_components.bubble import BubbleAppearance, CanvasHeading, badge_origins, badge_width, paint_origins, paint_surface
from assistant.ui_components.canvas_bubble import CanvasBubble, CanvasEvents
from assistant.ui_components.canvas_controls import CanvasControl, ControlAction
from assistant.ui_components.text import PlainLayout, font
from assistant.work_canvas_context import ContextGroup, descendants
from assistant.work_canvas_model import CanvasContent, caption, summary, title
from automation.personal_work import SourceKind, WorkSource, WorkThread


class CanvasText(QtWidgets.QGraphicsRectItem):
    """The component owns a measured viewport, not a free-floating text item."""

    def __init__(self, parent: QtWidgets.QGraphicsItem) -> None:
        super().__init__(parent)
        self.document: PlainLayout = PlainLayout()
        self.text: str = ""
        self.setCacheMode(QtWidgets.QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def load(self, text: str, width: float, maximum: float = 10000) -> float:
        # Preview space is bounded and stable before painting. Qt's viewport
        # culling then shapes text only for bubbles actually on screen.
        self.text = " ".join(text.split())
        height = maximum if text else 0
        self.setRect(0, 0, width, height)
        self.update()
        return height

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem, widget: QtWidgets.QWidget | None = None) -> None:
        painter.save()
        painter.setClipRect(self.rect())
        self.document.load(self.text, self.rect().width(), self.rect().height())
        self.document.draw(painter)
        painter.restore()


class CanvasContents(QtWidgets.QGraphicsRectItem):
    """Every container uses the same disclosure and focus controls."""

    def __init__(self, parent: QtWidgets.QGraphicsItem, events: CanvasEvents, identity: str) -> None:
        super().__init__(parent)
        self.setRect(0, 0, 312, 32)
        self.setPen(Qt.PenStyle.NoPen)
        self.disclosure: CanvasControl = CanvasControl(self, ControlAction("Show contents", lambda: events.toggle_bubble(identity)))
        self.open_canvas: CanvasControl = CanvasControl(
            self, ControlAction("Expand and center this bubble", lambda: events.open_context(identity), "center")
        )
        self.resize(312)

    def resize(self, width: float) -> None:
        self.setRect(0, 0, width, 32)
        self.disclosure.set_width(width - 40)
        self.open_canvas.setPos(width - 32, 0)

    def refresh(self, count: int, *, expanded: bool) -> None:
        unit = "piece" if count == 1 else "pieces"
        self.disclosure.set_caption(("▾ Hide" if expanded else "▸ Show") + f" {count} {unit}")
        self.disclosure.setToolTip("Collapse these pieces" if expanded else "Expand these pieces on the canvas")


class CanvasCard(CanvasBubble):
    def __init__(self, content: CanvasContent, events: CanvasEvents) -> None:
        super().__init__(content.id, events)
        self.content: CanvasContent = content
        self.expanded: bool = False
        self.detail: QtWidgets.QWidget | None = None
        self.detail_proxy: QtWidgets.QGraphicsProxyWidget | None = None
        self.app: App = source_app(content)
        self.colors: Palette = palette(Tone.REPLY, self.app)
        self.compact_height: float = 0
        self.own_size: QtCore.QSizeF = QtCore.QSizeF()
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.heading: QtWidgets.QGraphicsTextItem = QtWidgets.QGraphicsTextItem(self)
        self.heading.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.title_label: CanvasHeading = CanvasHeading(self)
        self.preview: CanvasText = CanvasText(self)
        self.child_count: int = 0
        self.contents_expanded: bool = False
        self.contents: CanvasContents | None = None
        self.refresh(content)

    def refresh(self, content: CanvasContent) -> None:
        self.content = content
        self.app = source_app(content)
        match content:
            case CanvasQuestion(reply=Attention.WAITING):
                tone = Tone.QUESTION
            case _:
                tone = Tone.REPLY
        self.colors = palette(tone, self.app)
        self.setToolTip(title(content) + "\nClick to read; drag to arrange")
        self.relayout()

    def relayout(self) -> None:
        width = 480 if self.expanded else 360
        text_width = width - 48
        self.heading.setFont(font(8.5))
        self.heading.setDefaultTextColor(QtGui.QColor("#b7afc9"))
        origins = source_origins(self.content)
        heading_x = badge_width(origins) + 16
        title_width = width - heading_x - 64
        title_height = self.title_label.load(title(self.content), title_width, expanded=self.expanded)
        self.title_label.setPos(heading_x, 18)
        self.heading.setPlainText(QtGui.QFontMetricsF(font(8.5)).elidedText(caption(self.content), Qt.TextElideMode.ElideRight, title_width))
        self.heading.setTextWidth(title_width)
        self.heading.setPos(heading_x, 18 + title_height + 2)
        body_y = 18 + title_height + self.heading.boundingRect().height() + 14
        # A three-line preview must not lay out an entire mail/ticket excerpt.
        # The detail editor retains the complete source evidence.
        preview_height = self.preview.load(summary(self.content)[:600], text_width, 52)
        self.preview.setPos(24, body_y)
        self.preview.setVisible(not self.expanded)
        self.compact_height = body_y + preview_height + 26
        if self.expanded and self.detail_proxy is not None and self.detail is not None:
            self.detail.setFixedWidth(round(text_width))
            self.detail_proxy.setPos(24, body_y)
            self.detail_proxy.resize(text_width, self.detail.height())
            height = body_y + self.detail.height() + 26
        else:
            height = self.compact_height
        if self.contents is not None:
            self.contents.setVisible(self.child_count > 0)
            if self.child_count:
                self.contents.resize(text_width)
                self.contents.setPos(24, height - 12)
                height += 32
        self.own_size = QtCore.QSizeF(width, max(120, height))
        self.setRect(0, 0, self.own_size.width(), self.own_size.height())
        self.resize_controls()
        self.update()

    def set_contents(self, count: int, *, expanded: bool) -> None:
        if count == self.child_count and expanded == self.contents_expanded:
            return
        self.child_count, self.contents_expanded = count, expanded
        if count and self.contents is None:
            self.contents = CanvasContents(self, self.events, self.content.id)
        if self.contents is not None:
            self.contents.refresh(count, expanded=expanded)
        self.relayout()

    def contain(self, bounds: QtCore.QRectF, depth: int) -> None:
        self.setRect(0, 0, bounds.width(), bounds.height())
        self.setPos(bounds.topLeft())
        self.setZValue(depth)
        self.resize_controls()
        if self.contents is not None:
            self.contents.resize(bounds.width() - 48)

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem, widget: QtWidgets.QWidget | None = None) -> None:
        paint_surface(painter, self.rect(), BubbleAppearance(self.colors))
        paint_origins(painter, source_origins(self.content), self.colors)
        self.paint_selection(painter)

    def show_detail(self, widget: QtWidgets.QWidget) -> None:
        if self.detail is None:
            self.detail = widget
            self.detail_proxy = QtWidgets.QGraphicsProxyWidget(self)
            self.detail_proxy.setWidget(widget)
        self.set_expanded(expanded=not self.expanded)
        self.events.reflow()

    def set_expanded(self, *, expanded: bool) -> None:
        self.expanded = expanded
        if self.detail is not None:
            self.detail.setVisible(expanded)
        self.setZValue(10 if self.expanded else 1)
        self.relayout()


class CanvasViewport(QtWidgets.QGraphicsView):
    resized = QtCore.Signal()

    def __init__(self, scene: QtWidgets.QGraphicsScene) -> None:
        super().__init__(scene)
        self.setAccessibleName("Your work canvas")
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QtGui.QColor("#18171e"))
        # Qt owns the background raster and invalidates it on zoom/resize.
        # Static grid painting must not repeat during source/editor interaction.
        self.setCacheMode(QtWidgets.QGraphicsView.CacheModeFlag.CacheBackground)
        # Qt owns this reusable texture; refresh its dot size on zoom so a
        # zoomed-out grid keeps its screen spacing and visible dot diameter.
        self.grid_scale: float = 0
        self.grid_brush: QtGui.QBrush | None = None

    @override
    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        item = self.itemAt(event.pos())
        while item is not None:
            match item:
                case CanvasBubble():
                    item.events.context_menu(item.identity)
                    event.accept()
                    return
                case _:
                    item = item.parentItem()
        super().contextMenuEvent(event)

    @override
    def drawBackground(self, painter: QtGui.QPainter, rect: QtCore.QRectF | QtCore.QRect) -> None:
        # Scene-anchored dots retain their screen size. Coarser levels
        # replace dense grids at low zoom instead of aliasing a shrunken tile.
        scale = self.transform().m11()
        spacing = 32
        while spacing * scale < 24:
            spacing *= 2
        if self.grid_brush is None or self.grid_scale != scale:
            tile = QtGui.QPixmap(128, 128)
            tile.fill(QtGui.QColor("#18171e"))
            dots = QtGui.QPainter(tile)
            dots.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            dots.setPen(Qt.PenStyle.NoPen)
            dots.setBrush(QtGui.QColor("#4b4358"))
            radius = 0.8 * 128 / (spacing * scale)
            for x, y in ((0, 0), (128, 0), (0, 128), (128, 128)):
                dots.drawEllipse(QtCore.QPointF(x, y), radius, radius)
            dots.end()
            brush = QtGui.QBrush(tile)
            brush.setTransform(QtGui.QTransform().scale(spacing / 128, spacing / 128))
            self.grid_brush, self.grid_scale = brush, scale
        painter.fillRect(rect, self.grid_brush)

    @override
    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.resized.emit()

    def zoom(self, factor: float) -> None:
        current = self.transform().m11()
        target = max(0.15, min(1.6, current * factor))
        self.scale(target / current, target / current)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        delta = event.pixelDelta() if not event.pixelDelta().isNull() else event.angleDelta()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(math.pow(1.15, delta.y() / 120))
        else:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
        event.accept()

    @override
    def viewportEvent(self, event: QtCore.QEvent) -> bool:
        match event:
            case QtGui.QNativeGestureEvent() if event.gestureType() is Qt.NativeGestureType.ZoomNativeGesture:
                self.zoom(math.exp(event.value()))
                event.accept()
                return True
            case _:
                return super().viewportEvent(event)


def source_app(content: CanvasContent) -> App:
    match content:
        case WorkSource(kind=SourceKind.TEAMS):
            return App.TEAMS
        case WorkSource(kind=SourceKind.OUTLOOK):
            return App.OUTLOOK
        case WorkSource(kind=SourceKind.DOCUMENT):
            return App.DOCUMENT
        case WorkSource(kind=SourceKind.WEB_PAGE):
            return App.WEB_PAGE
        case WorkSource(kind=SourceKind.KANBAN):
            return App.KANBAN
        case CanvasUpdate(origins=origins) | CanvasQuestion(origins=origins) | CanvasAction(origins=origins) if origins:
            return origins[0].app
        case _:
            return App.WORKSPACE


def source_origins(content: CanvasContent) -> tuple[Origin, ...]:
    match content:
        case CanvasUpdate(origins=origins) | CanvasQuestion(origins=origins) | CanvasAction(origins=origins):
            return badge_origins(origins)
        case _:
            return badge_origins((), source_app(content))


class CanvasGroup(CanvasBubble):
    """A recursive context uses the same bubble surface, heading and controls."""

    def __init__(self, group: ContextGroup, bounds: QtCore.QRectF, events: CanvasEvents) -> None:
        super().__init__(group.id, events)
        self.context: ContextGroup = group
        self.colors: Palette = palette(Tone.REPLY, App.WORKSPACE)
        self.origins: tuple[Origin, ...] = ()
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        self.title_label: CanvasHeading = CanvasHeading(self)
        self.heading: QtWidgets.QGraphicsSimpleTextItem = QtWidgets.QGraphicsSimpleTextItem(self)
        self.heading.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.heading.setFont(font(8.5))
        self.heading.setBrush(QtGui.QColor("#b7afc9"))
        self.preview: CanvasText = CanvasText(self)
        self.contents: CanvasContents = CanvasContents(self, events, group.id)
        self.refresh(group, bounds)

    def refresh(self, group: ContextGroup, bounds: QtCore.QRectF) -> None:
        if self.origins and self.context == group and self.rect().size() == bounds.size():
            self.setPos(bounds.topLeft())
            return
        self.context = group
        self.setRect(0, 0, bounds.width(), bounds.height())
        self.setPos(bounds.topLeft())
        self.setToolTip(group.title + "\nClick to show contents; double-click to center this bubble")
        unique = frozendict((origin.app, origin) for nested in descendants(group) for item in nested.pieces for origin in source_origins(item))
        self.origins = badge_origins(tuple(unique.values()))
        title_x = badge_width(self.origins) + 16
        self.title_label.load(group.title, bounds.width() - title_x - 64, expanded=False)
        self.title_label.setPos(title_x, 18)
        count = len(group.children) + len(group.items)
        match group.container:
            case WorkThread(definition=definition):
                caption_text = "Work context · " + definition.state.value.capitalize()
                preview = "\n".join(
                    part for part in (definition.goal, definition.summary, "Next: " + definition.next_step if definition.next_step else "") if part
                )
            case _:
                caption_text = "Group"
                preview = " · ".join((*tuple(child.title for child in group.children), *tuple(title(item) for item in group.items)))
        self.heading.setText(caption_text)
        self.heading.setPos(title_x, 48)
        self.preview.load(preview[:600], bounds.width() - 48, 52)
        self.preview.setPos(24, 78)
        self.contents.refresh(count, expanded=group.expanded)
        self.contents.resize(bounds.width() - 48)
        self.contents.setPos(24, 132)
        self.resize_controls()
        self.update()

    @override
    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem, widget: QtWidgets.QWidget | None = None) -> None:
        paint_surface(painter, self.rect(), BubbleAppearance(self.colors))
        paint_origins(painter, self.origins, self.colors)

        self.paint_selection(painter)
