"""Real notification windows, with controlled time and no microphone or key input."""

import ctypes
import math
import sys
import threading
import time
import unittest
from collections import deque
from collections.abc import Callable, Generator
from contextlib import contextmanager
from ctypes import wintypes
from itertools import pairwise
from typing import Protocol, cast

if sys.platform != "win32":
    raise unittest.SkipTest("Windows native agent notifications")

lazy import shiboken6
lazy from PySide6.QtCore import QPoint, Qt
lazy from PySide6.QtGui import QFont, QImage, QPainter, QRegion, QTextCursor
lazy from PySide6.QtTest import QTest
lazy from PySide6.QtWidgets import QWidget

from assistant.agent_session import Answer, Begin, Failed, Question, ReasoningSummary, Said, Session, StreamState, Succeeded, ToolActivity, transition
from assistant.agent_toasts import AgentToasts
from assistant.agent_window import AgentWindow
from assistant.communications import Command
from assistant.feed_desktop import NativeDesktop
from assistant.feed_triage import edited
from assistant.notifications import MAX_VISIBLE, WIDTH, Kind, MessageKey, Toast, TurnKey
from assistant.panel import PanelPreferences
from assistant.qt_runtime import prepare
from assistant.qt_text import TextView
from assistant.qt_ui import application
from assistant.recording_state import RecordingAction, RecordingState
from assistant.rich_text import formatted
from assistant.toast_card import Card
from tests.test_agent_session import asking
from winapi import appearance, screen, system, windows
from winapi.composition import DesktopComposition, Glass
from winapi.shapes import Rect

prepare()


class Desktop:
    __slots__ = ("bounds", "native", "pointer")

    def __init__(self) -> None:
        self.pointer: tuple[int, int] = (-100000, -100000)
        self.bounds: Rect | None = None
        self.native = NativeDesktop()

    def cursor_position(self) -> tuple[int, int]:
        return self.pointer

    def work_area(self, preferred: Rect | None) -> Rect:
        return self.bounds if self.bounds is not None else self.native.work_area(preferred)


class Notifications:
    __slots__ = (
        "_view",
        "agent",
        "animated",
        "choices",
        "choose_allowed",
        "commands",
        "create_card",
        "desktop",
        "dismiss_allowed",
        "jobs",
        "now",
        "preference",
        "recorded",
        "requested",
        "root",
        "timing",
    )

    def __init__(self, *, animated: bool, create_card: Callable[[AgentToasts, Toast, int], Card] = Card,
                 timing: appearance.TimerResolution | None = None) -> None:
        screen.use_physical_pixels()
        self.root = application()
        self.now = 100.0
        self.animated = animated
        self.desktop = Desktop()
        self.create_card, self.timing = create_card, timing
        self.preference: appearance.Preference = appearance.preference()
        # These observations belong to the fixture's concrete feed-action adapter.
        self.dismiss_allowed = self.choose_allowed = True
        self.choices: list[tuple[str, str, str]] = []
        self.commands: list[Command] = []
        self.jobs: deque[Callable[[], None]] = deque()
        self.requested = threading.Event()
        self.recorded: list[RecordingAction] = []
        self._view: AgentToasts | None = None
        self.agent = AgentWindow(
            self.stop, post=self.jobs.append, create_view=self.build,
            on_waiting=lambda waiting: self.requested.set() if waiting else None, on_recording=self.recorded.append,
            on_dismiss_work=self.dismiss, on_choose_work=self.choose, on_communication=self.communicate,
        )
        self.pump()
        assert self.agent.ready.is_set(), self.agent.all_text()

    @property
    def view(self) -> AgentToasts:
        assert self._view is not None
        return self._view

    def build(self, agent: AgentWindow) -> AgentToasts:
        self._view = AgentToasts(
            self.root, agent, preferences=PanelPreferences(Rect(30, 30, 430, 790)), remember=False,
            clock=lambda: self.now, motion_enabled=lambda: self.animated,
            desktop=self.desktop,
            create_card=self.create_card, timing=self.timing, material_preference=lambda: self.preference,
        )
        return self._view

    def dismiss(self, identity: str) -> bool:
        if not self.dismiss_allowed:
            return False
        self.agent.triage(edited(self.agent.state.triage, {'operation': 'dismiss', 'item': identity}))
        return True

    def choose(self, identity: str, revision: str, choice: str) -> bool:
        if not self.choose_allowed:
            return False
        self.choices.append((identity, revision, choice))
        return True

    def communicate(self, command: Command) -> bool:
        self.commands.append(command)
        return True

    def pump(self) -> None:
        while self.jobs:
            self.jobs.popleft()()
        self.root.processEvents()
        if self._view is not None and not self._view.closed:
            self._view.loop.pump()

    def advance(self, seconds: float) -> None:
        self.now += seconds
        self.view.refresh()
        self.view.tick()
        self.pump()

    def stop(self) -> None:
        self.agent.stopping()

    def close(self) -> None:
        self.agent.close()
        self.pump()
        self.root.processEvents()


@contextmanager
def notifications(*, animated: bool = False, create_card: Callable[[AgentToasts, Toast, int], Card] = Card,
                  timing: appearance.TimerResolution | None = None) -> Generator[Notifications]:
    # The user's actual pointer must not affect a deterministic expiry check.
    # Desktop observations enter through the view's explicit boundary.
    panel = Notifications(animated=animated, create_card=create_card, timing=timing)
    try:
        yield panel
    finally:
        panel.close()


def scroll_position(card: Card) -> int:
    return card.text.offset


def select(text: TextView, value: str) -> None:
    cursor = text.document().find(value)
    assert not cursor.isNull()
    text.setTextCursor(cursor)


def tail_visible(text: TextView) -> bool:
    cursor = QTextCursor(text.document())
    cursor.movePosition(QTextCursor.MoveOperation.End)
    bounds = text.cursorRect(cursor)
    return text.isVisible() and bounds.top() >= 0 and bounds.bottom() < text.viewport().height() + 1


def anchor(text: TextView) -> int:
    return text.cursorForPosition(QPoint(0, 1)).position()


def widget_rect(widget: QWidget) -> Rect:
    outer = windows.outer_rect(int(widget.window().winId()))
    point = widget.mapTo(widget.window(), QPoint(0, 0))
    scale = widget.devicePixelRatioF()
    left, top = outer.left + round(point.x() * scale), outer.top + round(point.y() * scale)
    return Rect(left, top, left + round(widget.width() * scale), top + round(widget.height() * scale))


def top(area: Rect) -> int:
    return area.top


class WindowAt(Protocol):
    argtypes: tuple[object, ...]
    restype: object

    def __call__(self, point: wintypes.POINT) -> int: ...


class WindowClass(Protocol):
    argtypes: tuple[object, ...]
    restype: object

    def __call__(self, handle: int, name: ctypes.Array[ctypes.c_wchar], count: int) -> int: ...


def test_long_reply_keeps_its_ending_scrolls_and_stays_until_read() -> None:
    with notifications(animated=True) as panel:
        text = "A useful detail. " * 170 + "\n\nThe final instruction is to save the workbook."
        panel.agent.say(text)
        panel.pump()
        panel.advance(.3)
        card = panel.view.cards[MessageKey(0)]
        assert card.text.toPlainText() == "".join(span.text for span in formatted(text))
        assert scroll_position(card) == 0
        panel.advance(31)
        assert panel.view.cards[MessageKey(0)] is card and scroll_position(card) > 0
        panel.advance(10000)
        assert tail_visible(card.text)
        panel.advance(31)
        panel.advance(.3)
        assert not panel.view.cards


def test_long_replies_take_turns_scrolling_instead_of_expiring_unread() -> None:
    with notifications(animated=True) as panel:
        panel.agent.say("First answer. " * 220)
        panel.agent.say("Second answer. " * 220)
        panel.pump()
        panel.advance(.3)
        first, second = panel.view.cards[MessageKey(0)], panel.view.cards[MessageKey(1)]
        panel.advance(31)
        assert scroll_position(first) > 0 and scroll_position(second) == 0
        assert not first.retiring and not second.retiring


def test_wheel_pauses_reading_and_streaming_preserves_the_chosen_position() -> None:
    with notifications(animated=True) as panel:
        panel.agent.begin("Read the notes", panel.stop)
        publish = panel.agent.updates()
        text = "A useful detail. " * 220
        publish(Answer("stream", text, 1))
        panel.pump()
        panel.advance(.3)
        panel.advance(31)
        card = panel.view.cards[TurnKey(0)]
        before = scroll_position(card)
        assert card.bounds is not None
        panel.desktop.pointer = (card.bounds.left + 8, card.bounds.top + 8)
        card.scroll_delta(120)
        panel.view.observe_pointer()
        panel.pump()
        assert scroll_position(card) < before and card.hovered
        position = anchor(card.text)
        panel.now += 20
        panel.view.tick()
        panel.pump()
        assert anchor(card.text) == position
        publish(Answer("stream", text + "\n\nMore details arrive.", 2))
        panel.pump()
        assert anchor(card.text) == position


def test_reduced_motion_keeps_the_whole_reply_and_advances_by_pages() -> None:
    with notifications() as panel:
        panel.agent.say("A useful detail. " * 220 + "\n\nThe end.")
        panel.pump()
        card = panel.view.cards[MessageKey(0)]
        assert scroll_position(card) == 0
        positions: list[int] = []
        for _ in range(20):
            panel.advance(1)
            positions.append(scroll_position(card))
        assert positions == sorted(positions) and len(set(positions)) < len(positions)
        panel.advance(10000)
        assert tail_visible(card.text) and "The end." in card.text.toPlainText()


def test_wheel_over_empty_glass_reaches_text_without_focusing_other_apps() -> None:
    with notifications() as panel:
        panel.agent.say("A useful detail. " * 220)
        panel.pump()
        card = panel.view.cards[MessageKey(0)]
        router = panel.view.wheel
        assert router.ready.wait(timeout=2) and router.active, router.error
        bounds = windows.outer_rect(card.handle)
        foreground = windows.foreground()
        assert not router.dispatch(bounds.left - 1, bounds.top, -120)
        assert router.dispatch(bounds.left + 2, bounds.top + 2, -120)
        deadline = time.monotonic() + 1
        while scroll_position(card) == 0 and time.monotonic() < deadline:
            panel.pump()
            time.sleep(.005)
        assert scroll_position(card) > 0 and windows.foreground() == foreground
        panel.view.show_history()
        panel.pump()
        assert panel.view.query.history
        panel.agent.close()
        panel.pump()
        assert router.thread is not None and not router.thread.is_alive() and not router.active


def test_compact_header_and_native_stop_padding_are_clickable_without_activation() -> None:
    with notifications() as panel:
        panel.preference = appearance.Material.GLASS
        panel.agent.begin("Check the notes", panel.stop)
        panel.pump()
        card = panel.view.cards[TurnKey(0)]
        bounds, stop = windows.outer_rect(card.handle), widget_rect(card.stop)
        assert bounds.width == card.width <= round(WIDTH * panel.view.scale)
        assert stop.width >= 28 and stop.height >= 28 and bounds.left < stop.left < stop.right < bounds.right
        foreground = windows.foreground()
        # Check the native window under the icon's padding, then send the click
        # to that HWND. This exercises Qt's actual child hit test and event path.
        point = wintypes.POINT(stop.left + 4, stop.top + 4)
        hit = cast(WindowAt, ctypes.WinDLL("user32").WindowFromPoint)
        hit.argtypes, hit.restype = (cast(object, wintypes.POINT),), ctypes.c_void_p
        deadline = time.monotonic() + 1
        while int(hit(point) or 0) != card.handle and time.monotonic() < deadline:
            panel.pump()
            time.sleep(.01)
        observed = int(hit(point) or 0)
        class_name = ctypes.create_unicode_buffer(256)
        window_class = cast(WindowClass, ctypes.WinDLL("user32").GetClassNameW)
        window_class.argtypes, window_class.restype = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int), ctypes.c_int
        window_class(observed, class_name, len(class_name))
        if (class_name.value == "LockScreenBackstopFrame"
                or (class_name.value == "Windows.UI.Core.CoreWindow" and windows.exe(observed) == "lockapp.exe")):
            # New Windows builds expose LockApp's CoreWindow instead of the older backstop frame.
            raise unittest.SkipTest("Windows is locked; the lock screen covers the native click target.")
        assert int(hit(point) or 0) == card.handle, (card.handle, int(hit(point) or 0), bounds, stop, card.alpha, card.window.isVisible())
        if card.layer is not None:
            for empty in (wintypes.POINT(bounds.left + 1, bounds.top + 1), wintypes.POINT(bounds.left - 8, bounds.top + 20)):
                assert int(hit(empty) or 0) not in (card.handle, card.layer.handle), "Rounded corners and shadows must pass clicks through."
        local = (point.x - bounds.left) | ((point.y - bounds.top) << 16)
        assert system.post_message(card.handle, 0x0201, 1, local)
        assert system.post_message(card.handle, 0x0202, 0, local)
        panel.pump()
        panel.pump()
        assert panel.agent.state.stopping and not card.stop.isEnabled()
        assert windows.foreground() == foreground


def test_stop_has_no_different_fill_in_normal_pressed_or_disabled_states() -> None:
    with notifications() as panel:
        panel.agent.begin("Check the notes", panel.stop)
        panel.pump()
        button = panel.view.cards[TurnKey(0)].stop
        for enabled, down in ((True, False), (True, True), (False, False)):
            button.setEnabled(enabled)
            button.setDown(down)
            image = QImage(button.size(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            button.render(painter, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
            painter.end()
            # The background is supplied only by the parent bubble, even while
            # pressed. The button paints its icon and optional focus outline.
            assert image.pixelColor(1, 1).alpha() <= 1


def test_background_material_sampling_never_waits_for_desktop_pixels() -> None:
    started, release = threading.Event(), threading.Event()
    bounds = Rect(10, 20, 300, 400)
    calls: list[tuple[Rect, ...]] = []

    def sample(rects: tuple[Rect, ...]) -> tuple[appearance.Backdrop, ...]:
        calls.append(rects)
        started.set()
        assert release.wait(2)
        return tuple(appearance.Backdrop(rect, appearance.Frost.LIGHT) for rect in rects)

    sampler = appearance.FrostSampler(sample)
    try:
        sampler.submit((bounds,))
        assert started.wait(1)
        assert sampler.read() == ()
        sampler.submit((Rect(0, 0, 500, 600),))
        assert calls == [(bounds,)]
        release.set()
        assert sampler.pending is not None
        sampler.pending.result(timeout=1)
        assert sampler.read() == (appearance.Backdrop(bounds, appearance.Frost.LIGHT),)
        assert sampler.read() == ()
    finally:
        release.set()
        sampler.close()


def test_material_modes_choose_readable_ink_and_reject_stale_backgrounds() -> None:
    dark = tuple(map(appearance.colorref, ("#181d2a", "#353c50")))
    assert appearance.frost_for(dark) is appearance.Frost.LIGHT
    assert appearance.frost_for((appearance.colorref("#fafbfe"),)) is appearance.Frost.BRIGHT
    assert appearance.frost_for((*dark, appearance.colorref("#ffffff"))) is appearance.Frost.SMOKED
    assert appearance.frost_for(()) is appearance.Frost.SMOKED
    with notifications() as panel:
        panel.preference = appearance.Material.GLASS
        panel.agent.say("The workbook is ready.")
        panel.pump()
        card = panel.view.cards[MessageKey(0)]
        if not card.glass:
            return
        assert card.bounds is not None
        select(card.text, "workbook")
        for frost, foreground in ((appearance.Frost.LIGHT, "#f6f3ff"), (appearance.Frost.BRIGHT, "#202435"),
                                  (appearance.Frost.SMOKED, "#f6f3ff")):
            card.match_background(appearance.Backdrop(card.bounds, frost), appearance.Material.GLASS)
            assert card.ink.foreground == foreground
            assert card.text.textCursor().selectedText() == "workbook"
        card.match_background(appearance.Backdrop(Rect(0, 0, 1, 1), appearance.Frost.BRIGHT), appearance.Material.GLASS)
        assert card.frost is appearance.Frost.SMOKED
        assert card.text.toPlainText() == "The workbook is ready."


def test_material_changes_preserve_the_native_scroll_range_and_reading_position() -> None:
    with notifications() as panel:
        panel.agent.say("A useful detail. " * 220 + "\n\nThe end.")
        panel.pump()
        card = panel.view.cards[MessageKey(0)]
        assert card.bounds is not None
        card.scroll_delta(-480)
        panel.pump()
        position, original = scroll_position(card), anchor(card.text)
        assert position > 0
        for frost in (appearance.Frost.LIGHT, appearance.Frost.SMOKED, appearance.Frost.BRIGHT) * 3:
            card.frost = frost
            assert card.content is not None
            card.apply_style(card.content, appearance.Material.GLASS)
            panel.pump()
            assert scroll_position(card) == position and anchor(card.text) == original
            scroll = card.text.verticalScrollBar()
            assert 0 <= scroll.value() <= scroll.maximum()


def test_one_bubble_keeps_its_result_when_finished_and_when_steps_collapse() -> None:
    with notifications() as panel:
        panel.agent.begin("Read the workbook", panel.stop)
        panel.pump()
        card = panel.view.cards[TurnKey(0)]
        handle, text = card.handle, card.text
        publish = panel.agent.updates()
        publish(ToolActivity("read", "read_file", '{"path":"budget.xlsx"}', 1, Succeeded('{"rows":24}')))
        publish(ToolActivity("check", "read_file", "forecast.xlsx", 2, Succeeded("The totals match.")))
        publish(Answer("answer", "The workbook is **ready**.", 3, StreamState.COMPLETE))
        panel.pump()
        assert len(panel.view.cards) == 1 and panel.view.cards[TurnKey(0)] is card
        assert card.details.isVisible() and card.text.toPlainText() == "The workbook is ready."
        assert 'forecast.xlsx' in card.details.toPlainText() and 'budget.xlsx' not in card.details.toPlainText()
        compact, stop = windows.outer_rect(handle), widget_rect(card.stop)
        card.disclosure.click()
        panel.pump()
        expanded = windows.outer_rect(handle)
        assert card.expanded and expanded.height > compact.height
        steps = card.details.toPlainText()
        assert "Path: budget.xlsx" in steps and "Rows: 24" in steps
        assert steps.index("budget.xlsx") < steps.index("forecast.xlsx")
        assert card.details.geometry().bottom() < card.text.y()
        assert widget_rect(card.stop).right == stop.right
        panel.agent.finish()
        panel.pump()
        assert panel.view.cards[TurnKey(0)] is card and card.handle == handle
        assert card.stop.isHidden() and card.text.document().find("ready").charFormat().fontWeight() >= QFont.Weight.DemiBold
        card.disclosure.click()
        panel.pump()
        assert not bool(card.expanded) and card.details.isVisible()
        assert card.text is text and card.text.toPlainText() == "The workbook is ready." and tail_visible(card.text)
        assert windows.outer_rect(handle).height < expanded.height


def test_reversing_disclosure_preserves_selection_and_visible_attached_result() -> None:
    with notifications(animated=True) as panel:
        panel.agent.begin("Check the workbook", panel.stop)
        publish = panel.agent.updates()
        for index in range(4):
            publish(ToolActivity(str(index), "read_file", f"sheet-{index}.xlsx", index + 1, Succeeded("Read 24 rows.")))
        answer = "The result stays attached while you open and close the steps."
        publish(Answer("answer", answer, 5, StreamState.COMPLETE))
        panel.agent.finish()
        panel.pump()
        panel.advance(.3)
        card = panel.view.cards[TurnKey(0)]
        select(card.text, "result")
        before = windows.outer_rect(card.handle)
        card.disclosure.click()
        panel.pump()
        assert windows.outer_rect(card.handle) == before
        assert card.motion is not None and card.motion.end.details > 0
        for _ in range(5):
            panel.now += .016
            panel.view.tick()
            panel.pump()
            assert card.text.toPlainText() == answer and card.text.height() > 20
            if card.details.isVisible():
                assert card.details.geometry().bottom() < card.text.y()
        current = windows.outer_rect(card.handle)
        card.disclosure.click()
        panel.pump()
        assert windows.outer_rect(card.handle) == current
        panel.advance(.3)
        assert not bool(card.motion) and card.frame.details > 0 and card.details.isVisible()
        assert 'sheet-3.xlsx' in card.details.toPlainText() and 'sheet-0.xlsx' not in card.details.toPlainText()
        assert card.text.textCursor().selectedText() == "result" and tail_visible(card.text)


def test_long_steps_scroll_independently_and_keep_the_result_on_reopen() -> None:
    with notifications() as panel:
        panel.agent.begin("Check the workbooks", panel.stop)
        publish = panel.agent.updates()
        for index in range(15):
            publish(ToolActivity(str(index), "read_file", f"sheet-{index}.xlsx", index + 1, Succeeded("Read 24 rows.")))
        publish(Answer("answer", "All fifteen sheets match.", 20, StreamState.COMPLETE))
        panel.agent.finish()
        panel.pump()
        card = panel.view.cards[TurnKey(0)]
        card.toggle(animate=False)
        panel.pump()
        assert card.details.toPlainText().count("Read file") == 15 and card.details.verticalScrollBar().maximum() > 0
        reply = anchor(card.text)
        card.scroll_details(-240)
        panel.pump()
        position = card.details.offset
        assert position > 0 and anchor(card.text) == reply and tail_visible(card.text)
        assert any(region.target == id(card.details) for region in panel.view.wheel.regions)
        card.toggle(animate=False)
        panel.pump()
        assert not panel.view.wheel.regions and card.text.toPlainText() == "All fifteen sheets match."
        card.toggle(animate=False)
        panel.pump()
        assert card.details.offset == position and anchor(card.text) == reply


def test_keyboard_disclosure_is_immediate_and_keeps_the_result_attached() -> None:
    with notifications(animated=True) as panel:
        panel.agent.begin("Read the workbook", panel.stop)
        publish = panel.agent.updates()
        publish(ToolActivity("read", "read_file", "budget.xlsx", 1, Succeeded("24 rows")))
        publish(Answer("reply", "The workbook is ready.", 2, StreamState.COMPLETE))
        panel.pump()
        panel.advance(.3)
        card = panel.view.cards[TurnKey(0)]
        for key, expanded in ((Qt.Key.Key_Return, True), (Qt.Key.Key_Space, False)):
            QTest.keyClick(card.disclosure, key)
            panel.pump()
            assert card.expanded is expanded and card.motion is None
            assert card.text.toPlainText() == "The workbook is ready." and tail_visible(card.text)


def test_long_result_keeps_its_reading_position_while_steps_open_and_close() -> None:
    with notifications() as panel:
        panel.agent.begin("Read the workbook", panel.stop)
        publish = panel.agent.updates()
        publish(ToolActivity("read", "read_file", "budget.xlsx", 1, Succeeded("24 rows")))
        publish(Answer("reply", "A useful detail. " * 220, 2, StreamState.COMPLETE))
        panel.agent.finish()
        panel.pump()
        card = panel.view.cards[TurnKey(0)]
        card.scroll_delta(-240)
        panel.pump()
        position, first = card.text.offset, anchor(card.text)
        assert position > 0
        for _ in range(4):
            card.toggle(animate=False)
            panel.pump()
            assert card.text.offset == position and anchor(card.text) == first


def test_native_shadow_follows_the_foreground_after_fractional_dpi_rounding() -> None:
    with notifications(animated=True) as panel:
        panel.agent.say("Ready.")
        panel.pump()
        panel.advance(.3)
        card = panel.view.cards[MessageKey(0)]
        if card.layer is None:
            return
        panel.view.render(transition(Session(identity=panel.agent.state.identity), Said("Ready to review the plan.", 1)))
        panel.pump()
        for _ in range(18):
            panel.now += .016
            panel.view.tick()
            panel.pump()
            bounds = windows.outer_rect(card.handle)
            padding = round(28 * panel.view.scale)
            assert card.bounds == bounds
            surface = card.surface_bounds
            assert surface.right == bounds.right and surface.bottom == bounds.bottom
            assert card.layer.bounds == Rect(surface.left - padding, surface.top - padding, surface.right + padding, surface.bottom + padding)


def test_replies_keep_the_feed_width_and_grow_vertically_as_text_wraps() -> None:
    # Defect: standalone replies retain the retired text-sized bubble width.
    with notifications() as panel:
        sizes: list[tuple[int, int]] = []
        for text in ("Ready.", "Ready to review.", "Ready to review the plan.", "Ready to review the plan. " * 4):
            panel.view.render(transition(Session(identity="width-probe"), Said(text, 1)))
            panel.pump()
            card = panel.view.cards[MessageKey(0)]
            sizes.append((card.width, card.height))
            assert windows.outer_rect(card.handle).width == card.width and tail_visible(card.text)
        cap = round(WIDTH * panel.view.scale)
        assert all(width == cap for width, _height in sizes)
        assert sizes[0][1] == sizes[1][1] == sizes[2][1] < sizes[3][1]


def test_feed_wraps_markdown_and_long_words_inside_its_fixed_width() -> None:
    # Defect: our viewport/wrapping configuration lets text escape the feed column.
    with notifications() as panel:
        widths: list[int] = []
        for text in ("## A heading\n\n**Ready**\n\n- OK", "[Docs](https://example.org/" + "a" * 160 + ")", "W" * 80):
            panel.view.render(transition(Session(identity="width-probe"), Said(text, 1)))
            panel.pump()
            card = panel.view.cards[MessageKey(0)]
            widths.append(card.width)
            block = card.text.document().begin()
            while block.isValid():
                layout = block.layout()
                for index in range(layout.lineCount()):
                    line = layout.lineAt(index)
                    assert line.x() + line.naturalTextWidth() <= card.text.width() + 1
                block = block.next()
        assert widths == [round(WIDTH * panel.view.scale)] * 3


def test_reply_height_changes_retarget_from_current_bounds_with_right_edge_anchored() -> None:
    # Defect: growing/shrinking content jumps to its target or moves the feed edge.
    with notifications(animated=True) as panel:
        panel.view.render(transition(Session(identity="width-probe"), Said("Ready.", 1)))
        panel.pump()
        panel.advance(.3)
        card = panel.view.cards[MessageKey(0)]
        right = windows.outer_rect(card.handle).right
        for text in ("Ready to review the plan. " * 40, "**Done.**"):
            before = windows.outer_rect(card.handle)
            panel.view.render(transition(Session(identity="width-probe"), Said(text, 1)))
            panel.pump()
            assert windows.outer_rect(card.handle) == before
            heights: list[int] = []
            for _ in range(4):
                panel.now += .016
                panel.view.tick()
                panel.pump()
                bounds = windows.outer_rect(card.handle)
                # Qt maps integer logical pixels to physical pixels at 125%.
                assert abs(bounds.right - right) <= 1
                assert abs(bounds.width - card.width) <= 1
                assert min(before.height, card.height) - 1 <= bounds.height <= max(before.height, card.height) + 1
                heights.append(bounds.height)
            assert len(set(heights)) > 1
        panel.advance(.3)
        assert abs(windows.outer_rect(card.handle).height - card.height) <= 1 and card.motion is None


def test_narrow_work_area_keeps_complete_question_lines_with_voice_tooltip() -> None:
    with notifications() as panel:
        panel.desktop.bounds = Rect(40, 40, 290, 600)
        state = transition(Session(identity="narrow-area"), Begin("Check the notes", 1))
        state = transition(state, Question("question", "Which workbook should I use?", "Please say the filename.", 2))
        panel.view.render(state)
        panel.pump()
        for card in panel.view.cards.values():
            assert abs(windows.outer_rect(card.handle).width - card.width) <= 1
            assert card.width <= 250 - 2 * round(16 * panel.view.scale)
        question = panel.view.cards[TurnKey(0)]
        assert question.text.isReadOnly() and question.hint.isHidden()
        assert "agent voice-to-text button" in question.window.toolTip()
        assert question.window.rect().contains(question.text.geometry())
        assert tail_visible(question.text)


def test_streaming_never_resizes_a_visible_card_for_measurement() -> None:
    # This fixture owns native movement observations while retaining real cards.
    handles: set[int] = set()
    moves: list[tuple[int, Rect]] = []
    def move(handle: int, bounds: Rect) -> None:
        if handle in handles:
            moves.append((handle, bounds))
        windows.move(handle, bounds)
    def create(owner: AgentToasts, toast: Toast, width: int) -> Card:
        return Card(owner, toast, width, move=move)
    with notifications(animated=True, create_card=create) as panel:
        panel.agent.begin("Read the notes", panel.stop)
        publish = panel.agent.updates()
        publish(Answer("stream", "A short answer.", 1))
        panel.pump()
        panel.advance(.3)
        handles.update(card.handle for card in panel.view.cards.values())
        before = {handle: windows.outer_rect(handle) for handle in handles}
        publish(Answer("stream", "A short answer. " * 70, 2))
        panel.pump()
        assert all(bounds == before[handle] for handle, bounds in moves)


def test_stream_growth_moves_neighbors_together_without_overlap() -> None:
    with notifications(animated=True) as panel:
        panel.agent.say("Earlier context. " * 25)
        panel.agent.begin("Summarize the notes", panel.stop)
        publish = panel.agent.updates()
        text = "The summary follows."
        publish(Answer("stream", text, 1))
        panel.pump()
        panel.advance(.3)
        for index in range(40):
            panel.now += .016
            panel.view.tick()
            panel.pump()
            if index in (0, 2, 5, 8, 12):
                text += "\n\nA **formatted** finding with more detail. " * 2
                publish(Answer("stream", text, 2))
                panel.pump()
            bounds = sorted((windows.outer_rect(card.handle) for card in panel.view.cards.values()), key=top)
            assert all(first.bottom < second.top for first, second in pairwise(bounds))
            assert panel.view.work is not None and bounds[0].top >= panel.view.work.top and bounds[-1].bottom < panel.view.work.bottom
        assert all(card.motion is None for card in panel.view.cards.values())


def test_streaming_unicode_and_closing_markup_preserve_the_unchanged_selection() -> None:
    with notifications() as panel:
        panel.agent.begin("Summarize the notes", panel.stop)
        publish = panel.agent.updates()
        prefix = "Åäö 👩🏽‍💻 e\u0301: "
        publish(Answer("stream", prefix + "**bold", 1))
        panel.pump()
        card = panel.view.cards[TurnKey(0)]
        select(card.text, "👩🏽‍💻")
        for suffix in ("**bold**", "**bold** and [docs](https://example.org", "**bold** and [docs](https://example.org).",
                       "**bold** and [docs](https://example.org).\n\n```python\nprint('ok')"):
            text = prefix + suffix
            publish(Answer("stream", text, 2))
            panel.pump()
            assert card.text.toPlainText() == "".join(span.text for span in formatted(text))
            assert card.text.textCursor().selectedText() == "👩🏽‍💻"
        assert card.text.document().find("bold").charFormat().fontWeight() >= QFont.Weight.DemiBold
        assert card.text.document().find("docs").charFormat().anchorHref() == "https://example.org"


def test_streaming_reveals_only_new_text_and_releases_animation_timing() -> None:
    with notifications(animated=True) as panel:
        panel.agent.begin("Summarize the notes", panel.stop)
        publish = panel.agent.updates()
        publish(Answer("stream", "First.", 1))
        panel.pump()
        panel.advance(.3)
        reply = panel.view.cards[TurnKey(0)]
        for index in range(30):
            publish(Answer("stream", "First." + " a" * (index + 1), 2))
            panel.pump()
            assert all(selection.cursor.selectionStart() >= 6 for selection in reply.text.extraSelections())
            assert len(reply.text.extraSelections()) <= 12
        assert reply.text.extraSelections()
        final = "First." + " a" * 30
        publish(Answer("stream", final, 3, StreamState.COMPLETE))
        panel.agent.done(final)
        panel.agent.finish()
        panel.pump()
        panel.advance(.3)
        assert reply.text.toPlainText() == final and not reply.text.extraSelections()
        assert panel.view.animation_timer is None and not panel.view.timing.active


class Period:
    """The fixture owns observations of balanced native timer requests."""

    def __init__(self) -> None:
        self.calls: tuple[str, ...] = ()

    def request(self) -> bool:
        self.calls = (*self.calls, "begin")
        return True

    def release(self) -> None:
        self.calls = (*self.calls, "end")


def test_motion_timing_is_balanced_on_reduced_motion_history_and_close() -> None:
    period = Period()
    with notifications(animated=True, timing=appearance.TimerResolution(period)) as panel:
        panel.agent.begin("Read the notes", panel.stop)
        panel.pump()
        assert (panel.view.timing.active, period.calls) == (True, ("begin",))
        panel.animated = False
        panel.advance(.016)
        assert (panel.view.timing.active, period.calls) == (False, ("begin", "end"))
        panel.animated = True
        panel.agent.say("A reply.")
        panel.pump()
        assert panel.view.timing.active
        panel.view.clear_cards()
        assert not bool(panel.view.timing.active)
        panel.view.refresh()
        panel.pump()
        assert panel.view.timing.active
    assert period.calls == ("begin", "end") * 3


def test_measured_previews_end_on_complete_lines_with_mixed_markdown_fonts() -> None:
    with notifications() as panel:
        document = panel.view.measure.body
        for source in ("A wrapped paragraph with Åäö and 👩🏽‍💻. " * 12,
                       "# Heading\n\nA **bold** paragraph.\n\n- An item that wraps across several lines in a narrow preview.\n"
                       "- Another item.\n\n```python\nprint('hello')\n```\n\nEnd."):
            wanted = document.load(tuple(formatted(source)), 260)
            boundaries = [0, math.ceil(wanted)]
            block = document.qt.begin()
            while block.isValid():
                layout = block.layout()
                top = document.qt.documentLayout().blockBoundingRect(block).top()
                for index in range(layout.lineCount()):
                    line = layout.lineAt(index)
                    boundaries.append(math.ceil(top + line.y() + line.height()))
                block = block.next()
            for available in range(1, min(math.ceil(wanted) + 1, 500)):
                fitted = document.fit(available)
                assert fitted in boundaries and fitted <= available


def test_notifications_are_idle_until_needed_and_leave_focus_untouched() -> None:
    with notifications() as panel:
        view = panel.view
        assert not view.cards and not view.loop.timer.isActive()
        foreground = windows.foreground()
        panel.agent.begin("Find my workbook", panel.stop)
        panel.pump()
        work = view.cards[TurnKey(0)]
        assert windows.is_visible(work.handle) and work.stop.isVisible()
        assert work.dismiss.isVisible() and work.text.isHidden()
        publish = panel.agent.updates()
        publish(ReasoningSummary("thought", "Checking **recent files**.", 1))
        panel.pump()
        assert view.cards[TurnKey(0)] is work and work.text.toPlainText() == ""
        panel.advance(3600)
        publish(Answer("reply", "Found **budget.xlsx**.", 2, StreamState.COMPLETE))
        panel.agent.done("Found **budget.xlsx**.")
        panel.agent.finish()
        panel.pump()
        assert view.cards[TurnKey(0)] is work and len(view.cards) == 1 and work.stop.isHidden()
        assert work.height <= work.maximum and tail_visible(work.text)
        assert not work.text.textCursor().hasSelection()
        panel.advance(31)
        assert not view.cards and view.expiry_timer is None and not view.loop.timer.isActive()
        panel.agent.show()
        panel.pump()
        assert not view.cards
        assert "Found **budget.xlsx**." in panel.agent.all_text() and windows.foreground() == foreground


def test_stack_is_bounded_during_bursts_and_retains_retired_native_layers() -> None:
    with notifications(animated=True) as panel:
        old_handles: list[int] = []
        for index in range(12):
            panel.agent.say(f"Reply {index} with **Markdown**.")
            panel.pump()
            old_handles.extend(card.layer.handle for card in panel.view.cards.values() if card.layer is not None)
            assert len(panel.view.cards) <= MAX_VISIBLE
            assert len(panel.view.cards) + len(panel.view.spares) <= MAX_VISIBLE
        panel.advance(.5)
        assert all(card.motion is None for card in panel.view.cards.values())
        bounds = sorted((windows.outer_rect(card.handle) for card in panel.view.cards.values()), key=top)
        assert panel.view.work is not None and bounds[0].top >= panel.view.work.top and bounds[-1].bottom < panel.view.work.bottom
        assert all(first.bottom < second.top for first, second in pairwise(bounds))
        panel.advance(31)
        panel.advance(.3)
        assert not panel.view.cards and all(windows.exists(handle) and not windows.is_visible(handle) for handle in old_handles)
        panel.agent.close()
        panel.pump()
        assert all(not windows.exists(handle) for handle in old_handles)


def test_repeating_a_frame_keeps_native_geometry_stable_after_dpi_rounding() -> None:
    moves: list[tuple[int, Rect]] = []
    def move(handle: int, bounds: Rect) -> None:
        moves.append((handle, bounds))
        windows.move(handle, bounds)
    def create(owner: AgentToasts, toast: Toast, width: int) -> Card:
        return Card(owner, toast, width, move=move)
    with notifications(animated=True, create_card=create) as panel:
        panel.agent.say("Reply with **Markdown**.")
        panel.pump()
        card = panel.view.cards[MessageKey(0)]
        bounds = windows.outer_rect(card.handle)
        moves.clear()
        for _ in range(3):
            card.position(card.right, card.frame)
            panel.view.loop.pump()
        assert not moves and windows.outer_rect(card.handle) == bounds


def test_spinner_reuses_widgets_and_stops_timers_for_reduced_motion_and_input() -> None:
    with notifications(animated=True) as panel:
        panel.agent.begin("Find **the workbook**", panel.stop)
        panel.pump()
        panel.advance(.3)
        work = panel.view.cards[TurnKey(0)]
        widgets, angle = work.window.findChildren(QWidget), work.spin_angle
        panel.now += .1
        panel.view.tick()
        panel.pump()
        assert work.spin_angle != angle and work.window.findChildren(QWidget) == widgets
        panel.animated = False
        panel.view.tick()
        assert panel.view.animation_timer is None
        panel.animated = True
        with asking(panel.agent.inputs, question=True) as pending:
            assert panel.requested.wait(timeout=2)
            panel.pump()
            panel.advance(.3)
            assert panel.view.animation_timer is None
            assert panel.agent.reply_by_voice("The workbook on my desktop")
            assert pending.result() == "The workbook on my desktop"
        panel.agent.finish()
        panel.pump()
        panel.advance(.3)
        assert panel.view.animation_timer is None and panel.view.cards


def test_solid_and_high_contrast_materials_keep_all_content_readable() -> None:
    def unavailable(composition: DesktopComposition) -> Glass:
        raise OSError("Unavailable")
    def create(owner: AgentToasts, toast: Toast, width: int) -> Card:
        return Card(owner, toast, width, glass=unavailable)
    with notifications(create_card=create) as panel:
        panel.preference = appearance.Material.SOLID
        panel.agent.begin("Read the workbook", panel.stop)
        panel.pump()
        work = panel.view.cards[TurnKey(0)]
        assert not work.glass and work.dismiss.isVisible()
        publish = panel.agent.updates()
        publish(ToolActivity("tool", "read_file", "budget.xlsx", 1, Failed("Missing file")))
        panel.pump()
        work.toggle(animate=False)
        panel.pump()
        assert "Missing file" in work.details.toPlainText()
        panel.preference = appearance.Material.GLASS
        panel.view.refresh()
        panel.pump()
        assert not work.glass and work.details.isVisible()
        panel.preference = appearance.Contrast("#ffffff", "#000000")
        panel.view.refresh()
        panel.pump()
        assert not work.glass and work.colors.surface == "#ffffff"
        assert work.ink.foreground == work.ink.secondary == "#000000"
        color = work.details.calls[0].status.grab().toImage().pixelColor(8, 8)
        assert color.name() == "#000000" and color.alpha() > 0


def test_hovering_glass_pauses_expiry_and_close_cancels_all_observation() -> None:
    with notifications() as panel:
        panel.agent.say("A reply to read.")
        panel.pump()
        card = next(iter(panel.view.cards.values()))
        bounds = windows.outer_rect(card.handle)
        assert panel.view.pointer_timer is not None
        panel.now += 5
        panel.desktop.pointer = (bounds.right - 12, bounds.bottom - 12)
        panel.view.observe_pointer()
        assert panel.view.expiry_timer is None
        panel.advance(100)
        assert card.key in panel.view.cards
        panel.desktop.pointer = (-100000, -100000)
        panel.view.observe_pointer()
        panel.advance(6)
        assert card.key in panel.view.cards
        panel.advance(2)
        assert not panel.view.cards and not bool(panel.view.pointer_timer)
        panel.agent.say("Another reply.")
        panel.pump()
        panel.agent.close()
        panel.pump()
        assert not bool(panel.view.pointer_timer) and panel.view.loop.closed and not shiboken6.isValid(panel.view.loop.timer)


def test_questions_can_be_answered_or_stopped_by_voice_without_history() -> None:
    with notifications() as panel:
        panel.agent.begin("Open the workbook", panel.stop)
        with asking(panel.agent.inputs, question=True) as pending:
            assert panel.requested.wait(timeout=2)
            panel.pump()
            panel.advance(3600)
            question = panel.view.cards[TurnKey(0)]
            assert "agent voice-to-text button" in question.window.toolTip()
            assert "Open this?" in question.text.toPlainText()
            assert panel.agent.reply_by_voice("The revenue sheet.")
            assert pending.result() == "The revenue sheet."
        panel.pump()
        assert panel.view.cards[TurnKey(0)] is question
        assert "The revenue sheet." in question.text.toPlainText() and "Open this?" in question.text.toPlainText()
        panel.requested.clear()
        with asking(panel.agent.inputs) as pending:
            assert panel.requested.wait(timeout=2)
            panel.pump()
            approval = panel.view.cards[TurnKey(0)]
            assert [button.text() for button in approval.choices] == ["Approve", "Decline"]
            approval.stop.click()
            assert pending.result() is None
        panel.pump()
        assert not approval.stop.isEnabled()


def test_history_uses_the_existing_feed_and_returns_to_current_work() -> None:
    with notifications() as panel:
        panel.agent.say('An earlier result worth retaining.')
        panel.pump()
        panel.advance(10000)
        assert not panel.view.cards
        panel.view.show_history()
        panel.pump()
        assert panel.view.query.history and panel.view.cards
        assert any('An earlier result worth retaining.' in card.text.toPlainText() for card in panel.view.cards.values())
        panel.view.resume()
        panel.pump()
        assert not panel.view.query.history


def test_recording_stop_is_independent_and_shutdown_closes_every_native_layer() -> None:
    with notifications(animated=True) as panel:
        panel.agent.begin("Find the workbook", panel.stop)
        panel.agent.recording(RecordingState(phase="recording", identity="meeting", seconds=3723, preview="**00:00:00**  First sentence."))
        panel.pump()
        recording = panel.view.cards[Kind.RECORDING]
        assert "01:02:03" in recording.label.text()
        recording.stop.click()
        assert panel.recorded == ["stop"] and not panel.agent.state.stopping
        handles: list[int] = []
        for card in panel.view.cards.values():
            handles.append(card.handle)
            if card.layer is not None:
                handles.append(card.layer.handle)
        panel.agent.close()
        panel.pump()
        assert panel.agent.closed_ready.is_set() and not panel.view.cards
        assert panel.view.animation_timer is None and panel.view.expiry_timer is None and not shiboken6.isValid(panel.view.loop.timer)
        assert all(not windows.exists(handle) for handle in handles)


def test_recording_preview_keeps_the_latest_transcript_visible() -> None:
    with notifications() as panel:
        preview = "**00:00:00**  " + "An earlier sentence. " * 150 + "\n\n**00:15:00**  The newest sentence."
        panel.agent.recording(RecordingState(phase="recording", identity="meeting", seconds=900, preview=preview))
        panel.pump()
        card = panel.view.cards[Kind.RECORDING]
        assert "The newest sentence." in card.text.toPlainText() and tail_visible(card.text)


def test_new_recording_interrupts_dismissal_and_follows_work_area_changes() -> None:
    with notifications(animated=True) as panel:
        panel.agent.recording(RecordingState(phase="saved", identity="first", preview="Saved transcript."))
        panel.pump()
        panel.advance(.3)
        card = panel.view.cards[Kind.RECORDING]
        panel.advance(31)
        assert all(item.retiring for item in panel.view.cards.values())
        panel.now += .08
        assert card.motion is not None and 0 < card.motion.sample(panel.now).alpha < 1
        panel.agent.recording(RecordingState(phase="recording", identity="second", preview="New transcript."))
        panel.pump()
        assert panel.view.cards[Kind.RECORDING] is card and not card.retiring
        assert not bool(card.motion) and card.alpha == 1
        panel.advance(.3)
        assert panel.view.work is not None
        work = panel.view.work
        before = windows.outer_rect(card.handle)
        panel.desktop.bounds = Rect(work.left + 30, work.top, work.right - 30, work.bottom)
        panel.view.refresh()
        panel.pump()
        after = windows.outer_rect(card.handle)
        # The feed anchors its lower-right edge; narrower text can change height.
        # Fractional DPI can round the requested native edge by one pixel.
        assert abs(after.right - (before.right - 30)) <= 1 and abs(after.bottom - before.bottom) <= 1, (before, after)


def test_wrapped_text_and_scroll_indicator_stay_inside_the_visible_card_while_it_resizes() -> None:
    with notifications(animated=True) as panel:
        panel.agent.say('Ready.')
        panel.pump()
        panel.advance(.3)
        panel.view.render(transition(Session(identity=panel.agent.state.identity), Said(
            'Please compare the forecast before replying. ' * 100, 1)))
        panel.pump()
        overflow_seen = False
        for _ in range(20):
            panel.now += .016
            panel.view.tick()
            panel.pump()
            card = panel.view.cards[MessageKey(0)]
            view = card.text
            assert view.x() + view.width() <= card.window.width() - 12, (
                view.geometry(), card.window.size(), card.frame.width)
            assert view.document().textWidth() <= view.viewport().width() + 1, (
                view.document().textWidth(), view.viewport().size())
            assert view.viewport().width() == view.width()  # The hidden native scrollbar must consume no text space.
            if view.verticalScrollBar().maximum():
                overflow_seen = True
                assert not view.verticalScrollBar().isVisible()
                assert view.x() + view.width() < card.window.width() - 7  # Two-pixel painted indicator stays outside.
            block = view.document().begin()
            while block.isValid():
                layout = block.layout()
                for index in range(layout.lineCount()):
                    line = layout.lineAt(index)
                    assert line.x() + line.naturalTextWidth() <= view.viewport().width() + 1
                block = block.next()
        assert overflow_seen
