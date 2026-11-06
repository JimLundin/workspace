"""Workspace's shell grouping, real tray registration and accessible toolbar controls."""

import sys
import time
import unittest
from dataclasses import replace

if sys.platform != "win32":
    raise unittest.SkipTest("Windows shell sections")

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtTest import QTest

from desktop_ui.components.appearance import Capsule, look
from desktop_ui.components.meaning import Tint
from desktop_ui.desktop_pager import pager
from desktop_ui.navigation import Navigation
from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import application
from desktop_ui.shell_items import (
    EMPTY_SHELF,
    Application,
    Launches,
    Pinned,
    PinnedApp,
    Shelf,
    applications,
    caption_clip,
    launch,
    next_window,
    outstanding,
    shelf,
)
from desktop_ui.shell_surface import STACK_STEP, ShellSections, page_font
from desktop_ui.ui import Ui
from desktop_ui.window_layout import EDGE, TERMINAL, App, Program, WorkspaceView
from winapi import appearance, desktop_shell, shell, windows
from winapi.icon_pixels import Pixels, pixels
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
    handles = tuple(window.handle for window in apps[0].windows)
    assert next_window(handles, 11) == 12 and next_window(handles, 12) == 11
    assert next_window(handles, 99) == 11
    assert applications((other,), reordered) == (Application("browser.exe", (other,)),)


def test_pinned_web_app_windows_fill_their_slots_and_leave_the_edge_group() -> None:
    # Defect: an app window also shows in Edge's group, the ordinary browser or a
    # lookalike id fills a slot, another profile's window is missed, or slot order shuffles.
    mail = Window(1, "Mail", "msedge.exe", minimized=False)
    calendar = Window(2, "Calendar", "msedge.exe", minimized=False)
    chat = Window(3, "Chat", "msedge.exe", minimized=False)
    browser = Window(4, "Browser", "msedge.exe", minimized=False)
    lookalike = Window(5, "Other", "msedge.exe", minimized=False)
    editor = Window(6, "Editor", "editor.exe", minimized=False)
    app_ids = {
        1: "MSEdge.outlook.cloud.microsoft_/mail/",
        2: "MSEdge.outlook.cloud.microsoft_/mail/",
        3: "MSEdge.teams.cloud.microsoft_/.Profile 1",
        4: "MSEdge",
        5: "MSEdge.outlook.cloud.microsoft_/mail/calendar",
    }
    first = shelf((mail, browser, chat, calendar, lookalike, editor), app_ids, EMPTY_SHELF)
    assert first == Shelf(
        (Pinned(PinnedApp.OUTLOOK, (mail, calendar)), Pinned(PinnedApp.TEAMS, (chat,))),
        (Application("msedge.exe", (browser, lookalike)), Application("editor.exe", (editor,))),
    )
    again = shelf((calendar, editor, mail), app_ids, first)
    assert again == Shelf(
        (Pinned(PinnedApp.OUTLOOK, (mail, calendar)), Pinned(PinnedApp.TEAMS, ())),
        (Application("editor.exe", (editor,)),),
    )


def test_a_pinned_launch_waits_for_its_window_before_launching_again() -> None:
    # Defect: repeated clicks open several app windows, one slot's launch blocks
    # the other, or a closed window can no longer be reopened.
    none: Launches = frozendict()
    pending: Launches = frozendict({PinnedApp.OUTLOOK: 115.0})
    assert launch(none, PinnedApp.OUTLOOK, 100.0) == pending
    assert launch(pending, PinnedApp.OUTLOOK, 114.0) is None
    assert launch(pending, PinnedApp.OUTLOOK, 115.0) == frozendict({PinnedApp.OUTLOOK: 130.0})
    assert launch(pending, PinnedApp.TEAMS, 101.0) == frozendict({PinnedApp.OUTLOOK: 115.0, PinnedApp.TEAMS: 116.0})
    opened = Shelf((Pinned(PinnedApp.OUTLOOK, (Window(1, "Mail", "msedge.exe", minimized=False),)), Pinned(PinnedApp.TEAMS, ())), ())
    assert outstanding(pending, opened) == none
    assert outstanding(pending, EMPTY_SHELF) == pending


def test_slot_windows_hide_their_caption_once_and_follow_resizing() -> None:
    # Defect: the region is rewritten every poll, or a region kept from the restored
    # size crops a maximized window (Edge keeps an applied region across resizes).
    restored, maximized, caption = Rect(632, 0, 1288, 1208), Rect(-9, -9, 1929, 1209), Rect(463, 0, 648, 37)
    clipped = caption_clip(restored, caption, None)
    assert clipped == Rect(0, 37, 656, 1208)
    assert caption_clip(restored, caption, clipped) is None
    assert caption_clip(maximized, caption, clipped) == Rect(0, 37, 1938, 1218)


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
    image = shell.Icon(16, bytes((80, 160, 240, 255)) * 256)
    host = TrayHost()
    tray = shell.TrayIcon(owner.handle, 0x8123, image, "Workspace fixture")
    try:
        deadline = time.monotonic() + 2
        while not host.entries and time.monotonic() < deadline:
            app.processEvents()
        entry = next(entry for entry in host.poll() if entry.window == owner.handle)
        assert entry.tip == "Workspace fixture" and entry.callback == 0x8123
        # A 16 px registration stays 16 px: stretching it on copy blocks its edges.
        assert entry.image is not None and entry.image.size == 16 and any(entry.image.bgra[3::4])
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


def click_icon(button: QtWidgets.QWidget, index: int, count: int, which: QtCore.Qt.MouseButton) -> None:
    """Click the stacked icon at `index` of `count`, at its centre."""
    first = (button.width() - STACK_STEP * (count - 1)) / 2
    QTest.mouseClick(button, which, QtCore.Qt.KeyboardModifier.NoModifier, QtCore.QPoint(round(first + STACK_STEP * index), button.height() // 2))


def test_pager_icons_route_clicks_to_their_app_and_keep_overflow_reachable() -> None:
    # Defects: a click on a stacked icon reaches its neighbour's app, a right
    # click loses its kind, an empty desktop other than the current one still
    # takes room, or excess desktops disappear instead of remaining scrollable.
    app = application()
    parent = QtWidgets.QWidget()
    parent.resize(600, 50)
    sections = ShellSections(parent)
    clicked: list[tuple[App, Click]] = []
    jumped: list[Navigation] = []
    many = tuple((Program(f"app{index}.exe"),) for index in range(14))
    view = pager(((WorkspaceView.CANVAS,), (PinnedApp.OUTLOOK, PinnedApp.TEAMS, TERMINAL), (), *many), 0, chord=False)
    sections.desktops(view, jumped.append, lambda each, click: clicked.append((each, click)))
    sections.place(250, 600)
    parent.show()
    app.processEvents()
    try:
        canvas, apps = sections.pager.buttons[0], sections.pager.buttons[1]
        click_icon(canvas, 0, 1, QtCore.Qt.MouseButton.LeftButton)
        click_icon(apps, 0, 3, QtCore.Qt.MouseButton.LeftButton)
        click_icon(apps, 2, 3, QtCore.Qt.MouseButton.RightButton)
        click_icon(apps, 1, 3, QtCore.Qt.MouseButton.LeftButton)
        assert clicked == [
            (WorkspaceView.CANVAS, Click.LEFT),
            (PinnedApp.OUTLOOK, Click.LEFT),
            (TERMINAL, Click.RIGHT),
            (PinnedApp.TEAMS, Click.LEFT),
        ]
        assert not jumped
        # The empty third desktop isn't the current one, so it's left out.
        assert len(sections.pager.buttons) == 2 + len(many)
        assert sections.pager.overflow.horizontalScrollBar().maximum() > 0
        sections.pager.overflow.horizontalScrollBar().setValue(sections.pager.overflow.horizontalScrollBar().maximum())
        app.processEvents()
        assert (
            sections.pager.buttons[-1].geometry().right() - sections.pager.overflow.horizontalScrollBar().value()
            < sections.pager.overflow.viewport().width()
        )
        assert sections.pager.geometry().right() < 250
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
    sections.desktops(pager(((WorkspaceView.CANVAS,), (TERMINAL,)), 0, chord=False), lambda _: None, lambda _app, _click: None)
    sections.place(250, 600)
    sections.pager.apply_look(look(appearance.Material.GLASS, Capsule(appearance.Frost.SMOKED), Tint.NONE))
    parent.show()
    app.processEvents()
    try:
        assert sections.pager.grab().toImage().pixelColor(3, 17).alpha() <= 1
        sections.pager.apply_look(look(appearance.Contrast("#ffffff", "#000000"), Capsule(appearance.Frost.SMOKED), Tint.NONE))
        app.processEvents()
        pixel = sections.pager.grab().toImage().pixelColor(3, 17)
        assert (pixel.red(), pixel.green(), pixel.blue(), pixel.alpha()) == (255, 255, 255, 255)
    finally:
        parent.close()
        parent.deleteLater()
        app.processEvents()


def ink(image: QtGui.QImage) -> tuple[int, int]:
    """The width and height, in device pixels, of the image's opaque-enough ink."""
    inked = tuple((x, y) for y in range(image.height()) for x in range(image.width()) if image.pixelColor(x, y).alpha() >= 128)
    columns, rows = {x for x, _ in inked}, {y for _, y in inked}
    return (max(columns) - min(columns) + 1, max(rows) - min(rows) + 1) if inked else (0, 0)


def face(button: QtWidgets.QWidget) -> QtGui.QImage:
    """What the window shows under the button, without the default background a lone widget grab paints."""
    return button.window().grab(QtCore.QRect(button.mapTo(button.window(), QtCore.QPoint(0, 0)), button.size())).toImage()


def test_shell_faces_keep_the_bar_symbol_size_and_sit_concentric_inside_the_workspace_process() -> None:
    # Defects: a stylesheet squeezes a pager digit, an application's bitmap in
    # a desktop's stack paints larger than the bar's 16 px symbols, or the first
    # control loses its concentric 3 px inset.
    ui = Ui()
    parent = QtWidgets.QWidget()
    parent.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
    parent.resize(1200, 50)
    sections = ShellSections(parent)
    chosen = look(appearance.Material.GLASS, Capsule(appearance.Frost.SMOKED), Tint.NONE)
    editor = Application("editor.exe", (Window(1, "Editor", "editor.exe", minimized=False),), image=Pixels(40, bytes((80, 160, 240, 255)) * 1600))
    sections.applications((Shelf(EMPTY_SHELF.pinned, (editor,)), 0))
    sections.desktops(pager(((Program("editor.exe"),), (), ()), 2, chord=False), lambda _: None, lambda _app, _click: None)
    sections.place(800, 1200)
    for section in sections.sections():
        section.apply_look(chosen)
    parent.show()
    application().processEvents()
    try:
        scale = parent.devicePixelRatioF()
        side = round(16 * scale)
        ink_colour = QtGui.QColor(chosen.lettering.ink.color)
        digit = QtGui.QImage(round(32 * scale), round(32 * scale), QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        digit.setDevicePixelRatio(scale)
        digit.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(digit)
        painter.setFont(page_font())
        painter.setPen(ink_colour)
        painter.drawText(QtCore.QRectF(0, 0, 32, 32), QtCore.Qt.AlignmentFlag.AlignCenter, "3")
        painter.end()
        # The editor's desktop, then the current, empty third desktop by its number.
        editor_desktop, three = sections.pager.buttons
        for (width, height), (expected_width, expected_height) in ((ink(face(three)), ink(digit)), (ink(face(editor_desktop)), (side, side))):
            assert abs(width - expected_width) <= 1 and abs(height - expected_height) <= 1, (width, height, expected_width, expected_height)
        assert [section.buttons[0].mapTo(section, QtCore.QPoint(0, 0)) for section in sections.sections()] == [QtCore.QPoint(3, 3)]
    finally:
        parent.close()
        parent.deleteLater()
        ui.close()
        ui.run()


def test_a_pager_of_one_desktop_leaves_no_targets_behind() -> None:
    # Defect: building a hidden pager's targets anyway leaves them in the
    # section, unplaced, until it shows and they stack over its first target.
    app = application()
    parent = QtWidgets.QWidget()
    parent.resize(600, 50)
    sections = ShellSections(parent)
    sections.desktops(pager(((),), 0, chord=False), lambda _: None, lambda _app, _click: None)
    sections.desktops(pager(((TERMINAL,), (EDGE,), ()), 0, chord=False), lambda _: None, lambda _app, _click: None)
    sections.place(12, 600)
    parent.show()
    app.processEvents()
    try:
        body = sections.pager.body
        shown = [child for child in body.findChildren(QtWidgets.QAbstractButton) if child.isVisibleTo(body)]
        assert len(shown) == len(sections.pager.buttons) and set(shown) == set(sections.pager.buttons)
    finally:
        parent.close()
        parent.deleteLater()
        app.processEvents()
