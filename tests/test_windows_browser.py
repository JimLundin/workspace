"""Installed Edge runs real DOM actions in an isolated persistent profile."""

import json
import shutil
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast
from unittest import TestCase

if sys.platform != "win32":
    raise unittest.SkipTest("Native Edge browser automation")

import msvcrt

lazy from PySide6.QtGui import QImage

from assistant.browser import MAX_OUTPUT, Browser
from assistant.browser_session import read_endpoint
from assistant.browser_values import BrowserError, Group, InterruptedError, Tab
from assistant.qt_runtime import prepare
from automation.json_value import Json
from tests.browser_fixture import fixture
from tests.native_browser_fixture import borrowed, disposable, dispose, request
from tests.native_browser_tabs import verify_native_tabs
from tests.native_business_apps import verify_business_apps
from tests.native_communications_browser import NativeTrace, verify_communications
from tests.test_browser import command, decoded, group_of, tab_of

prepare()


def control(page: dict[str, Json], name: str) -> str:
    controls = page["controls"]
    assert isinstance(controls, list)
    row = next(row for row in controls if isinstance(row, dict) and row["name"] == name)
    return cast(str, row["id"])


def act(browser: Browser, target: str, page: dict[str, Json], name: str, action: str, **args: Json) -> None:
    browser.request(command("action", **{"target_id": target, "id": control(page, name), "action": action, **args}), threading.Event())


def test_disposable_browser_fixture_waits_for_late_native_profile_release(tmp_path: Path) -> None:
    browser = Browser(tmp_path / "profile")
    browser.profile.mkdir()
    stream = (browser.profile / "dictionary.bdic").open("wb")
    denied = threading.Event()
    remove = shutil.rmtree

    def release() -> None:
        assert denied.wait(3)
        stream.close()

    def observed_remove(path: Path) -> None:
        try:
            remove(path)
        except PermissionError:
            denied.set()
            raise

    worker = threading.Thread(target=release)
    worker.start()
    try:
        dispose(browser, observed_remove)
        assert denied.is_set() and not browser.profile.exists()
    finally:
        denied.set()
        worker.join(timeout=3)
        stream.close()


def test_disposable_browser_fixture_reports_persistent_cleanup_failure(tmp_path: Path) -> None:
    browser = Browser(tmp_path / "profile")
    attempts: tuple[Path, ...] = ()

    def refuse(path: Path) -> None:
        nonlocal attempts
        attempts += (path,)
        raise PermissionError("Fixture profile remains inaccessible.")

    with TestCase().assertRaisesRegex(PermissionError, "remains inaccessible"):
        dispose(browser, refuse)
    assert attempts == (browser.profile,) * 7


def test_endpoint_publication_recovers_after_a_native_file_lock(tmp_path: Path) -> None:
    with (tmp_path / "DevToolsActivePort").open("w+b") as stream:
        stream.write(b"12345\n/devtools/browser/fixture\n")
        stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            with TestCase().assertRaises(BrowserError):
                read_endpoint(tmp_path)
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    assert read_endpoint(tmp_path) == "ws://127.0.0.1:12345/devtools/browser/fixture"


def verify_dom_and_saved_profile(browser: Browser, url: str) -> None:
    page = request(browser, "open", url=url)
    target = cast(str, page["target_id"])
    # Opening returns at main-document readiness; iframe controls need the full load event.
    browser.request(
        command(
            "evaluate",
            **{
                "target_id": target,
                "expression": "new Promise(resolve => document.readyState === 'complete' ? resolve(true) : "
                "window.addEventListener('load', () => resolve(true), {once: true}))",
            },
        ),
        threading.Event(),
    )
    assert "fixture-private" not in json.dumps(page)
    act(browser, target, page, "Name", "fill", value='Åäö "literal"')
    act(browser, target, page, "Choice", "select", value="beta")
    act(browser, target, page, "Enabled", "check", checked=True)
    act(browser, target, page, "Save", "click")
    page = request(browser, "snapshot", target_id=target)
    assert 'Åäö "literal":beta:true' in cast(str, page["text"])
    act(browser, target, page, "Shadow action", "click")
    page = request(browser, "snapshot", target_id=target)
    assert page["title"] == "Shadow clicked"
    frames = page["frames"]
    assert isinstance(frames, list)
    frame = next(row for row in frames if isinstance(row, dict) and row["name"] == "embedded")
    inner = request(browser, "snapshot", target_id=target, frame_id=frame["id"])
    act(browser, target, inner, "Frame action", "click", frame_id=frame["id"])
    assert "Frame clicked" in cast(str, request(browser, "snapshot", target_id=target, frame_id=frame["id"])["text"])
    shot = browser.request(command("screenshot", **{"target_id": target}), threading.Event()).image
    assert shot is not None and shot.startswith(b"\x89PNG")
    with TestCase().assertRaisesRegex(BrowserError, "TrustedHTML"):
        browser.request(command("evaluate", **{"target_id": target, "expression": "document.body.innerHTML = '<p>blocked</p>'"}), threading.Event())
    page = request(browser, "snapshot", target_id=target)
    original = control(page, "Save")
    request(browser, "snapshot", target_id=target)
    with TestCase().assertRaisesRegex(BrowserError, "stale"):
        browser.request(command("action", **{"target_id": target, "id": original, "action": "click"}), threading.Event())
    expression = """(() => {
        const text = document.createElement('p'); text.textContent = 'long content '.repeat(2000); document.body.append(text);
        for (let i = 0; i < 150; i++) {
            const b = document.createElement('button'); b.textContent = 'Button ' + i + ' x'.repeat(150); document.body.append(b);
        }
        return true;
    })()"""
    browser.request(command("evaluate", **{"target_id": target, "expression": expression}), threading.Event())
    output = browser.request(command("snapshot", **{"target_id": target, "limit": 100}), threading.Event()).text
    assert len(output) <= MAX_OUTPUT
    first = decoded(output)
    second = request(browser, "snapshot", target_id=target, offset=first["next_control_offset"], text_offset=first["next_text_offset"])
    assert second["offset"] == first["next_control_offset"] and second["text_offset"] == first["next_text_offset"]
    assert first["controls"] != second["controls"]
    process = browser.process
    browser.close()
    assert process is not None and process.poll() is not None
    page = request(browser, "open", url=url)
    saved = browser.request(command("evaluate", **{"target_id": page["target_id"], "expression": "localStorage.getItem('saved')"}), threading.Event())
    assert cast(Json, json.loads(saved.text)) == 'Åäö "literal":beta:true'


def verify_managed_cancellation(browser: Browser) -> None:
    cancel = threading.Event()
    try:
        page = request(browser, "open", url="about:blank")
        process = browser.process
        with ThreadPoolExecutor(max_workers=1) as worker:
            pending = worker.submit(browser.request, command("evaluate", target_id=page["target_id"], expression="new Promise(() => {})"), cancel)
            time.sleep(0.15)
            started = time.monotonic()
            cancel.set()
            with TestCase().assertRaises(InterruptedError):
                pending.result(timeout=8)
            assert time.monotonic() - started < 6
        assert process is not None and process.poll() is not None and browser.connection is None
    finally:
        cancel.set()


def test_managed_browser_dom_teams_persistence_and_cancellation(tmp_path: Path) -> None:
    profile = tmp_path / "managed-profile"
    trace = NativeTrace(profile)
    with disposable(Browser(profile, opener=trace)) as browser:
        with fixture() as url:
            verify_dom_and_saved_profile(browser, url)
        verify_communications(browser, trace)
        verify_business_apps(browser)
        # Defect: the dedicated profile accepts synced or pushed extensions,
        # which open tabs and script the pages Workspace automates. Managed
        # Edge installs one within seconds of launch when extensions run.
        assert not (profile / "Default" / "Extensions").exists()
        # Cancellation terminates the shared process, so it must run last.
        verify_managed_cancellation(browser)


def test_visible_sign_in_handoff_reuses_only_the_dedicated_profile(tmp_path: Path) -> None:
    with disposable(Browser(tmp_path / "sign-in-profile")) as browser, fixture() as url:
        visible = request(browser, "sign_in", url=url)
        assert visible["mode"] == "sign_in"
        result = request(browser, "open", url=url, target_id=visible["target_id"])
        assert result["title"] == "Workspace browser fixture"
        assert request(browser, "tabs")["mode"] == "background"


def verify_inactive_screenshots(browser: Browser, target: str, identity: int) -> None:
    """Check real repaint and native selection/group restoration on an attached tab."""

    def state() -> tuple[frozenset[int], Tab, Group]:
        view = request(browser, "tabs", view="strip", limit=40)
        rows, groups = view["tabs"], view["groups"]
        assert isinstance(rows, list) and isinstance(groups, list)
        tabs = tuple(tab_of(row) for row in rows)
        current = next(tab for tab in tabs if tab.id == identity)
        native_groups = tuple(group_of(row) for row in groups)
        group = next(group for group in native_groups if group.id == current.group_id)
        return frozenset(tab.id for tab in tabs if tab.active), current, group

    active, before, group = state()
    assert active and not before.active and group.collapsed
    for color in ((255, 0, 0), (0, 0, 255)):
        css = f"rgb({color[0]}, {color[1]}, {color[2]})"
        expression = """(() => {
            document.body.replaceChildren();
            document.documentElement.style.backgroundColor = COLOR;
            document.body.style.cssText = 'margin:0;min-height:100vh;background:' + COLOR;
            return document.visibilityState;
        })()""".replace("COLOR", json.dumps(css))
        painted = browser.request(command("evaluate", **{"target_id": target, "expression": expression}), threading.Event())
        visibility = cast(Json, json.loads(painted.text))
        assert visibility in ("hidden", "visible")
        shot = browser.request(command("screenshot", **{"target_id": target}), threading.Event()).image
        assert shot is not None
        restored = browser.request(command("evaluate", **{"target_id": target, "expression": "document.visibilityState"}), threading.Event())
        assert cast(Json, json.loads(restored.text)) == visibility
        image = QImage()
        assert image.loadFromData(shot)
        assert not image.isNull() and image.width() >= 4 and image.height() >= 4
        for x, y in ((1, 1), (3, 1), (2, 2), (1, 3), (3, 3)):
            pixel = image.pixelColor(image.width() * x // 4, image.height() * y // 4).getRgb()
            assert pixel == (*color, 255), (color, x, y, pixel)
        current_active, current, current_group = state()
        assert current_active == active and not current.active
        assert current.group_id == before.group_id and current_group == group


def verify_attached_dom(personal: Browser, attached: Browser, url: str) -> None:
    original = request(personal, "open", url=url)
    personal.request(
        command("evaluate", **{"target_id": original["target_id"], "expression": "localStorage.setItem('fixture-session', 'already-signed-in')"}),
        threading.Event(),
    )
    blank = request(personal, "open", url="about:blank")
    assert request(attached, "attach")["mode"] == "attached"
    connection = attached.connection
    page = request(attached, "open", url=url)
    target = cast(str, page["target_id"])
    assert target not in (original["target_id"], blank["target_id"]) and attached.connection is connection
    value = attached.request(command("evaluate", **{"target_id": target, "expression": "localStorage.getItem('fixture-session')"}), threading.Event())
    assert cast(Json, json.loads(value.text)) == "already-signed-in"
    act(attached, target, page, "Name", "fill", value="Attached fixture")
    act(attached, target, page, "Save", "click")
    assert "Attached fixture" in cast(str, request(attached, "snapshot", target_id=target)["text"])
    shot = attached.request(command("screenshot", **{"target_id": target}), threading.Event()).image
    assert shot is not None and shot.startswith(b"\x89PNG")
    # Repaint the same attached, inactive tab without changing user selection.
    inactive_target, identity = page["target_id"], page["tab_id"]
    assert isinstance(inactive_target, str) and isinstance(identity, int)

    verify_inactive_screenshots(attached, inactive_target, identity)

    assert "remain open" in attached.request(command("close"), threading.Event()).text
    rows = request(personal, "tabs")["tabs"]
    assert isinstance(rows, list)
    tabs = [tab for tab in rows if isinstance(tab, dict)]
    assert {cast(str, original["target_id"]), cast(str, blank["target_id"]), target} <= {cast(str, tab["id"]) for tab in tabs}
    assert next(tab for tab in tabs if tab["id"] == blank["target_id"])["url"] == "about:blank"
    assert personal.process is not None and personal.process.poll() is None
    assert not attached.profile.exists()
    # Detach preserves the created tab; explicitly remove it before the next
    # scenario so native tab/group baselines contain only the two personal tabs.
    request(personal, "close", target_id=target)


def verify_attached_cancellation(personal: Browser, attached: Browser) -> None:
    cancel = threading.Event()
    try:
        tabs = request(personal, "tabs")["tabs"]
        assert isinstance(tabs, list)
        blank = next(tab for tab in tabs if isinstance(tab, dict) and tab["url"] == "about:blank")
        page = request(personal, "snapshot", target_id=blank["id"])
        request(attached, "attach")
        with ThreadPoolExecutor(max_workers=1) as worker:
            pending = worker.submit(attached.request, command("evaluate", target_id=page["target_id"], expression="new Promise(() => {})"), cancel)
            time.sleep(0.15)
            cancel.set()
            with TestCase().assertRaises(InterruptedError):
                pending.result(timeout=3)
        assert attached.connection is None and personal.process is not None and personal.process.poll() is None
        assert request(personal, "snapshot", target_id=page["target_id"])["url"] == "about:blank"
    finally:
        cancel.set()


def test_attached_browser_dom_tabs_and_cancellation_share_a_personal_browser(tmp_path: Path) -> None:
    with disposable(Browser(tmp_path / "fixture-personal")) as personal, fixture() as url:
        with borrowed(personal) as attached:
            verify_attached_dom(personal, attached, url)
        process = personal.process
        assert process is not None and process.poll() is None
        with borrowed(personal) as attached:
            verify_native_tabs(personal, attached, url)
        assert personal.process is process and process.poll() is None
        with borrowed(personal) as attached:
            verify_attached_cancellation(personal, attached)
