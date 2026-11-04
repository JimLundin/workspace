"""Glass publication through real Qt and Windows composition owners."""

import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows composition")

from win32more.Windows.Win32.UI.WindowsAndMessaging import GetWindow
lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.desktop_bar import BarActions, BarObservations, DesktopBar
from desktop_ui.island_model import Agent
from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import EventLoop, application
from desktop_ui.shell_items import Application
from winapi import appearance
from winapi.composition import Glass, GlassScene, stack_behind
from winapi.shapes import Pane, Rect, Stop, Veil, Window

prepare()

VEIL = Veil("#1c1c20", 0.26, (Stop(0, "#ffffff", 0.55), Stop(1, "#ffffff", 0.22)), 0.36)


def inert() -> BarActions:
    return BarActions(
        lambda: None,
        lambda: None,
        lambda: None,
        lambda action: None,
        lambda: None,
        lambda: None,
        lambda: None,
        lambda message: None,
        inbox=lambda: None,
    )


def foreground(title: str) -> QtWidgets.QWidget:
    window = QtWidgets.QWidget()
    window.setWindowTitle(title)
    window.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.resize(120, 40)
    return window


def test_the_bar_publishes_one_final_glass_frame_per_qt_turn_behind_its_window() -> None:
    # Defects: intermediate states of one Qt turn reach composition, a capsule
    # change moves the glass window, or the glass sits above the bar's content.
    app = application()
    bar = DesktopBar(inert(), native_shell=False, observations=BarObservations(material=lambda: appearance.Material.GLASS, motion=lambda: False))
    try:
        bar.visible = True
        bar.render()
        app.processEvents()
        scene = bar.window.scene
        if scene is None:
            raise unittest.SkipTest("Desktop composition is unavailable.")
        published, bounds = scene.published(), scene.bounds
        baseline_keys = {pane.key for pane in published}
        assert {"CANVAS", "STATUS"} <= baseline_keys
        assert not {"VOLUME", "WIFI"} & baseline_keys, "Status controls must share one glass capsule."
        assert "ISLAND" not in baseline_keys and "INBOX" not in baseline_keys
        bar.agent_changed(Agent("Comparing both sheets", waiting=False))
        bar.inbox_changed(3)
        bar.agent_changed(None)
        assert scene.published() == published, "Intermediate bar state reached Windows composition."
        app.processEvents()
        assert {pane.key for pane in scene.published()} == baseline_keys | {"INBOX"}
        assert scene.bounds == bounds, "A capsule change moved the glass window."
        assert GetWindow(int(bar.window.winId()), 2) == scene.handle
    finally:
        bar.close()
        app.processEvents()


def test_first_visible_frame_retains_application_glass_prepared_while_parent_hidden() -> None:
    # Defect: global child visibility omits the applications' glass from the cached first frame.
    app = application()
    bar = DesktopBar(inert(), native_shell=False, observations=BarObservations(material=lambda: appearance.Material.GLASS, motion=lambda: False))
    try:
        editor = Application("editor.exe", (Window(1, "Editor", "editor.exe", minimized=False),))
        bar.window.shell_sections.applications(((editor,), 0), lambda item, click: None)
        bar.window.presentation = None
        bar.render()
        assert not bar.window.isVisible()
        assert "applications" in {pane.key for pane in bar.window.panes}
        bar.visible = True
        bar.render()
        app.processEvents()
        scene = bar.window.scene
        if scene is None:
            raise unittest.SkipTest("Desktop composition is unavailable.")
        assert "applications" in {pane.key for pane in scene.published()}
    finally:
        bar.close()
        app.processEvents()


def test_scene_reuses_a_returning_panes_visuals_and_hides_departed_ones() -> None:
    # Defects: a capsule that returns allocates new native visuals, one that
    # leaves stays on screen, or a direct write targets the wrong COM slot.
    app = application()
    owner = EventLoop(app, lambda: None)
    if owner.composition is None:
        owner.close()
        raise unittest.SkipTest("Desktop composition is unavailable.")
    scene = GlassScene(owner.composition, "Workspace scene regression")
    try:
        scene.place(Rect(0, 0, 800, 120), 1.0)
        island, inbox = Pane("ISLAND", Rect(300, 8, 412, 42), 17, 1, VEIL), Pane("INBOX", Rect(418, 8, 452, 42), 17, 1, VEIL)
        scene.publish((island, inbox))
        group = scene.groups["INBOX"]
        scene.publish((island,))
        assert scene.published() == (island,) and group.visual.Opacity == 0
        scene.publish((island, inbox))
        assert scene.groups["INBOX"] is group, "A returning pane rebuilt its native visuals."
        # The writes go straight through IVisual's COM slots; read back through the SDK, they must land.
        assert group.visual.Opacity == 1 and (group.visual.Size.X, group.visual.Size.Y) == (34, 34)
        assert (group.visual.Offset.X, group.visual.Offset.Y) == (418, 8)
    finally:
        scene.close()
        owner.close()


def test_glass_stacks_only_when_real_window_order_needs_correction() -> None:
    # Defect: every frame repeats native stacking even while correctly ordered;
    # blindly caching that state instead fails to repair intervening windows.
    app = application()
    owner = EventLoop(app, lambda: None)
    if owner.composition is None:
        owner.close()
        raise unittest.SkipTest("Desktop composition is unavailable.")
    front_window, other_window = foreground("Workspace stacking foreground"), foreground("Workspace stacking intervening")
    placements: tuple[tuple[int, int], ...] = ()

    def observe_stack(handle: int, front: int) -> None:
        nonlocal placements
        placements = (*placements, (handle, front))
        stack_behind(handle, front)

    layer = Glass(owner.composition, stack=observe_stack)
    try:
        front_window.show()
        other_window.show()
        app.processEvents()
        front, other = int(front_window.winId()), int(other_window.winId())
        layer.show(front)
        assert GetWindow(front, 2) == layer.handle
        first = len(placements)
        for _ in range(5):
            layer.show(front)
        assert len(placements) == first, "An unchanged frame repeated native stacking."
        stack_behind(other, front)
        assert GetWindow(front, 2) == other
        layer.show(front)
        assert len(placements) == first + 1, "An intervening window did not correct glass stacking."
        assert GetWindow(front, 2) == layer.handle
    finally:
        layer.close()
        front_window.deleteLater()
        other_window.deleteLater()
        app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        owner.close()


def test_glass_resizes_its_retained_geometry_and_shadow_mask_across_dpi_changes() -> None:
    # Defects: a resize rebuilds native geometry and its clip, or the shadow mask
    # keeps an old size or DPI.
    app = application()
    owner = EventLoop(app, lambda: None)
    if owner.composition is None:
        owner.close()
        raise unittest.SkipTest("Desktop composition is unavailable.")
    layer = Glass(owner.composition)
    try:
        layer.position(Rect(40, 60, 260, 88), 1.0, 1.0)
        geometry, clip = layer.geometry, layer.group.Clip.value
        for width, scale in ((260, 1.0), (220, 1.25)):
            layer.position(Rect(40, 60, 40 + round(width * scale), 60 + round(28 * scale)), scale, 1.0)
            assert layer.geometry is geometry and layer.group.Clip.value == clip, "A resize rebuilt native geometry."
            size = layer.mask_surface.SourceSize
            expected = (round(width * scale), round(28 * scale))
            assert expected == (size.X, size.Y), "The shadow mask retained an old size or DPI."
    finally:
        layer.close()
        owner.close()
