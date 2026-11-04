"""The island bar through real Qt windows: what shows, where it sits, and what a press does."""

import sys
import threading
import time
import unittest
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import replace
from datetime import datetime

if sys.platform != "win32":
    raise unittest.SkipTest("Windows island bar")

import itertools

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtTest import QTest

from assistant.meeting_detection import AutomaticStatus
from assistant.recording_state import RecordingState
from desktop_ui.ambient import Ambient, SystemStatus
from desktop_ui.desktop_bar import BarActions, BarObservations, DesktopBar, SettingsUri
from desktop_ui.fluent_icons import REGULAR
from desktop_ui.island_menu import Menu, Rule
from desktop_ui.island_model import Action, Agent, Control, Job, Key
from desktop_ui.island_surface import SHADOW, TOP, ControlButton, MenuRow
from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import EventLoop, application
from desktop_ui.vector_icons import symbol
from protocol import Tool
from tests.native_pointer import foreign_pointer
from winapi import appearance, windows
from winapi._core import fn, user32
from winapi.machine_status import Battery, PowerUnavailable, Speakers, Wifi
from winapi.shapes import Rect
from winapi.tray_host import Entry

prepare()

WORKING = Agent("Comparing both sheets", waiting=False)
_GetWindowLong = fn(user32, "GetWindowLongW", wintypes.LONG, wintypes.HWND, wintypes.INT)


def test_idle_toolbar_preserves_application_focus_and_menu_can_take_the_keyboard() -> None:
    # Defect: the toolbar activates before an app click observes the current
    # window, so repeated icon clicks stop cycling that application's windows.
    app = application()
    bar = DesktopBar(recorded([]), native_shell=False)
    try:
        handle = int(bar.window.winId())
        assert _GetWindowLong(handle, -20) & 0x08000000
        bar.open_menu()
        assert not _GetWindowLong(handle, -20) & 0x08000000
        bar.close_menu(restore=False)
        assert _GetWindowLong(handle, -20) & 0x08000000
    finally:
        closed(app, bar)


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
        open_settings=invoked.append,
    )


FIXED = [Key.CANVAS, Key.STATUS]


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


def test_right_cluster_keeps_fixed_positions_and_truthful_status_through_disclosure() -> None:
    # Defects: tray expansion shifts fixed controls, missing readings imply a
    # healthy state, or unavailable symbols fall back to a document glyph.
    app = application()
    bar = DesktopBar(recorded([]), native_shell=False, observations=BarObservations(motion=lambda: False))
    try:
        bar.timer.stop()
        bar.layout(enabled=False)
        order = (Key.CANVAS, Key.LAYER, Key.STATUS)
        before = tuple(bar.window.capsules[key].geometry() for key in order)
        assert all(left.right() < right.left() for left, right in itertools.pairwise(before))
        tray = bar.window.shell_sections.tray
        toggle_left = tray.mapTo(bar.window, tray.toggle.pos()).x()
        assert toggle_left < before[0].left()
        assert tray.toggle.accessibleName() == "Expand system tray"
        tray.toggle.click()
        assert tray.toggle.accessibleName() == "Collapse system tray"
        assert tuple(bar.window.capsules[key].geometry() for key in order) == before
        assert tray.mapTo(bar.window, tray.toggle.pos()).x() == toggle_left
        for speakers in Speakers:
            for wifi in Wifi:
                bar.system = SystemStatus(speakers, wifi)
                bar.render()
                capsule = bar.window.capsules[Key.STATUS]
                assert capsule.view is not None
                assert capsule.view.slots[0] == (
                    Control(bar.system.speaker_icon, bar.system.speaker_description + " · Open sound settings", Action.OPEN_SOUND_SETTINGS),
                    Control(bar.system.wifi_icon, bar.system.wifi_description + " · Open Wi-Fi settings", Action.OPEN_WIFI_SETTINGS),
                )
                assert all(button.focusPolicy() is QtCore.Qt.FocusPolicy.StrongFocus for button in capsule.controls)
                assert tuple(button.size() for button in capsule.controls) == (QtCore.QSize(28, 28),) * 2
                assert tuple(button.accessibleName() for button in capsule.controls) == tuple(button.control.label for button in capsule.controls)
                assert tuple(button.toolTip() for button in capsule.controls) == tuple(button.control.label for button in capsule.controls)
                assert capsule.isVisibleTo(bar.window)
                for name, label in (
                    (bar.system.speaker_icon, bar.system.speaker_description),
                    (bar.system.wifi_icon, bar.system.wifi_description),
                ):
                    assert label in capsule.accessibleName() and label in capsule.toolTip()
                    assert symbol(name) != REGULAR["doc"]
                assert tuple(bar.window.capsules[key].geometry() for key in order) == before
        for power in (
            Battery(9, powered=False, charging=False),
            Battery(100, powered=True, charging=False),
            Battery(96, powered=True, charging=True),
            PowerUnavailable.NO_BATTERY,
            PowerUnavailable.UNKNOWN,
        ):
            bar.ambient = Ambient("11:11", power)
            bar.render()
            assert tuple(bar.window.capsules[key].geometry() for key in order) == before
            status = bar.window.capsules[Key.STATUS]
            assert bar.ambient.battery_text in status.accessibleName()
            assert status.view is not None
            assert abs(bar.window.measure(status.view).width - status.width()) <= 1
        assert symbol("chevron-left") == '<g transform="translate(16 0) scale(-1 1)">' + REGULAR["chevron"] + "</g>"
    finally:
        closed(app, bar)


def test_status_children_open_settings_without_parent_menu_or_focus_restore() -> None:
    # Defects: child presses bubble to the menu, swap destinations or restore old focus.
    app = application()
    invoked: list[str] = []
    focused: list[int] = []
    bar = DesktopBar(
        recorded(invoked),
        native_shell=False,
        observations=BarObservations(motion=lambda: False, foreground=lambda: 42, focus=lambda hwnd: remember(focused, hwnd)),
    )
    try:
        bar.timer.stop()
        capsule = bar.window.capsules[Key.STATUS]
        buttons = capsule.controls
        assert tuple(button.control.action for button in buttons) == (Action.OPEN_SOUND_SETTINGS, Action.OPEN_WIFI_SETTINGS)
        for button, destination in zip(buttons, ("ms-settings:sound", "ms-settings:network-wifi"), strict=True):
            QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
            assert invoked[-1] == destination and bar.expanded is None
            bar.open_menu()
            QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
            assert invoked[-1] == destination and bar.expanded is None and focused == []
        assert invoked == ["ms-settings:sound", "ms-settings:sound", "ms-settings:network-wifi", "ms-settings:network-wifi"]
        before = capsule.geometry()
        button = buttons[0]
        app.sendEvent(button, QtGui.QFocusEvent(QtCore.QEvent.Type.FocusIn, QtCore.Qt.FocusReason.TabFocusReason))
        assert button.ringed
        bar.system = SystemStatus(Speakers.MUTED, Wifi.DISCONNECTED)
        bar.render()
        assert capsule.controls == buttons and capsule.geometry() == before and button.ringed
        assert button.accessibleName() == "Speakers muted · Open sound settings"
        assert buttons[1].toolTip() == "Wi-Fi disconnected · Open Wi-Fi settings"
        QTest.keyClick(buttons[1], QtCore.Qt.Key.Key_Space)
        assert invoked[-1] == "ms-settings:network-wifi" and bar.expanded is None
        # The reading region still opens Workspace controls.
        QTest.mouseClick(capsule, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(capsule.width() - 10, TOP + 17))
        assert bar.expanded is not None
    finally:
        closed(app, bar)


def unavailable_settings(uri: str) -> None:
    """An explicit failing launch adapter detects swallowed Windows errors."""
    raise OSError("Cannot open " + uri)


def test_settings_launch_failure_reports_problem_and_leaves_menu_closed() -> None:
    # Defect: Windows launch failure escapes Qt or leaves focus-restoring menu state.
    app = application()
    invoked: list[str] = []
    focused: list[int] = []
    bar = DesktopBar(
        replace(recorded(invoked), open_settings=unavailable_settings),
        native_shell=False,
        observations=BarObservations(motion=lambda: False, foreground=lambda: 42, focus=lambda hwnd: remember(focused, hwnd)),
    )
    try:
        destinations: tuple[tuple[Action, SettingsUri], ...] = (
            (Action.OPEN_SOUND_SETTINGS, "ms-settings:sound"),
            (Action.OPEN_WIFI_SETTINGS, "ms-settings:network-wifi"),
        )
        for action, uri in destinations:
            bar.open_menu()
            bar.press(action)
            assert invoked[-1] == "problem: Cannot open " + uri
            assert bar.expanded is None and focused == []
    finally:
        closed(app, bar)


def test_the_canvas_capsule_rests_beside_the_island_and_opens_the_canvas() -> None:
    # Defects: Canvas navigation disappears, loses its label, or its press runs another function.
    app = application()
    invoked: list[str] = []
    bar = DesktopBar(recorded(invoked), native_shell=False)
    try:
        assert shown(bar) == FIXED
        assert bar.window.capsules[Key.CANVAS].accessibleName() == "Canvas · Open your work canvas"
        press(bar, Key.CANVAS)
        assert invoked == ["canvas"]
    finally:
        closed(app, bar)


def test_the_island_keeps_canvas_navigation_and_each_capsule_acts_on_what_it_shows() -> None:
    # Defects: a capsule's press runs another function, a stoppable activity
    # hides its Stop, or a finished activity leaves its capsule behind.
    app = application()
    invoked: list[str] = []
    observations = BarObservations(power=lambda: Battery(73, powered=False, charging=False), local_time=lambda: datetime(2026, 10, 30, 20, 59))
    bar = DesktopBar(recorded(invoked), native_shell=False, observations=observations)
    try:
        assert shown(bar) == FIXED
        status = bar.window.capsules[Key.STATUS]
        assert "20:59" in status.accessibleName() and "73%" in status.accessibleName()
        press(bar, Key.STATUS)
        assert bar.expanded is not None and bar.window.capsules[Key.ISLAND].rows[0].accessibleName() == "Your work canvas"
        QTest.keyClick(bar.window, QtCore.Qt.Key.Key_Escape)
        bar.agent_changed(WORKING)
        island = bar.window.capsules[Key.ISLAND]
        assert "Comparing both sheets" in island.accessibleName()
        stop = stop_button(bar, Key.ISLAND)
        before = island.geometry()
        bar.hover(Key.ISLAND)
        assert island.geometry() == before, "Hover changed the running agent's toolbar width."
        stop.click()
        bar.recording_changed(RecordingState(phase="recording", seconds=125))
        bar.dictation(active=True)
        assert shown(bar) == [Key.AGENT, Key.ISLAND, Key.RECORDING, *FIXED]
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
        assert shown(bar) == FIXED
        bar.automatic_changed(AutomaticStatus.READY)
        press(bar, Key.STATUS)
        menu_row(bar, "Auto-record Teams: On").click()
        assert invoked[-1] == "record-automatic"
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
        canvas = bar.window.capsules[Key.CANVAS].geometry()
        assert abs(inbox.left() - (island.left() + island.width()) - 6) <= 1
        assert canvas.left() > inbox.right()
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
        bar.agent_changed(WORKING)
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
        bar.agent_changed(WORKING)
        now[0] += 2
        bar.paint_frames()
        bar.agent_changed(None)
        now[0] += 2
        bar.paint_frames()
        assert Key.ISLAND not in shown(bar)
        bar.inbox_changed(2)
        now[0] += 0.08
        bar.paint_frames()
        inbox = bar.window.capsules[Key.INBOX].geometry()
        assert 1 < inbox.width() < 36 and bar.loop.timer.isActive()
        assert Key.ISLAND not in shown(bar), "Pending inbox restored idle centre facts."
        now[0] += 2
        bar.paint_frames()
        assert bar.window.capsules[Key.INBOX].geometry().width() == 36 and not bar.loop.timer.isActive()
        bar.inbox_changed(0)
        now[0] += 0.05
        bar.paint_frames()
        assert Key.INBOX in shown(bar) and bar.window.capsules[Key.INBOX].geometry().width() < 36
        now[0] += 2
        bar.paint_frames()
        assert shown(bar) == FIXED and not bar.loop.timer.isActive()
        motion[0] = False
        bar.inbox_changed(5)
        assert shown(bar) == [Key.INBOX, *FIXED] and bar.window.capsules[Key.INBOX].geometry().width() == 36
        assert not bar.loop.timer.isActive()
    finally:
        closed(app, bar)


def test_tray_frames_reverse_without_jumping_keep_anchors_and_publish_only_visible_hitboxes() -> None:
    # Defects: disclosure jumps, reversal restarts from an endpoint, tray-only
    # motion loses its timer/glass publication, or clipped/closing icons are located.
    app = application()
    now, motion = [100.0], [True]
    bar = DesktopBar(
        recorded([]),
        native_shell=False,
        observations=BarObservations(clock=lambda: now[0], motion=lambda: motion[0], material=lambda: appearance.Material.GLASS),
    )
    try:
        bar.timer.stop()
        bar.visible = True
        sections, tray = bar.window.shell_sections, bar.window.shell_sections.tray
        entries = tuple(Entry(1, index, b"", 0x8001, None, str(index)) for index in range(12))
        sections.notifications(entries, lambda item, click: None)
        bar.window.presentation = None
        bar.render()
        app.processEvents()
        fixed = tuple(bar.window.capsules[key].geometry() for key in FIXED)
        anchor = tray.mapTo(bar.window, tray.toggle.pos()).x()
        outer = Rect(0, 0, bar.window.width(), bar.window.height())
        tray.toggle.click()
        assert tray.width() == 36 and bar.loop.timer.isActive()
        now[0] += 0.08
        bar.paint_frames()
        app.processEvents()
        intermediate = tray.width()
        assert 36 < intermediate < tray.desired_width()
        assert tray.mapTo(bar.window, tray.toggle.pos()).x() == anchor
        assert tuple(bar.window.capsules[key].geometry() for key in FIXED) == fixed
        pane = next(pane for pane in bar.window.panes if pane.key == "tray")
        assert pane.bounds.width == round(intermediate * bar.window.devicePixelRatioF())
        located = sections.locations(outer, 1)
        assert 0 < len(located) < len(entries)
        viewport = tray.overflow.viewport()
        assert all(
            viewport.rect().contains(QtCore.QRect(button.mapTo(viewport, QtCore.QPoint()), button.size()))
            for button in tray.buttons
            if any(item.entry.tip == button.toolTip() for item in located)
        )
        tray.toggle.click()
        assert tray.width() == intermediate and sections.locations(outer, 1) == ()
        assert not tray.overflow.isEnabled()
        now[0] += 0.12
        bar.paint_frames()
        assert 36 < tray.width() < intermediate
        closing = tray.width()
        tray.toggle.click()
        assert tray.width() == closing and tray.overflow.isEnabled()
        now[0] += 2
        bar.paint_frames()
        app.processEvents()
        assert tray.width() == round(tray.width_motion.target)
        assert tray.mapTo(bar.window, tray.toggle.pos()).x() == anchor
        assert not bar.loop.timer.isActive() and not bar.resolution.active
        motion[0] = False
        assert_reduced_tray_motion(bar, fixed, anchor)
    finally:
        closed(app, bar)


def assert_reduced_tray_motion(bar: DesktopBar, fixed: tuple[QtCore.QRect, ...], anchor: int) -> None:
    """Verify that disabling motion settles disclosure without shifting fixed controls."""
    tray = bar.window.shell_sections.tray
    tray.toggle.click()
    bar.paint_frames()
    assert tray.width() == 36 and not tray.overflow.isVisible()
    assert not bar.loop.timer.isActive()
    tray.toggle.click()
    assert tray.width() == round(tray.width_motion.target) and tray.width() > 36
    assert tuple(bar.window.capsules[key].geometry() for key in FIXED) == fixed
    assert tray.mapTo(bar.window, tray.toggle.pos()).x() == anchor
    assert not bar.loop.timer.isActive()


def test_contrast_paints_system_colours_and_releases_only_its_composition_owner() -> None:
    # Defects: high contrast keeps glass or Workspace colours, or closing the bar
    # closes the composition that other views still use.
    app = application()
    bar = DesktopBar(recorded([]), native_shell=False, observations=BarObservations(material=lambda: appearance.Contrast("#000000", "#ffff00")))
    other_view = EventLoop(app, lambda: None)
    try:
        island = bar.window.capsules[Key.STATUS]
        image = island.grab().toImage()
        scale = image.devicePixelRatio()
        assert image.pixelColor(round((island.width() - 4) * scale), round((TOP + 17) * scale)) == QtGui.QColor("#000000")
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


def test_dictation_animates_between_samples_without_republishing_glass() -> None:
    # Defects: dictation only jumps on its 20 Hz sample timer, or indicator
    # frames repeat unchanged native glass/layout publication.
    app = application()
    now = [100.0]
    bar = DesktopBar(
        recorded([]), native_shell=False, audio_level=lambda: 0.25, observations=BarObservations(clock=lambda: now[0], motion=lambda: True)
    )
    bar.visible = True
    try:
        bar.timer.stop()
        bar.dictation(active=True)
        now[0] += 2
        bar.paint_frames()
        app.processEvents()
        bar.audio_timer.stop()
        sampled(app, bar, lambda: bar.window.samples[-1] > 0)
        assert bar.loop.timer.isActive(), "Settled dictation must keep its waveform frames running."
        app.processEvents()
        first = bar.window.capsules[Key.ISLAND].grab().toImage()
        now[0] += 0.025
        bar.paint_frames()
        halfway = bar.window.capsules[Key.ISLAND].grab().toImage()
        assert halfway != first, "The waveform jumped only when another microphone sample arrived."
        assert not bar.window.glass_timer.isActive(), "A waveform frame queued unchanged glass publication."
        now[0] += 0.025
        bar.paint_frames()
        assert bar.window.capsules[Key.ISLAND].grab().toImage() != halfway
        bar.dictation(active=False)
        now[0] += 2
        bar.paint_frames()
        assert not bar.loop.timer.isActive() and not bar.resolution.active
    finally:
        closed(app, bar)


def test_activity_indicators_move_only_while_work_runs_and_motion_allows() -> None:
    # Defects: the agent's spinner or a job's dots are painted frozen, keep the
    # frame timer running after work ends, or ignore Windows' reduced-motion setting.
    app = application()
    now, motion = [10.0], [True]
    bar = DesktopBar(recorded([]), native_shell=False, observations=BarObservations(clock=lambda: now[0], motion=lambda: motion[0]))
    bar.visible = True
    try:
        # Seed the capsule before testing animated updates; its first frame is absent.
        bar.visible = False
        bar.agent_changed(WORKING)
        island = bar.window.capsules[Key.ISLAND]
        bar.visible = True

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


def test_expanded_menu_keeps_its_activity_spinner_running_after_settling() -> None:
    # Defect: expanding moves activity out of the compact slots, so its menu
    # spinner loses the frame loop and stays frozen once geometry settles.
    class Paints(QtCore.QObject):
        """This native observer retains paint deliveries from Workspace's updates."""

        def __init__(self, parent: QtCore.QObject) -> None:
            super().__init__(parent)
            self.count = 0

        def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
            if event.type() == QtCore.QEvent.Type.Paint:
                self.count += 1
            return False

    app = application()
    now, motion = [100.0], [True]
    bar = DesktopBar(
        recorded([]),
        native_shell=False,
        observations=BarObservations(clock=lambda: now[0], motion=lambda: motion[0], material=lambda: appearance.Material.SOLID),
    )
    bar.visible = True
    try:
        bar.timer.stop()
        bar.agent_changed(WORKING)
        bar.open_menu()
        now[0] += 2
        bar.paint_frames()
        app.processEvents()
        row = menu_row(bar, "Agent working")
        assert bar.loop.timer.isActive(), "The expanded activity lost its frame loop."
        first = row.grab().toImage()
        app.processEvents()
        paints = Paints(row)
        row.installEventFilter(paints)
        now[0] += 0.1
        bar.paint_frames()
        app.processEvents()
        assert paints.count, "The menu's activity did not receive a native paint."
        assert row.grab().toImage() != first, "The settled menu's activity spinner stayed frozen."
        motion[0] = False
        bar.paint_frames()
        assert not bar.loop.timer.isActive() and bar.window.spin_angle == 90
        motion[0] = True
        bar.agent_changed(None)
        now[0] += 2
        bar.paint_frames()
        assert not bar.loop.timer.isActive(), "An idle expanded menu kept animation running."
    finally:
        closed(app, bar)


def test_repeated_observations_cannot_postpone_the_next_animation_frame() -> None:
    # Defect: each observation restarts the frame timer, starving animation
    # delivery when observations arrive faster than the frame interval.
    app = application()
    bar = DesktopBar(recorded([]), native_shell=False, observations=BarObservations(motion=lambda: True))
    bar.visible = True
    frames = 0

    def painted() -> None:
        nonlocal frames
        frames += 1

    updates = QtCore.QTimer(bar.window)
    updates.setInterval(5)
    updates.timeout.connect(bar.render)
    waiting = QtCore.QEventLoop()
    try:
        bar.timer.stop()
        bar.agent_changed(WORKING)
        app.processEvents()
        bar.loop.timer.timeout.connect(painted)
        updates.start()
        QtCore.QTimer.singleShot(150, waiting.quit)
        waiting.exec()
        assert frames >= 3, "Repeated observations starved the animation timer."
    finally:
        updates.stop()
        closed(app, bar)


def test_first_menu_open_survives_native_activation_settling() -> None:
    # Defect: Qt briefly reports inactive between native activation events,
    # immediately closing the first expanded menu before its next interaction.
    app = application()
    bar = DesktopBar(recorded([]), native_shell=False, audio_level=lambda: 0.25, observations=BarObservations(motion=lambda: True))
    bar.visible = True
    bar.dictation(active=True)
    waiting = QtCore.QEventLoop()
    target = QtWidgets.QWidget()
    try:
        QtCore.QTimer.singleShot(75, bar.open_menu)
        QtCore.QTimer.singleShot(300, waiting.quit)
        waiting.exec()
        assert bar.expanded is not None, "Native activation closed the menu immediately after opening it."
        target.show()
        target.activateWindow()
        deadline = time.monotonic() + 2
        while (not target.isActiveWindow() or menu(bar) is not None) and time.monotonic() < deadline:
            QTest.qWait(20)
        assert target.isActiveWindow(), "The fixture did not transfer native focus."
        assert bar.expanded is None, "A real focus transfer left the menu open."
    finally:
        target.close()
        target.deleteLater()
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


def test_menu_dividers_never_take_the_pointer_selection_or_highlight() -> None:
    # Defect: entering a divider selects its row and paints the action highlight
    # behind the line, even though keyboard navigation and clicks skip it.
    app = application()
    invoked: list[str] = []
    bar = DesktopBar(recorded(invoked), native_shell=False, observations=BarObservations(motion=lambda: False))
    try:
        bar.open_menu()
        island = bar.window.capsules[Key.ISLAND]
        for divider in (row for row in island.rows if row.line.row is Rule.SEPARATOR):
            action = island.rows[divider.line.index - 1]
            point = QtCore.QPointF(action.rect().center())
            app.sendEvent(action, QtGui.QEnterEvent(point, point, QtCore.QPointF(action.mapToGlobal(point.toPoint()))))
            before = divider.grab().toImage()
            point = QtCore.QPointF(divider.rect().center())
            app.sendEvent(divider, QtGui.QEnterEvent(point, point, QtCore.QPointF(divider.mapToGlobal(point.toPoint()))))
            opened = menu(bar)
            assert opened is not None and opened.selected == action.line.index, "Hover selected a menu divider."
            assert divider.grab().toImage() == before, "Hover painted a highlight behind a menu divider."
            assert divider.cursor().shape() == QtCore.Qt.CursorShape.ArrowCursor
            QTest.mouseClick(divider, QtCore.Qt.MouseButton.LeftButton)
            assert menu(bar) is not None and not invoked, "Clicking a divider acted on the menu."
    finally:
        closed(app, bar)


def test_menu_rows_do_not_inherit_the_escape_closes_tooltip() -> None:
    # Defect: the expanded capsule's tooltip propagates to every menu row.
    app = application()
    bar = DesktopBar(recorded([]), native_shell=False, observations=BarObservations(motion=lambda: False))
    try:
        assert bar.window.capsules[Key.STATUS].toolTip()
        bar.open_menu()
        island = bar.window.capsules[Key.ISLAND]
        assert island.toolTip() == "" and all(row.toolTip() == "" for row in island.rows)
        assert "Workspace controls" in island.accessibleName()
        QTest.keyClick(bar.window, QtCore.Qt.Key.Key_Escape)
        assert bar.expanded is None and bar.window.capsules[Key.STATUS].toolTip()
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
        assert menu(bar) is None and focused == [42] and Key.ISLAND not in shown(bar)
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
