"""Shared Qt controls, selection-preserving text updates and native window behavior."""

import threading
from collections.abc import Callable, Sequence
from typing import override

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.components.appearance import KIT, Kit, Shade, Tokens, control_style, scheme, tokens
from desktop_ui.components.typeface import TYPE
from desktop_ui.qt_runtime import prepare
from desktop_ui.vector_icons import icon
from winapi import windows
from winapi.shapes import Size

prepare()


def window_style(theme: Tokens, kit: Kit) -> str:
    """The shared controls on the kit's solid window, and its segmented choices."""
    segment, choice = theme.segment, kit.choice
    return (
        control_style(theme, kit)
        + f"""
QWidget#workspaceWindow {{ background: {theme.window}; }}
QFrame#segmented {{ background: {theme.hover.css}; border-radius: {kit.segmented_radius}px; }}
QFrame#segmented QToolButton {{ border-radius: {kit.choice_radius}px; {choice.css()} min-height: {kit.choice_least}px; {TYPE.label.css} }}
QFrame#segmented QToolButton:focus {{ {choice.css(kit.ring)} }}
QFrame#segmented QToolButton:checked {{ background: {segment}; }}
"""
    )


def surface_style(theme: Tokens, radius: int, kit: Kit) -> str:
    """A solid surface from the kit: the window colour, a hairline edge and large concentric corners."""
    edge = f"{kit.hairline}px solid {theme.solid_edge.css}"
    return f"QFrame#surface {{ background: {theme.window}; border: {edge}; border-radius: {radius}px; }}"


def tool_window(window: QtWidgets.QWidget, title: str | None, *, on_top: bool) -> None:
    """A frameless, translucent tool window that shows without activating; `on_top` keeps it above other windows."""
    if title is not None:
        window.setWindowTitle(title)
    flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
    window.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint if on_top else flags)
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)


def device_size(widget: QtWidgets.QWidget, scale: float) -> Size:
    """A widget's logical size in device pixels at `scale`."""
    return Size(round(widget.width() * scale), round(widget.height() * scale))


def surface(window: QtWidgets.QWidget, theme: Tokens, radius: int, kit: Kit) -> QtWidgets.QFrame:
    """Draw a `tool_window` as one rounded surface; its corners stay transparent."""
    frame = QtWidgets.QFrame(window)
    frame.setObjectName("surface")
    frame.setStyleSheet(surface_style(theme, radius, kit))
    column(window).addWidget(frame)
    return frame


def segmented(buttons: Sequence[QtWidgets.QToolButton], kit: Kit) -> QtWidgets.QFrame:
    """Checkable choices in one well; the checked choice carries the thumb."""
    frame = QtWidgets.QFrame()
    frame.setObjectName("segmented")
    layout = row(frame)
    inset = kit.segmented_inset
    layout.setContentsMargins(inset, inset, inset, inset)
    layout.setSpacing(inset)
    for choice in buttons:
        layout.addWidget(choice)
    return frame


def glyph(name: str, ink: Shade, size: int = 16) -> QtGui.QPixmap:
    """A symbol in translucent ink, such as the secondary ink; SVG fills take no alpha."""
    solid = icon(name, ink.color, size).pixmap(QtCore.QSize(size, size))
    faded = QtGui.QPixmap(solid.size())
    faded.setDevicePixelRatio(solid.devicePixelRatio())
    faded.fill(Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(faded)
    painter.setOpacity(ink.opacity)
    painter.drawPixmap(0, 0, solid)
    painter.end()
    return faded


class Window(QtWidgets.QWidget):
    def __init__(self, title: str, close: Callable[[], None], *, width: int = 900, height: int = 640) -> None:
        super().__init__()
        self.on_close = close
        self.setObjectName("workspaceWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setWindowTitle(title)
        self.setStyleSheet(window_style(tokens(scheme()), KIT))
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(width, height)
        self.escape = QtGui.QShortcut(QtGui.QKeySequence("Escape"), self)

        self.escape.activated.connect(self.escaped)

    def escaped(self) -> None:
        self.on_close()

    @override
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        event.ignore()
        self.on_close()


def show_window(window: QtWidgets.QWidget, *, focus: bool, target: QtWidgets.QWidget | None = None) -> None:
    handle = int(window.winId())
    windows.allow_activation(handle, allowed=False)
    try:
        window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        window.show()
        windows.show_quietly(handle, visible=True, topmost=False)
        # Qt's first quiet show can leave a maximized widget at normal native
        # geometry. Apply its requested state while activation is still blocked.
        if window.isMaximized() and not windows.is_maximized(handle):
            windows.show(handle, windows.SW_MAXIMIZE)
    finally:
        windows.allow_activation(handle, allowed=True)
    if focus:
        threading.Thread(target=lambda: windows.focus(handle), name="focus workspace", daemon=True).start()
        (target or window).setFocus(Qt.FocusReason.OtherFocusReason)


def near_pointer(window: QtWidgets.QWidget, width: int, height: int) -> None:
    """Size `window` and put it under the pointer, inside the pointer's screen."""
    point = QtGui.QCursor.pos()
    display = QtWidgets.QApplication.screenAt(point) or window.screen()
    area = display.availableGeometry()
    window.resize(width, height)
    window.move(
        max(area.left(), min(point.x() - width // 2, area.right() - width)), max(area.top(), min(point.y() - height // 3, area.bottom() - height))
    )


def _spaced[L: QtWidgets.QBoxLayout](layout: L, spacing: int) -> L:
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    return layout


def row(parent: QtWidgets.QWidget | None = None) -> QtWidgets.QHBoxLayout:
    return _spaced(QtWidgets.QHBoxLayout(parent) if parent is not None else QtWidgets.QHBoxLayout(), 8)


def column(parent: QtWidgets.QWidget | None = None) -> QtWidgets.QVBoxLayout:
    return _spaced(QtWidgets.QVBoxLayout(parent) if parent is not None else QtWidgets.QVBoxLayout(), 10)
