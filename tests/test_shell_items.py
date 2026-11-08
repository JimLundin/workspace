"""The shelf's grouping, slots, launches and captions, and the tray host's wire packing."""

from dataclasses import replace

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
from winapi.shapes import Point, Rect, Window
from winapi.tray_host import Click, Entry, Notify, Registration, callbacks, registration, update


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


def test_tray_version_four_packs_identity_and_signed_screen_coordinates() -> None:
    # Defect: Workspace sends the legacy callback arguments after version negotiation.
    entry = Entry(1, 17, b"", 0x8001, None, "Tray", version=4)
    assert callbacks(entry, Click.LEFT, Point(-20, 40)) == tuple(Notify(0x0028FFEC, (17 << 16) | event) for event in (0x201, 0x202, 0x400))
    assert callbacks(entry, Click.RIGHT, Point(20, -40))[-1] == Notify(0xFFD80014, (17 << 16) | 0x7B)
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
