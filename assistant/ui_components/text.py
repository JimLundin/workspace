"""Selectable, incrementally updated Markdown on a per-pixel transparent surface."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

lazy import shiboken6
lazy from PySide6.QtCore import QPoint, QPointF, Qt
lazy from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFont,
    QFontMetricsF,
    QPainter,
    QPalette,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextLayout,
    QTextLine,
    QTextOption,
    QWheelEvent,
)
lazy from PySide6.QtWidgets import QFrame, QMenu, QTextBrowser, QWidget

from assistant.qt_runtime import prepare
from assistant.rich_text import Span, changed_tail
from assistant.ui_components import typeface
from assistant.ui_components.appearance import DARK, GLASS_ACCENT, GREEN, RED, Shade, Tokens

prepare()

BODY: Final = 13.0  # pixels, as the kit's body text
STEP: Final = 12.0
META: Final = 11.5
LEADING: Final = 114  # percent of Inter's font height: the kit's 1.38 line height
MONOSPACE: Final = "Consolas"


@dataclass(frozen=True, slots=True)
class TextInk:
    """Ink for text inside a surface: body and secondary, meaning, code wells and selection."""

    ink: Shade
    quiet: Shade  # body text and meta, as the kit's ink2
    link: Shade
    error: Shade
    success: Shade
    well: Shade  # inline code
    selection: Shade
    selected: Shade  # selected text


def text_ink(theme: Tokens) -> TextInk:
    return TextInk(theme.ink, theme.ink2, Shade(GLASS_ACCENT), Shade(RED), Shade(GREEN), theme.fill, Shade(GLASS_ACCENT, 0.42), theme.ink)


def contrast_ink(foreground: str, background: str) -> TextInk:
    """High contrast keeps every role in the system foreground; selection swaps the system colours."""
    ink = Shade(foreground)
    return TextInk(ink, ink, ink, ink, ink, Shade(foreground, 0.12), ink, Shade(background))


def color(shade: Shade) -> QColor:
    value = QColor(shade.color)
    value.setAlphaF(shade.opacity)
    return value


def face(pixels: float, weight: int = 400, family: str = typeface.FAMILY) -> QFont:
    """Inter at a pixel size and CSS weight; Qt's 96 logical DPI makes a point 4/3 pixels."""
    value = QFont(family)
    value.setPointSizeF(pixels * 0.75)
    value.setWeight(QFont.Weight(weight))
    return value


def line_height(value: QFont) -> float:
    return QFontMetricsF(value).height() * LEADING / 100


def font(size: float = 10.5, *, bold: bool = False, family: str = "Segoe UI") -> QFont:
    """The canvas's point-sized face, until the canvas adopts `face`."""
    value = QFont(family)
    value.setPointSizeF(size)
    value.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    return value


def units(text: str) -> int:
    """Qt cursor positions count UTF-16 units, including astral emoji."""
    return len(text.encode("utf-16-le")) // 2


def _size(tags: tuple[str, ...]) -> float:
    if "heading" in tags:
        return 17 if "h1" in tags else 15 if "h2" in tags else BODY
    if any(tag in tags for tag in ("step", "step_detail", "step_error")):
        return STEP
    return BODY


def _ink(span: Span, ink: TextInk) -> Shade:
    if span.link:
        return ink.link
    if "step_error" in span.tags:
        return ink.error
    if any(tag in span.tags for tag in ("bold", "heading", "step")):
        return ink.ink
    return ink.quiet


def character_style(span: Span, ink: TextInk) -> QTextCharFormat:
    style = QTextCharFormat()
    code = "code" in span.tags
    weight = 600 if "bold" in span.tags or "heading" in span.tags else 400
    value = face(_size(span.tags) - (1 if code else 0), weight, MONOSPACE if code else typeface.FAMILY)
    value.setItalic("italic" in span.tags)
    value.setStrikeOut("strike" in span.tags)
    style.setFont(value)
    if span.link:
        style.setAnchor(True)
        style.setAnchorHref(span.link)
        style.setFontUnderline(True)
    if code:
        style.setBackground(color(ink.well))
    style.setForeground(color(_ink(span, ink)))
    return style


def paragraph_style(span: Span) -> QTextBlockFormat:
    style = QTextBlockFormat()
    hanging = QFontMetricsF(face(BODY)).horizontalAdvance(span.hanging)
    style.setLeftMargin(min(span.indent, 6) * 16 + hanging + (4 if "codeblock" in span.tags else 0))
    style.setTextIndent(-hanging)
    style.setLineHeight(LEADING, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
    return style


class PlainLayout:
    """Qt lays out only the visible lines of a bounded plain-text preview.

    This native owner keeps its QTextLayout and line handles; large source
    excerpts stay in the domain/detail editor instead of a full preview document.
    """

    def __init__(self) -> None:
        self.qt: QTextLayout = QTextLayout()
        self.qt.setFont(font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.qt.setTextOption(option)
        self.lines: tuple[QTextLine, ...] = ()
        self.observed: tuple[str, float, float] | None = None
        self.height: float = 0

    def load(self, text: str, width: float, maximum: float) -> float:
        observed = text, width, maximum
        if observed == self.observed:
            return self.height
        self.qt.clearLayout()
        self.qt.setText(text.replace("\n", "\u2028"))
        self.qt.beginLayout()
        self.lines = ()
        height = 0.0
        try:
            while True:
                line = self.qt.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(max(1, width))
                bottom = height + line.height() * 1.25
                if math.ceil(bottom) > maximum:
                    break
                line.setPosition(QPointF(0, height))
                self.lines = (*self.lines, line)
                height = bottom
        finally:
            self.qt.endLayout()
        self.observed, self.height = observed, math.ceil(height)
        return self.height

    def draw(self, painter: QPainter) -> None:
        painter.setPen(color(DARK.ink))
        for line in self.lines:
            line.draw(painter, QPointF())


class Document:
    __slots__ = ("ink", "qt", "spans")

    def __init__(self, parent: QWidget | None = None) -> None:
        self.qt = QTextDocument(parent)
        self.qt.setDefaultFont(face(BODY))
        self.qt.setDocumentMargin(0)
        self.qt.setUndoRedoEnabled(False)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.qt.setDefaultTextOption(option)
        self.spans: tuple[Span, ...] = ()
        self.ink = text_ink(DARK)

    def load(self, spans: tuple[Span, ...], width: float) -> float:
        if spans != self.spans:
            tail = changed_tail(self.spans, spans)
            previous = "".join(span.text for span in self.spans)
            self.spans = spans
            cursor = QTextCursor(self.qt)
            cursor.setPosition(units(previous[: tail.offset]))
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            cursor.beginEditBlock()
            cursor.removeSelectedText()
            for span in tail.spans:
                style = character_style(span, self.ink)
                for part in span.text.splitlines(keepends=True):
                    if part.strip() or cursor.atBlockStart():
                        cursor.setBlockFormat(paragraph_style(span))
                    cursor.insertText(part, style)
            cursor.endEditBlock()
        width = max(1.0, width)
        if self.qt.textWidth() != width:
            self.qt.setTextWidth(width)
        return self.height

    @property
    def height(self) -> float:
        return self.qt.size().height() if self.spans else 0.0

    def intrinsic_width(self, spans: tuple[Span, ...], maximum: float) -> float:
        if not spans:
            return 0
        self.load(spans, maximum)
        widest = 0.0
        block = self.qt.begin()
        while block.isValid():
            layout = block.layout()
            if layout.lineCount() > 1:
                return maximum
            if layout.lineCount():
                line = layout.lineAt(0)
                widest = max(widest, line.x() + line.naturalTextWidth())
            block = block.next()
        return min(maximum, math.ceil(widest) + 1)

    def fit(self, available: float) -> float:
        """End a shortened viewport on a complete rendered line."""
        if self.height <= available:
            return math.ceil(self.height)
        used = 0.0
        block = self.qt.begin()
        document_layout = self.qt.documentLayout()
        while block.isValid():
            layout = block.layout()
            top = document_layout.blockBoundingRect(block).top()
            for index in range(layout.lineCount()):
                line = layout.lineAt(index)
                bottom = top + line.y() + line.height()
                if math.ceil(bottom) > available:
                    return math.ceil(used)
                used = bottom
            block = block.next()
        return math.ceil(used)

    def recolor(self, ink: TextInk) -> None:
        if self.ink == ink:
            return
        self.ink = ink
        cursor = QTextCursor(self.qt)
        cursor.beginEditBlock()
        offset = 0
        for span in self.spans:
            cursor.setPosition(offset)
            offset += units(span.text)
            cursor.setPosition(offset, QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(character_style(span, ink))
        cursor.endEditBlock()

    def close(self) -> None:
        shiboken6.delete(self.qt)


class TextView(QTextBrowser):
    __slots__ = ("content", "on_menu", "on_scroll")

    def __init__(self, parent: QWidget, on_scroll: Callable[[int], None], on_menu: Callable[[QPoint], None]) -> None:
        super().__init__(parent)
        self.content = Document(self)
        self.setDocument(self.content.qt)
        self.on_scroll, self.on_menu = on_scroll, on_menu
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QTextBrowser { background: transparent; border: none; padding: 0; margin: 0; border-radius: 0; }")
        self.viewport().setAutoFillBackground(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setOpenExternalLinks(True)
        self.setUndoRedoEnabled(False)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.setAccessibleName("Conversation text")

    @property
    def offset(self) -> int:
        return self.verticalScrollBar().value()

    def update_spans(self, spans: tuple[Span, ...], width: float) -> None:
        offset = self.offset
        cursor = self.textCursor()
        anchor, position = cursor.anchor(), cursor.position()
        self.content.load(spans, width)
        # QTextDocument edits move the editor's cursor too. Restore both ends:
        # keeping only its position would select all newly inserted text.
        limit = self.document().characterCount() - 1
        cursor.setPosition(min(anchor, limit))
        cursor.setPosition(min(position, limit), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.verticalScrollBar().setValue(offset)

    def fit_width(self) -> None:
        """Use the actual viewport even when new content leaves widget geometry unchanged."""
        self.content.load(self.content.spans, max(1, self.viewport().width()))

    def recolor(self, ink: TextInk) -> None:
        offset = self.offset
        self.content.recolor(ink)
        colors = self.palette()
        colors.setColor(QPalette.ColorRole.Text, color(ink.quiet))
        colors.setColor(QPalette.ColorRole.Highlight, color(ink.selection))
        colors.setColor(QPalette.ColorRole.HighlightedText, color(ink.selected))
        colors.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        self.setPalette(colors)
        self.content.qt.size()  # Resolve layout before restoring a pixel position.
        self.verticalScrollBar().setValue(offset)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.on_scroll(event.angleDelta().y())
        event.accept()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self.on_menu(event.globalPos())
        event.accept()

    def copy_menu(self, point: QPoint, history: Callable[[], None]) -> None:
        menu = QMenu(self)
        copy = menu.addAction("Copy selection", self.copy)
        copy.setEnabled(self.textCursor().hasSelection())
        menu.addSeparator()
        menu.addAction("Agent session", history)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(point)
