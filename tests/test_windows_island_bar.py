"""The island bar through real Qt windows: what shows, where it sits, and what a press does."""

import sys
import threading
import time
import unittest
from collections.abc import Callable
from datetime import datetime

if sys.platform != "win32":
    raise unittest.SkipTest("Windows island bar")

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtTest import QTest

from assistant.desktop_bar import BarActions, BarObservations, DesktopBar
from assistant.island_menu import Menu
from assistant.island_model import Agent, Job, Key
from assistant.island_surface import SHADOW, TOP, ControlButton, MenuRow
from assistant.qt_runtime import prepare
from assistant.qt_ui import EventLoop, application
from assistant.recording_state import RecordingState
from protocol import Tool
from tests.native_pointer import foreign_pointer
from winapi import appearance, windows
from winapi.machine_status import Battery

prepare()

WORKING = Agent("Comparing both sheets", waiting=False)


def rest(bar: DesktopBar) -> None:
    bar.dictation(active=False)
    bar.job_changed(None)
    bar.agent_changed(None)


def recorded(invoked: list[str], *, tools: list[tuple[Tool, int]] | None = None) -> BarActions:
    return BarActions(
        lambda: invoked.append("feed"),
        lambda: invoked.append("canvas"),
        lambda: invoked.append("stop"),
        lambda action: invoked.append("record-" + action),
        lambda: invoked.append("keymap"),
        lambda: invoked.append("overlay"),
        lambda: invoked.append("controls"),
        lambda message: invoked.append("problem: " + message),
        (lambda tool, hwnd: tools.append((tool, hwnd))) if tools is not None else (lambda tool, hwnd: None),
        inbox=lambda: invoked.append("inbox"),
    )


def shown(bar: DesktopBar) -> list[Key]:
    return [key for key in Key if (capsule := bar.window.capsules.get(key)) is not None and capsule.isVisibleTo(bar.window)]


def press(bar: DesktopBar, key: Key) -> None:
    QTest.mouseClick(bar.window.capsules[key], QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(10, TOP + 17))


def stop_button(bar: DesktopBar, key: Key) -> ControlButton:
    return next(button for button in bar.window.capsules[key].controls if button.control.icon == "stop")


def sampled(app: QtWidgets.QApplication, bar: DesktopBar, reached: Callable[[], bool]) -> None:
    """Sample the microphone until the trace reaches a state; the meter reads off Qt's thread."""
    deadline = time.monotonic() + 1
    while not reached() and time.monotonic() < deadline:
        bar.sample_audio()
        app.processEvents()
        time.sleep(0.005)
    assert reached(), "The microphone level did not reach the trace."


def remember(focused: list[int], hwnd: int) -> bool:
    focused.append(hwnd)
    return True


def menu(bar: DesktopBar) -> Menu | None:
    """The open menu, read fresh: the bar changes it between steps."""
    return bar.expanded


def menu_row(bar: DesktopBar, label: str) -> MenuRow:
    return next(row for row in bar.window.capsules[Key.ISLAND].rows if row.accessibleName().split(" · ")[0] == label)


def closed(app: QtWidgets.QApplication, bar: DesktopBar) -> None:
    bar.close()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()


def test_the_island_rests_alone_and_each_capsule_acts_on_what_it_shows() -> None:
    # Defects: persistent controls return beside the island, a capsule's press runs
    # another function, a stoppable activity hides its Stop, or a finished
    # activity leaves its capsule behind.
    app = application()
    invoked: list[str] = []
    observations = BarObservations(power=lambda: Battery(73, powered=False, charging=False), local_time=lambda: datetime(2026, 10, 30, 20, 59))
    bar = DesktopBar(recorded(invoked), native_shell=False, observations=observations)
    try:
        assert shown(bar) == [Key.ISLAND]
        island = bar.window.capsules[Key.ISLAND]
        assert "20:59" in island.accessibleName() and "73%" in island.accessibleName()
        press(bar, Key.ISLAND)
        assert bar.expanded is not None and bar.window.capsules[Key.ISLAND].rows[0].accessibleName() == "Your work canvas"
        QTest.keyClick(bar.window, QtCore.Qt.Key.Key_Escape)
        bar.agent_changed(WORKING)
        assert "Comparing both sheets" in island.accessibleName()
        bar.hover(Key.ISLAND)
        stop_button(bar, Key.ISLAND).click()
        bar.recording_changed(RecordingState(phase="recording", seconds=125))
        bar.dictation(active=True)
        assert shown(bar) == [Key.AGENT, Key.ISLAND, Key.RECORDING]
        press(bar, Key.ISLAND)
        press(bar, Key.RECORDING)
        bar.hover(Key.RECORDING)
        stop_button(bar, Key.RECORDING).click()
        bar.hover(None)
        bar.dictation(active=False)
        bar.agent_changed(Agent("Which sheet?", waiting=True))
        press(bar, Key.ISLAND)
        bar.layout(enabled=False)
        assert "Colemak" in bar.window.capsules[Key.LAYER].accessibleName()
        press(bar, Key.LAYER)
        bar.inbox_changed(120)
        assert "120 clarifications" in bar.window.capsules[Key.INBOX].accessibleName()
        press(bar, Key.INBOX)
        assert invoked == ["stop", "stop", "canvas", "record-stop", "inbox", "keymap", "inbox"]
        bar.recording_changed(RecordingState(phase="saved"))
        bar.layout(enabled=True)
        bar.inbox_changed(0)
        rest(bar)
        assert shown(bar) == [Key.ISLAND]
    finally:
        closed(app, bar)


def test_capsules_float_below_the_edge_centred_and_one_gap_apart() -> None:
    # Defects: the island drifts off centre, neighbours touch or overlap it, the
    # edge strip leaves a dead band above the glass, or controls lose their concentric inset.
    app = application()
    bar = DesktopBar(recorded([]), native_shell=False)
    try:
        area = app.primaryScreen().geometry()
        assert bar.window.geometry() == QtCore.QRect(area.x(), area.y(), area.width(), TOP + 34)
        bar.inbox_changed(2)
        bar.recording_changed(RecordingState(phase="recording", seconds=125))
        bar.hover(Key.ISLAND)
        island, inbox = bar.window.capsules[Key.ISLAND].geometry(), bar.window.capsules[Key.INBOX].geometry()
        # Edges snap to device pixels, so a logical edge can sit a pixel off at fractional scales.
        assert abs(island.left() + island.width() / 2 - area.width() / 2) <= 1
        assert island.top() == 0 and island.height() == TOP + 34
        assert abs(inbox.left() - (island.left() + island.width()) - 6) <= 1
        stop = stop_button(bar, Key.ISLAND).geometry()
        assert (stop.width(), stop.height(), stop.top() - TOP) == (28, 28, 3)
        assert abs(island.width() - (stop.left() + stop.width()) - 3) <= 1
    finally:
        closed(app, bar)


def test_pointer_reaches_capsules_and_their_edge_strip_but_passes_through_elsewhere() -> None:
    # Defects: a glass host intercepts another process's title-bar/drag targets
    # in the empty strip or shadow, or capsules and their edge strip lose input.
    # This query was qualified red against the old STATIC host; it runs on the
    # target's own message thread and never injects input into an unshown desktop.
    app = application()
    bar = DesktopBar(recorded([]), native_shell=False, observations=BarObservations(material=lambda: appearance.Material.GLASS, motion=lambda: False))
    try:
        bar.visible = True
        bar.render()
        bar.timer.stop()
        app.processEvents()
        if bar.loop.composition is None:
            raise unittest.SkipTest("Desktop composition is unavailable.")
        scene = bar.window.scene
        assert scene is not None and scene.bounds is not None, "The bar did not create its available glass host."
        handle = int(bar.window.winId())
        rest_height = windows.outer_rect(handle).height
        with foreign_pointer(scene.bounds) as target:
            for expanded in (False, True):
                if expanded:
                    # This fixture owns native hit bounds; menu activation is
                    # covered elsewhere. Supply the immutable expanded observation
                    # without requesting foreground on the unshown desktop.
                    app.processEvents()
                    bar.expanded = bar.menu()
                    bar.render()
                    app.processEvents()
                    assert windows.outer_rect(handle).height > rest_height
                    assert any(row.isVisibleTo(bar.window) for row in bar.window.capsules[Key.ISLAND].rows)
                outer, scale = windows.outer_rect(handle), bar.window.devicePixelRatioF()
                island = bar.window.capsules[Key.ISLAND].geometry()
                assert scene.bounds is not None
                windows.move(target.window.handle, scene.bounds)
                outside = (
                    (outer.left + round((island.left() - 40) * scale), outer.top + round((TOP + 17) * scale)),
                    (outer.left + round(island.center().x() * scale), outer.bottom + round(SHADOW * scale / 2)),
                    (outer.left + round((island.left() - 12) * scale), outer.top + round((TOP + 17) * scale)),
                )
                capsule = (
                    (outer.left + round(island.center().x() * scale), outer.top + round((TOP + 17) * scale)),
                    (outer.left + round(island.center().x() * scale), outer.top + round(scale)),
                )
                scene.hide()
                assert tuple(target.sample(point, app.processEvents) for point in outside) == (target.window.handle,) * 3
                scene.show(handle)
                assert tuple(target.sample(point, app.processEvents) for point in outside) == (target.window.handle,) * 3
                assert tuple(target.sample(point, app.processEvents) for point in capsule) == (handle,) * 2
    finally:
        closed(app, bar)


def test_capsules_spring_between_views_and_the_frame_loop_stops_once_settled() -> None:
    # Defects: a capsule appears or vanishes at full size, its neighbour jumps, the
    # frame loop keeps running at rest, or reduced motion still animates.
    app = application()
    now, motion = [100.0], [True]
    bar = DesktopBar(recorded([]), native_shell=False, observations=BarObservations(clock=lambda: now[0], motion=lambda: motion[0]))
    try:
        bar.timer.stop()
        bar.visible = True
        bar.render()
        island = bar.window.capsules[Key.ISLAND].geometry()
        bar.inbox_changed(2)
        now[0] += 0.08
        bar.paint_frames()
        inbox = bar.window.capsules[Key.INBOX].geometry()
        assert 1 < inbox.width() < 36 and bar.loop.timer.isActive()
        assert bar.window.capsules[Key.ISLAND].geometry() == island, "The island moved for a trailing capsule."
        now[0] += 2
        bar.paint_frames()
        assert bar.window.capsules[Key.INBOX].geometry().width() == 36 and not bar.loop.timer.isActive()
        bar.inbox_changed(0)
        now[0] += 0.05
        bar.paint_frames()
        assert Key.INBOX in shown(bar) and bar.window.capsules[Key.INBOX].geometry().width() < 36
        now[0] += 2
        bar.paint_frames()
        assert shown(bar) == [Key.ISLAND] and not bar.loop.timer.isActive()
        motion[0] = False
        bar.inbox_changed(5)
        assert shown(bar) == [Key.ISLAND, Key.INBOX] and bar.window.capsules[Key.INBOX].geometry().width() == 36
        assert not bar.loop.timer.isActive()
    finally:
        closed(app, bar)


def test_contrast_paints_system_colours_and_releases_only_its_composition_owner() -> None:
    # Defects: high contrast keeps glass or Workspace colours, or closing the bar
    # closes the composition that other views still use.
    app = application()
    bar = DesktopBar(recorded([]), native_shell=False, observations=BarObservations(material=lambda: appearance.Contrast("#000000", "#ffff00")))
    other_view = EventLoop(app, lambda: None)
    try:
        island = bar.window.capsules[Key.ISLAND]
        image = island.grab().toImage()
        assert image.pixelColor(island.width() - 4, TOP + 17) == QtGui.QColor("#000000")
        assert not bar.window.glass
        assert other_view.composition is bar.loop.composition
        bar.close()
        if other_view.composition is not None:
            assert not other_view.composition.closed
    finally:
        closed(app, bar)
        other_view.close()


def test_dictation_traces_the_microphone_only_while_listening() -> None:
    # Defects: the trace runs or keeps its timer outside dictation, a silent
    # microphone keeps the last level, or leaving dictation wipes the trace mid-frame.
    app = application()
    level = [0.25]
    bar = DesktopBar(recorded([]), native_shell=False, audio_level=lambda: level[0])
    try:
        assert not bar.audio_timer.isActive()
        bar.dictation(active=True)
        assert bar.audio_timer.isActive()
        sampled(app, bar, lambda: bar.window.samples[-1] > 0)
        level[0] = 0
        sampled(app, bar, lambda: bar.window.samples[-1] == 0)
        trace = tuple(bar.window.samples)
        bar.dictation(active=False)
        bar.job_changed(Job.TRANSCRIBING)
        assert not bar.audio_timer.isActive()
        bar.sample_audio()
        assert tuple(bar.window.samples) == trace
    finally:
        closed(app, bar)


def test_slow_native_audio_level_does_not_block_the_waveform_ui() -> None:
    app = application()
    entered, released = threading.Event(), threading.Event()
    caller = threading.current_thread()
    readers: list[threading.Thread] = []

    def level() -> float:
        readers.append(threading.current_thread())
        entered.set()
        released.wait(0.25)
        return 0.25

    bar = DesktopBar(recorded([]), native_shell=False, audio_level=level)
    try:
        bar.dictation(active=True)
        started = time.monotonic()
        bar.sample_audio()
        assert time.monotonic() - started < 0.025, "A slow driver blocked a waveform frame."
        assert entered.wait(0.5), "Listening must start observing the microphone."
        assert readers and all(reader is not caller for reader in readers), "Native audio observation belongs off Qt's thread."
        released.set()
        sampled(app, bar, lambda: bar.window.samples[-1] > 0)
    finally:
        released.set()
        closed(app, bar)


def test_activity_indicators_move_only_while_work_runs_and_motion_allows() -> None:
    # Defects: the agent's spinner or a job's dots are painted frozen, keep the
    # frame timer running after work ends, or ignore Windows' reduced-motion setting.
    app = application()
    now, motion = [10.0], [True]
    bar = DesktopBar(recorded([]), native_shell=False, observations=BarObservations(clock=lambda: now[0], motion=lambda: motion[0]))
    bar.visible = True
    try:
        island = bar.window.capsules[Key.ISLAND]

        def transcribe(_: Agent) -> None:
            bar.job_changed(Job.TRANSCRIBING)

        starts: tuple[Callable[[Agent], None], ...] = (bar.agent_changed, transcribe)
        for start in starts:
            rest(bar)
            start(WORKING)
            now[0] += 2
            bar.paint_frames()
            assert bar.loop.timer.isActive()
            first = island.grab().toImage()
            now[0] += 0.3
            bar.paint_frames()
            assert island.grab().toImage() != first, "An activity painted a stationary indicator."
        motion[0] = False
        bar.paint_frames()
        assert bar.window.spin_angle == 90 and not bar.loop.timer.isActive()
        motion[0] = True
        rest(bar)
        now[0] += 2  # The island's width settles back to rest.
        bar.paint_frames()
        assert not bar.loop.timer.isActive()
    finally:
        closed(app, bar)


def test_tool_choice_acts_on_the_window_captured_before_the_menu_opened() -> None:
    # Defect: a window tool acts on whatever window is in front after the menu
    # took the keyboard, or the keyboard isn't handed back to that window.
    app = application()
    invoked: list[tuple[Tool, int]] = []
    foreground, focused = [42], list[int]()
    observations = BarObservations(foreground=lambda: foreground[0], focus=lambda hwnd: remember(focused, hwnd))
    bar = DesktopBar(recorded([], tools=invoked), native_shell=False, observations=observations)
    try:
        bar.open_menu()
        foreground[0] = 999
        QTest.mouseClick(menu_row(bar, "Window tiling"), QtCore.Qt.MouseButton.LeftButton)
        QTest.mouseClick(menu_row(bar, "Float or tile the active window"), QtCore.Qt.MouseButton.LeftButton)
        assert invoked == [(Tool.TILE_FLOAT, 42)] and focused == [42] and bar.expanded is None
    finally:
        closed(app, bar)


def test_the_menu_takes_the_keyboard_and_hands_it_back_only_when_a_choice_calls_for_it() -> None:
    # Defects: arrows or letters don't reach the menu, Escape strands the keyboard
    # on the bar, opening a Workspace view gives the keyboard back to the old window,
    # clicking elsewhere steals it back, or a live row stops its activity from
    # anywhere but its Stop.
    app = application()
    invoked: list[str] = []
    focused: list[int] = []
    observations = BarObservations(foreground=lambda: 42, focus=lambda hwnd: remember(focused, hwnd))
    bar = DesktopBar(recorded(invoked), native_shell=False, observations=observations)
    try:
        bar.open_menu()
        island = bar.window.capsules[Key.ISLAND]
        assert island.height() > TOP + 34 and bar.window.height() >= island.height()
        QTest.keyClick(bar.window, QtCore.Qt.Key.Key_Down)
        opened = menu(bar)
        assert opened is not None and opened.selected == 0
        QTest.keyClick(bar.window, QtCore.Qt.Key.Key_Escape)
        assert menu(bar) is None and focused == [42] and bar.window.capsules[Key.ISLAND].height() == TOP + 34
        bar.open_menu()
        QTest.keyClicks(bar.window, "k")
        QTest.keyClick(bar.window, QtCore.Qt.Key.Key_Return)
        assert invoked == ["keymap"] and focused == [42]
        bar.open_menu()
        bar.deactivated()
        assert bar.expanded is None and focused == [42]
        bar.recording_changed(RecordingState(phase="recording", seconds=125))
        bar.open_menu()
        live = menu_row(bar, "Recording")
        assert "02:05" in live.accessibleName() and "Stop recording" in live.accessibleName()
        QTest.mouseClick(live, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(40, live.height() // 2))
        assert invoked == ["keymap"], "Clicking the live row's reading stopped the recording."
        QTest.mouseClick(live, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(live.width() - 17, live.height() // 2))
        assert invoked == ["keymap", "record-stop"] and bar.expanded is None
    finally:
        closed(app, bar)
