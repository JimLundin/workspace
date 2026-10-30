"""Toolbar frame publication through real Qt and Windows composition owners."""

import gc
import sys
import unittest
import weakref

if sys.platform != "win32":
    raise unittest.SkipTest("Windows toolbar geometry")

from win32more.Windows.UI.Composition import CompositionPath, CompositionPathGeometry
from win32more.Windows.Win32.UI.WindowsAndMessaging import GetWindow
lazy from PySide6 import QtCore

from assistant.bar_geometry import segment
from assistant.bar_surface import Pill
from assistant.notifications import Tone
from assistant.qt_runtime import prepare
from assistant.qt_ui import EventLoop, application
from winapi import appearance
from winapi.composition import Glass, stack_behind
from winapi.composition_paths import composition_path
from winapi.contours import Contour
from winapi.shapes import Rect

prepare()


def test_toolbar_publishes_only_final_geometry_in_one_qt_turn() -> None:
    # Defect: intermediate join/size changes rebuild native COM paths several
    # times before Qt can paint the final toolbar frame.
    app = application()
    loop = EventLoop(app, lambda: None)
    pill = Pill(loop, "Workspace geometry regression", attached=True)
    try:
        pill.resize(220, 28)
        pill.alpha = 1.0
        pill.presented = True
        pill.place(40, 60)
        pill.material(Tone.REPLY, appearance.Material.GLASS)
        pill.show()
        pill.sync_glass()
        app.processEvents()
        layer = pill.layer
        assert layer is not None and layer.size is not None
        previous = layer.size
        pill.connections(left=True)
        pill.connections(right=True)
        assert layer.size == previous, "Intermediate toolbar state reached Windows composition."
        app.processEvents()
        assert layer.size is not None
        assert layer.size[4] == segment(pill.width(), pill.height(), right=True).fill
    finally:
        pill.dispose()
        app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        loop.close()


def test_toolbar_reuses_native_contours_and_releases_its_bounded_pool() -> None:
    # Defect: a repeated native contour reconstructs thousands of COM callback
    # objects; an unbounded pool instead retains every size until process exit.
    app = application()
    owner = EventLoop(app, lambda: None)
    assert owner.composition is not None
    created: tuple[weakref.ReferenceType[object], ...] = ()

    def create_path(contour: Contour, scale: float) -> CompositionPath:
        nonlocal created
        path = composition_path(contour, scale)
        created = (*created, weakref.ref(path))
        return path

    layer = Glass(owner.composition, create_path=create_path)
    try:
        for width in (220, 260):
            layer.position(Rect(40, 60, 40 + width, 88), 1.0, 1.0, attached=True, contour=segment(width, 28).fill)
        count = len(created)
        for width in (220, 260, 220):
            layer.position(Rect(40, 60, 40 + width, 88), 1.0, 1.0, attached=True, contour=segment(width, 28).fill)
        assert len(created) == count, "Repeated toolbar geometry rebuilt its native path."
        layer.position(Rect(40, 60, 315, 95), 1.25, 1.0, attached=True, contour=segment(220, 28).fill)
        assert len(created) == count + 1, "A DPI change reused geometry at the wrong scale."
        for width in range(280, 460, 20):
            layer.position(Rect(40, 60, 40 + width, 88), 1.0, 1.0, attached=True, contour=segment(width, 28).fill)
        count = len(created)
        layer.position(Rect(40, 60, 260, 88), 1.0, 1.0, attached=True, contour=segment(220, 28).fill)
        assert len(created) == count + 1, "The toolbar retained more than its native path budget."
    finally:
        layer.close()
        owner.close()
    gc.collect()
    assert all(reference() is None for reference in created), "Closed glass retained cached native paths."


def test_glass_stacks_only_when_real_window_order_needs_correction() -> None:
    # Defect: every frame repeats native stacking even while correctly ordered;
    # blindly caching that state instead fails to repair intervening windows.
    app = application()
    owner = EventLoop(app, lambda: None)
    assert owner.composition is not None
    foreground = Pill(owner, "Workspace stacking foreground")
    intervening = Pill(owner, "Workspace stacking intervening")
    placements: tuple[tuple[int, int], ...] = ()

    def observe_stack(handle: int, front: int) -> None:
        nonlocal placements
        placements = (*placements, (handle, front))
        stack_behind(handle, front)

    layer = Glass(owner.composition, stack=observe_stack)
    try:
        foreground.show()
        intervening.show()
        app.processEvents()
        front, other = int(foreground.winId()), int(intervening.winId())
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
        foreground.dispose()
        intervening.dispose()
        app.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        owner.close()


def test_glass_updates_retained_geometry_and_clip_across_shape_and_dpi_changes() -> None:
    # Defect: every contour change rebuilds native geometry and its clip, even
    # though their supported setters can update the same owner-bound resources.
    app = application()
    owner = EventLoop(app, lambda: None)
    assert owner.composition is not None
    layer = Glass(owner.composition)

    def published() -> None:
        # Defect: the retained geometry changes, but the visible clip or shadow
        # mask keeps the prior rounded/path resource.
        interface = type(layer.geometry)
        assert layer.clip.Geometry.as_(interface).value == layer.geometry.value, "The visible clip retained the prior geometry."
        assert layer.mask_shape.Geometry.as_(interface).value == layer.geometry.value, "The shadow mask retained the prior geometry."

    try:
        contour = segment(220, 28).fill
        layer.position(Rect(40, 60, 260, 88), 1.0, 1.0, attached=True, contour=contour)
        geometry = layer.geometry
        match geometry:
            case CompositionPathGeometry():
                pass
            case _:
                raise AssertionError("A joined capsule did not publish native path geometry.")
        clip = layer.group.Clip.value
        published()
        for width, scale, right in ((260, 1.0, True), (260, 1.0, False), (220, 1.25, True)):
            contour = segment(width, 28, right=right).fill
            layer.position(Rect(40, 60, 40 + round(width * scale), 60 + round(28 * scale)), scale, 1.0, attached=True, contour=contour)
            assert layer.geometry is geometry, "Changing the contour rebuilt native path geometry."
            assert layer.group.Clip.value == clip, "Changing the contour rebuilt its native clip."
            published()
            assert geometry.Path.value == layer.paths(contour, scale).value, "Retained geometry used a stale shape or DPI."
            size = layer.mask_surface.SourceSize
            assert round(width * scale) == size.X and round(28 * scale) == size.Y, "The shadow mask retained an old size or DPI."
            size = layer.root.Size
            padding = round(28 * scale)
            assert round(width * scale) + 2 * padding == size.X and round(28 * scale) + 2 * padding == size.Y
        layer.position(Rect(40, 60, 260, 88), 1.0, 1.0)
        assert layer.group.Clip.value == clip, "Switching to rounded geometry rebuilt the clip."
        published()
        layer.position(Rect(40, 60, 260, 88), 1.0, 1.0, attached=True, contour=contour)
        assert layer.geometry is geometry, "Returning to a joined capsule rebuilt its geometry."
        published()
    finally:
        layer.close()
        owner.close()
