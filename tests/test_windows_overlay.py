"""Live key feedback on a hidden Qt canvas, without taking focus or sending input."""

import sys
import time
import unittest
from collections.abc import Generator
from contextlib import contextmanager

if sys.platform != "win32":
    raise unittest.SkipTest("Windows overlay")

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.qt_runtime import prepare
from assistant.qt_ui import application
from assistant.ui import KeymapCanvas, KeymapOverlay
from miryoku.layout import AGENT, TALK, Layer, Scancode
from winapi.shapes import Rect

prepare()

WORK = Rect(0, 0, 1920, 1040)
Q, M = Scancode(0x10), Scancode(0x32)


class HiddenDesktop:
    """Own scripted desktop observations without presenting native windows.

    Cursor and clock values change as the fixture drives events; the saved
    position captures the persistence outcome of that same drag lifetime.
    """

    def __init__(self) -> None:
        self.now: float | None = 1.0
        self.point: tuple[int, int] = (0, 0)
        self.position: tuple[int, int] | None = (1000, 600)
        self.windows: list[QtWidgets.QWidget] = []
        self.moves: tuple[tuple[int, Rect], ...] = ()

    def clock(self) -> float:
        return time.monotonic() if self.now is None else self.now

    def cursor(self) -> tuple[int, int]:
        return self.point

    def work_areas(self) -> tuple[Rect, ...]:
        return ()

    def load_position(self) -> tuple[int, int] | None:
        return self.position

    def save_position(self, position: tuple[int, int]) -> None:
        self.position = position

    def prepare(self, window: QtWidgets.QWidget, *, click_through: bool) -> int:
        self.windows.append(window)
        return int(window.winId())

    def present(self, window: QtWidgets.QWidget) -> None:
        window.hide()

    def move(self, frame: int, area: Rect) -> None:
        self.moves = (*self.moves, (frame, area))

    def canvas(self) -> KeymapCanvas:
        value = self.windows[0].findChild(KeymapCanvas)
        assert value is not None
        return value


@contextmanager
def hidden_overlay() -> Generator[tuple[QtWidgets.QApplication, KeymapOverlay, HiddenDesktop]]:
    root = application()
    desktop = HiddenDesktop()
    overlay = KeymapOverlay(root, desktop)
    try:
        overlay.show(None, "BASE", WORK, visible=True)
        yield root, overlay, desktop
    finally:
        overlay.show(None, "BASE", WORK, visible=False)
        for window in desktop.windows:
            window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def key_style(canvas: KeymapCanvas, name: str) -> tuple[str, ...]:
    background, foreground = canvas.colors(name)
    return background, foreground, foreground, foreground


def test_overlay_drag_retains_physical_pixels_at_fractional_display_scale() -> None:
    with hidden_overlay() as (_, _overlay, desktop):
        for kind, logical, physical, pressed in (
            (QtCore.QEvent.Type.MouseButtonPress, (800, 480), (1000, 600), Qt.MouseButton.LeftButton),
            (QtCore.QEvent.Type.MouseMove, (820, 500), (1025, 625), Qt.MouseButton.LeftButton),
            (QtCore.QEvent.Type.MouseButtonRelease, (820, 500), (1025, 625), Qt.MouseButton.NoButton),
        ):
            event = QtGui.QMouseEvent(kind, QtCore.QPointF(5, 5), QtCore.QPointF(*logical),
                                     Qt.MouseButton.LeftButton, pressed, Qt.KeyboardModifier.NoModifier)
            desktop.point = physical
            QtWidgets.QApplication.sendEvent(desktop.windows[1], event)
        assert desktop.position == (1025, 625)
        assert all(not window.isVisible() for window in desktop.windows)
        released = desktop.moves
        desktop.point = (1050, 650)
        event = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseMove, QtCore.QPointF(5, 5), QtCore.QPointF(840, 520),
                                 Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        QtWidgets.QApplication.sendEvent(desktop.windows[1], event)
        assert desktop.moves == released


def check_chord_feedback(overlay: KeymapOverlay, desktop: HiddenDesktop) -> None:
    canvas = desktop.canvas()
    desktop.now = 1.0
    normal_q, normal_m, normal_b = (key_style(canvas, name) for name in ("Q", "M", "B"))
    normal_n = key_style(canvas, "N")
    normal_space = key_style(canvas, "Space")
    items = tuple(canvas.boxes.items())
    overlay.set_pressed(frozenset({Q, M, AGENT, TALK}))
    pressed_q, pressed_m = key_style(canvas, "Q"), key_style(canvas, "M")
    assert pressed_q != normal_q and pressed_m != normal_m
    assert pressed_q == pressed_m  # both keys use the same contrasting feedback
    assert pressed_q[0] != pressed_q[1] == pressed_q[2] == pressed_q[3]
    assert key_style(canvas, "B") == normal_b
    assert key_style(canvas, "N") == pressed_q
    assert key_style(canvas, "Space") == pressed_q
    assert canvas.boxes["Space"].bottom() <= canvas.height()
    desktop.now = 2.0
    overlay.set_pressed(frozenset({M}))
    assert key_style(canvas, "Q") == normal_q
    assert key_style(canvas, "M") == pressed_m
    assert key_style(canvas, "N") == normal_n
    assert key_style(canvas, "Space") == normal_space
    overlay.set_pressed(frozenset())
    assert key_style(canvas, "M") == normal_m
    assert tuple(canvas.boxes.items()) == items


def check_feedback_across_layers(overlay: KeymapOverlay, desktop: HiddenDesktop) -> None:
    canvas = desktop.canvas()
    desktop.now = 1.0
    overlay.show(Layer.SYM, "SYM", WORK, visible=True)
    normal_q, normal_m = key_style(canvas, "Q"), key_style(canvas, "M")
    overlay.show(None, "BASE", WORK, visible=True)
    overlay.set_pressed(frozenset({Q, M}))
    gold = key_style(canvas, "M")
    desktop.now = 1.01
    overlay.set_pressed(frozenset({M}))
    overlay.show(Layer.SYM, "SYM", WORK, visible=True, pressed=frozenset({M}))
    assert key_style(canvas, "Q")[0] == gold[0]
    assert key_style(canvas, "M") == gold
    desktop.now = 1.121
    overlay.set_pressed(frozenset({M}))
    assert key_style(canvas, "Q") == normal_q
    assert key_style(canvas, "M") == gold
    overlay.set_pressed(frozenset())
    assert key_style(canvas, "M") == normal_m  # restores the blue layer indicator


def check_hiding_and_resetting(overlay: KeymapOverlay, desktop: HiddenDesktop) -> None:
    canvas = desktop.canvas()
    desktop.now = 1.0
    overlay.show(None, "BASE", WORK, visible=True)
    normal_q, normal_m = key_style(canvas, "Q"), key_style(canvas, "M")
    overlay.set_pressed(frozenset({Q}))
    gold = key_style(canvas, "Q")
    overlay.set_pressed(frozenset())
    assert key_style(canvas, "Q") == gold
    overlay.show(None, "BASE", WORK, visible=False)
    overlay.set_pressed(frozenset({Q, M}))  # state arriving while hidden must not replay old flashes
    overlay.show(None, "BASE", WORK, visible=True, pressed=frozenset({M}))
    assert key_style(canvas, "Q") == normal_q
    assert key_style(canvas, "M") == gold
    overlay.set_pressed(frozenset(), reset=True)
    assert key_style(canvas, "M") == normal_m


def test_overlay_renders_chords_flashes_layer_changes_and_resets() -> None:
    with hidden_overlay() as (root, overlay, desktop):
        canvas = desktop.canvas()
        check_chord_feedback(overlay, desktop)
        check_feedback_across_layers(overlay, desktop)
        check_hiding_and_resetting(overlay, desktop)
        desktop.now = None  # Exercise our timer wiring with actual elapsed time.
        normal = key_style(canvas, "Q")
        overlay.set_pressed(frozenset({Q}))
        overlay.set_pressed(frozenset())
        assert key_style(canvas, "Q") != normal
        QtCore.QTimer.singleShot(250, root.quit)
        root.exec()
        assert key_style(canvas, "Q") == normal
