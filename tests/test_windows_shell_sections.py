"""Workspace's shell grouping, real tray registration and accessible toolbar controls."""

import sys
import time
import unittest
from dataclasses import replace

if sys.platform != "win32":
    raise unittest.SkipTest("Windows shell sections")

lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtTest import QTest

from desktop_ui.components.appearance import Capsule, look
from desktop_ui.components.meaning import Tint
from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import application
from desktop_ui.shell_items import Application, applications, next_window
from desktop_ui.shell_surface import ShellSections
from winapi import appearance, desktop_shell, shell, windows
from winapi.icon_pixels import pixels
from winapi.shapes import Rect, Window
from winapi.tray_host import Click, Entry, Located, Registration, TrayHost, callbacks, registration, update

prepare()


def test_legacy_black_app_icons_keep_their_mask_while_copying_pixels() -> None:
    # Defect: the adapter treats opaque black legacy ink as transparent.
    image = shell.Icon(32, bytes(32 * 32 * 4))
    try:
        copied = pixels(image.handle)
        assert copied is not None and all(alpha == 255 for alpha in copied.bgra[3::4])
    finally:
        image.destroy()


def test_application_grouping_preserves_icon_order_and_cycles_current_windows() -> None:
    # Defect: MRU enumeration shuffles icons or switching ignores another window of the same app.
    first = Window(11, "One", "editor.exe", minimized=False)
    second = Window(12, "Two", "editor.exe", minimized=True)
    other = Window(20, "Browser", "browser.exe", minimized=False)
    apps = applications((first, other, second), ())
    reordered = applications((other, second, first), apps)
    assert tuple(app.identity for app in reordered) == ("editor.exe", "browser.exe")
    assert tuple(window.handle for window in reordered[0].windows) == (11, 12)
    assert next_window(apps[0], 11) == 12 and next_window(apps[0], 12) == 11
    assert next_window(apps[0], 99) == 11
    assert applications((other,), reordered) == (Application("browser.exe", (other,)),)


def test_tray_host_captures_real_icon_updates_routes_clicks_and_restores_explorer() -> None:
    # Defect: the proxy misses the live wire layout, loses update fields, forwards
    # to a guessed callback, or lets taskbar recovery hide its own native window.
    app = application()
    received: list[tuple[int, int]] = []

    def message(hwnd: int, kind: int, wparam: int, lparam: int) -> int | None:
        # Native WNDPROC contract.
        if kind == 0x8123:
            received.append((wparam, lparam))
            return 0
        return None

    owner = shell.AppWindow("workspace test tray owner", message)
    image = shell.Icon(32, bytes((80, 160, 240, 255)) * 1024)
    host = TrayHost()
    tray = shell.TrayIcon(owner.handle, 0x8123, image, "Workspace fixture")
    try:
        deadline = time.monotonic() + 2
        while not host.entries and time.monotonic() < deadline:
            app.processEvents()
        entry = next(entry for entry in host.poll() if entry.window == owner.handle)
        assert entry.tip == "Workspace fixture" and entry.callback == 0x8123
        assert entry.image is not None and any(entry.image.bgra[3::4])
        assert host.window.handle not in desktop_shell.taskbars()
        host.locate((Located(entry, Rect(42, 50, 64, 72)),))
        observed_bounds = tray.bounds()
        assert observed_bounds == Rect(42, 50, 64, 72), (observed_bounds, owner.handle)
        host.click(entry, Click.RIGHT, (42, 84))
        app.processEvents()
        assert received == [(1, 0x204), (1, 0x205)]
        tray.update(image, "Updated fixture")
        app.processEvents()
        changed = next(entry for entry in host.poll() if entry.window == owner.handle)
        assert changed.tip == "Updated fixture" and changed.callback == 0x8123
        tray.remove()
        app.processEvents()
        assert not any(entry.window == owner.handle for entry in host.poll())
        tray.restore()
        app.processEvents()
        restored = next(entry for entry in host.poll() if entry.window == owner.handle)
        assert restored.tip == "Updated fixture" and restored.callback == 0x8123
    finally:
        tray.remove()
        handle = host.window.handle
        host.close()
        owner.destroy()
        image.destroy()
        assert not windows.exists(handle)


def test_tray_version_four_packs_identity_and_signed_screen_coordinates() -> None:
    # Defect: Workspace sends the legacy callback arguments after version negotiation.
    entry = Entry(1, 17, b"", 0x8001, None, "Tray", version=4)
    assert callbacks(entry, Click.LEFT, (-20, 40)) == tuple((0x0028FFEC, (17 << 16) | event) for event in (0x201, 0x202, 0x400))
    assert callbacks(entry, Click.RIGHT, (20, -40))[-1] == (0xFFD80014, (17 << 16) | 0x7B)
    assert registration(b"invalid") is None


def test_tray_updates_respect_field_flags_and_version_changes_preserve_registration() -> None:
    # Defect: an icon-only update clears callback/tooltip, or version negotiation
    # applies unrelated fields and turns an existing tray item into a dead button.
    original = Entry(10, 2, b"", 0x8001, None, "Original", version=4)
    observed = Registration(1, 10, 2, 2, 0, 0, "", 0, 0, 0, b"")
    assert update((original,), observed, None) == (original,)
    hidden = update((original,), replace(observed, flags=8, state=1, mask=1), None)
    assert hidden == (replace(original, hidden=True),)
    version = replace(observed, operation=4, flags=7, version=3)
    assert update((original,), version, None) == (replace(original, version=3),)
    assert update((original,), replace(observed, operation=2), None) == ()


def test_toolbar_shell_icons_route_actions_and_keep_overflow_reachable() -> None:
    # Defect: buttons lose their app identity, or excess icons disappear
    # instead of remaining scrollable.
    app = application()
    parent = QtWidgets.QWidget()
    parent.resize(600, 50)
    sections = ShellSections(parent)
    invoked: list[tuple[str, Click]] = []
    apps = tuple(Application(str(index), (Window(index + 1, "Window", "app.exe", minimized=False),)) for index in range(12))
    sections.applications((apps, 1), lambda item, click: invoked.append((item.identity, click)))
    sections.place(250, 600)
    parent.show()
    app.processEvents()
    try:
        QTest.mouseClick(sections.apps.buttons[0], QtCore.Qt.MouseButton.LeftButton)
        QTest.mouseClick(sections.apps.buttons[1], QtCore.Qt.MouseButton.RightButton)
        assert invoked == [("0", Click.LEFT), ("1", Click.RIGHT)]
        assert sections.apps.overflow.horizontalScrollBar().maximum() > 0
        sections.apps.overflow.horizontalScrollBar().setValue(sections.apps.overflow.horizontalScrollBar().maximum())
        app.processEvents()
        assert (
            sections.apps.buttons[-1].geometry().right() - sections.apps.overflow.horizontalScrollBar().value()
            < sections.apps.overflow.viewport().width()
        )
        assert sections.apps.geometry().right() < 250
    finally:
        parent.close()
        parent.deleteLater()
        app.processEvents()


def test_shell_sections_leave_glass_transparent_and_use_the_shared_solid_surface() -> None:
    # Defect: a scroll viewport paints opaque black over the native glass,
    # or the shell strip invents a colour instead of using the shared surface.
    app = application()
    parent = QtWidgets.QWidget()
    parent.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
    parent.resize(600, 50)
    sections = ShellSections(parent)
    item = Application("editor.exe", (Window(1, "Editor", "editor.exe", minimized=False),))
    sections.applications(((item,), 0), lambda item, click: None)
    sections.place(250, 600)
    sections.apps.apply_look(look(appearance.Material.GLASS, Capsule(appearance.Frost.SMOKED), Tint.NONE))
    parent.show()
    app.processEvents()
    try:
        assert sections.apps.grab().toImage().pixelColor(3, 17).alpha() <= 1
        sections.apps.apply_look(look(appearance.Contrast("#ffffff", "#000000"), Capsule(appearance.Frost.SMOKED), Tint.NONE))
        app.processEvents()
        pixel = sections.apps.grab().toImage().pixelColor(3, 17)
        assert (pixel.red(), pixel.green(), pixel.blue(), pixel.alpha()) == (255, 255, 255, 255)
    finally:
        parent.close()
        parent.deleteLater()
        app.processEvents()
