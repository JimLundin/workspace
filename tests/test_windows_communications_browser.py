"""Exact-chat Teams automation against fictional local DOMs in an isolated Edge."""

import json
import sys
import threading
import unittest
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

if sys.platform != "win32":
    raise unittest.SkipTest("Native Teams DOM fixture")

from assistant.browser import Browser, BrowserResult
from assistant.browser_session import BrowserConnection, BrowserSession, NativeSessions, Owner, Source
from assistant.browser_values import BrowserError
from assistant.communications import SourceDate, SourceDateHint, SourceDateStatus, TeamsActivity, UpdateKind
from assistant.communications_browser import TeamsWeb
from assistant.llm import Json
from tests.browser_fixture import fixture
from tests.test_windows_browser import dispose, installed, request

# Fixture-only private CDP calls preserve real freeze/launcher recovery without
# navigating an account page. Narrow annotations below acknowledge that access.

PAGE = """<!doctype html><meta charset="utf-8"><title>Fictional Teams fixture</title>
<div role="treeitem" data-item-type="chat" data-fui-tree-item-value="chat-19:one@thread.v2">Same title</div>
<div role="treeitem" data-item-type="chat" data-fui-tree-item-value="chat-19:two@thread.v2">Same title</div>
<div data-tid="chat-title">Same title</div><div id="messages"></div>
<div data-tid="ckeditor" contenteditable="true" role="textbox"></div>
<button data-tid="sendMessageCommands-send" data-track-thread-id="19:one@thread.v2">Send</button>
<script>
const send=document.querySelector('button'), editor=document.querySelector('[contenteditable]');
let current='19:one@thread.v2', next=1700000000010;
const logs={
  '19:one@thread.v2':[{id:'1700000000000',author:'Anna',text:'First chat: **plain** source Åäö'}],
  '19:two@thread.v2':[{id:'1700000000000',author:'Sam',text:'Second chat with the same title'}]
};
const sent=[];
function render() {
  const pane=document.querySelector('#messages'); pane.replaceChildren();
  send.setAttribute('data-track-thread-id',current);
  for(const item of logs[current]) {
    const row=document.createElement('div'); row.setAttribute('data-mid',item.id);
    row.setAttribute('data-tid','chat-pane-message');
    const author=document.createElement('span'); author.setAttribute('data-tid','message-author-name'); author.textContent=item.author;
    const body=document.createElement('div'); body.id='content-'+item.id; body.textContent=item.text; body.style.whiteSpace='pre-wrap';
    row.append(author,body);pane.append(row);
  }
}
for(const row of document.querySelectorAll('[role=treeitem]')) row.onclick=()=>{
  current=row.getAttribute('data-fui-tree-item-value').slice(5); editor.textContent=''; render();
};
send.onclick=()=>{
  const text=editor.innerText.trim(); if(!text)return;
  sent.push({chat:current,text}); logs[current].push({id:String(next++),author:'You',text});
  document.body.dataset.sent=JSON.stringify(sent);
  editor.textContent='';render();
};
render();
</script>"""


class FixtureBrowser:
    """Adapt Teams addresses to a local app while retaining real browser effects.

    The fixture owns a chronological request trace for navigation assertions;
    immutable observations leave that owner. The native Browser owns its process.
    """

    __slots__ = ("browser", "origin", "requests")

    def __init__(self, browser: Browser, origin: str = "") -> None:
        self.browser = browser
        self.origin = origin
        self.requests: tuple[tuple[str, frozendict[str, Json]], ...] = ()

    @property
    def connection(self) -> BrowserConnection | None:
        return self.browser.connection

    @property
    def owner(self) -> Owner:
        return self.browser.owner

    def connect(self, cancel: threading.Event, *, visible: bool = False) -> None:
        self.browser.connect(cancel, visible=visible)

    def awake(self, target: str, cancel: threading.Event) -> AbstractContextManager[None]:
        return self.browser.awake(target, cancel)

    def activate_page(self, target: str, cancel: threading.Event) -> None:
        self.browser.activate_page(target, cancel)

    def request(self, operation: str, args: dict[str, Json], cancel: threading.Event) -> BrowserResult:
        self.requests += ((operation, frozendict(args)),)
        if operation == "open" and str(args.get("url", "")).startswith("https://teams.cloud.microsoft/l/chat/"):
            args = {**args, "url": self.origin + "dl/launcher/launcher.html"}
        result = self.browser.request(operation, args, cancel)
        if operation == "tabs":
            # Only catalog addresses cross the adapter; DOM reads and native
            # activation still exercise the real isolated browser connection.
            data = cast(dict[str, Json], json.loads(result.text))
            rows = cast(list[dict[str, Json]], data["tabs"])
            data = {**data, "tabs": [{**row, "url": "https://teams.cloud.microsoft/v2/"} for row in rows]}
            return BrowserResult(json.dumps(data), result.image)
        return result

    def close(self) -> None:
        self.browser.close()


class NativeTrace:
    """Observe native commands through the browser's existing connection seam."""

    __slots__ = ("commands", "sessions")

    def __init__(self, profile: Path) -> None:
        self.sessions = NativeSessions(profile)
        # The fixture owns the ordered native command evidence; only this
        # browser contributes to the observation.
        self.commands: tuple[tuple[str, frozendict[str, Json]], ...] = ()

    def open(self, source: Source, cancel: threading.Event, *, visible: bool = False) -> BrowserSession:
        native = self.sessions.open(source, cancel, visible=visible)
        return BrowserSession(TracedConnection(native.connection, self), native.owner)


class TracedConnection:
    __slots__ = ("connection", "trace")

    def __init__(self, connection: BrowserConnection, trace: NativeTrace) -> None:
        self.connection = connection
        self.trace = trace

    # The native protocol requires method, parameters, cancellation, session and
    # deadline together; this adapter preserves its complete calling contract.
    def call(self, method: str, params: dict[str, Json], cancel: threading.Event, *, session: str = "", timeout: float = 15) -> dict[str, Json]:
        self.trace.commands += ((method, frozendict(params)),)
        return self.connection.call(method, params, cancel, session=session, timeout=timeout)

    def close(self) -> None:
        self.connection.close()


def close_fixture(web: TeamsWeb, browser: Browser) -> None:
    """Release only the exact native process launched by this fixture.

    Preserve a failed normal close as a test failure, while still attempting
    owned-process cleanup and profile removal before the next scenario runs.
    """
    process = browser.process
    try:
        web.close()
    except Exception as primary:
        # The job already requested termination. A second kill can return
        # access denied while native exit is pending and hide the first failure.
        if process is not None:
            try:
                process.wait(timeout=10)
            except Exception as error:
                primary.add_note(f"The captured browser root did not finish exiting: {error}")
        try:
            dispose(browser)
        except Exception as error:
            primary.add_note(f"The disposable browser profile could not be removed: {error}")
        raise
    else:
        dispose(browser)


ACTIVITY_PAGE = """<!doctype html><meta charset="utf-8"><title>Fictional Teams Activity</title>
<div data-tid="activity-list-container">
<div data-tid="activity-feed-list-item-wrap" id="123">
 <div data-tid="activity-feed-list-item" role="option">
  <span data-tid="activity-feed-item-activity-icon-123" title="Like"></span>
  <span data-tid="activity-feed-item-title">Anna reacted</span>
  <span id="activity-feed-item-message-preview-123">Ready **literal text** Åäö</span>
  <span id="activity-feed-item-timestamp-123" datetime="2026-10-20T09:30:00+02:00">09:30</span>
  <span id="activity-feed-item-location-123">Planning</span>
  <button id="activity-feed-item-context-menu-123">More</button>
 </div>
</div>
<div data-tid="activity-feed-list-item-wrap" id="456">
 <div data-tid="activity-feed-list-item" role="option">
  <span data-tid="activity-feed-item-title">Meeting invitation</span>
  <span id="activity-feed-item-message-preview-456">Release discussion</span>
 </div>
</div>
</div><div id="portal"></div>
<script>
let unread=true, toggles=0;
function menu(){const item=document.createElement('button');item.setAttribute('role','menuitem');item.setAttribute('data-tid','toggleActivityRead');
 item.textContent=unread?'Mark as read':'Mark as unread';document.getElementById('portal').replaceChildren(item);
 item.onclick=()=>{unread=!unread;toggles++;document.body.dataset.toggles=String(toggles);
 document.getElementById('portal').replaceChildren()}}
document.querySelector('#activity-feed-item-context-menu-123').onclick=menu;
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('portal').replaceChildren()});
</script>"""


def test_activity_identity_read_action_and_relative_clock_changes_are_verified_in_a_native_browser(tmp_path: Path) -> None:
    installed()
    cancel = threading.Event()
    browser = Browser(tmp_path / "activity-profile")
    web = TeamsWeb(tmp_path / "unused", browser=browser)
    try:
        with fixture(ACTIVITY_PAGE) as url:
            opened = request(browser, "open", url=url)
            web.target = cast(str, opened["target_id"])
            first = web.activity(cancel)
            assert len(first.items) == 2
            assert isinstance(first.items[0].source, TeamsActivity)
            assert first.items[0].source.identity == "123"
            assert first.items[0].text == "Like\nReady **literal text** Åäö\nPlanning"
            assert first.items[0].kind is UpdateKind.REACTION and first.items[1].kind is UpdateKind.INVITATION
            assert first.items[0].source_time == SourceDate(datetime(2026, 10, 20, 7, 30, tzinfo=UTC).timestamp())
            assert first.items[1].source_time is SourceDateStatus.UNKNOWN
            web.evaluate("(() => {document.querySelector('[id^=activity-feed-item-timestamp]').textContent='Yesterday';return true})()",
                         cancel, target=web.target)
            changed = web.activity(cancel).items[0]
            assert changed.text == first.items[0].text and changed.source_time == first.items[0].source_time
            web.evaluate("(() => {document.querySelector('[id^=activity-feed-item-timestamp]').removeAttribute('datetime');return true})()",
                         cancel, target=web.target)
            relative = web.activity(cancel).items[0]
            match relative.source_time:
                case SourceDateHint('Yesterday', observed_on):
                    assert observed_on == datetime.fromtimestamp(relative.created_at, UTC).astimezone().date()
                case _:
                    raise AssertionError('A relative Teams date must remain evidence rather than becoming collected today.')
            assert web.activity_read("123", cancel)
            assert web.evaluate("document.body.dataset.toggles", cancel, target=web.target) == "1"
            assert web.activity_read("123", cancel)
            assert web.evaluate("document.body.dataset.toggles", cancel, target=web.target) == "1"
            assert not web.activity_read("999", cancel)
    finally:
        close_fixture(web, browser)


def test_activity_source_opens_the_exact_saved_page_after_native_tab_metadata_is_lost(tmp_path: Path) -> None:
    installed()
    cancel = threading.Event()
    profile = tmp_path / "activity-reopen-profile"
    trace = NativeTrace(profile)
    browser = Browser(profile, opener=trace)
    web = TeamsWeb(tmp_path / "unused", browser=browser)
    try:
        with fixture(ACTIVITY_PAGE) as url:
            opened = request(browser, "open", url=url)
            web.target = cast(str, opened["target_id"])
            assert browser.connection is not None
            browser.connection.call("Target.createTarget", {"url": "about:blank"}, cancel)
            browser.native_targets.clear()
            web.open_activity("123", cancel)
            assert ("Target.activateTarget", {"targetId": web.target}) in trace.commands
    finally:
        close_fixture(web, browser)


def test_observation_reply_binding_and_inspection_use_isolated_fictional_chats(tmp_path: Path) -> None:
    installed()
    cancel = threading.Event()
    browser = Browser(tmp_path / "isolated-profile")
    web = TeamsWeb(tmp_path / "unused", browser=FixtureBrowser(browser))
    try:
        with fixture(PAGE) as url:
            first = request(browser, "open", url=url)
            web.target = cast(str, first["target_id"])
            web.evaluate("(() => { const nodes=[...document.body.childNodes]; document.body.replaceChildren();"
                         " setTimeout(()=>document.body.replaceChildren(...nodes),1000); return true; })()", cancel)
            read = web.select("19:one@thread.v2", cancel)
            assert len(read.conversations) == 2
            assert read.messages[0].sender == "Anna"
            assert read.messages[0].text == "First chat: **plain** source Åäö"
            web.opening[web.target] = "19:unavailable@thread.v2"
            second = web.select("19:two@thread.v2", cancel)
            assert web.opening == {}
            assert read.messages[0].identity == second.messages[0].identity
            assert read.messages[0].key != second.messages[0].key
            assert second.messages[0].sender == "Sam"
            text = 'Exact reply Åäö "quoted"\nA second line.'
            posted = web.send("19:two@thread.v2", text, cancel)
            assert len(posted) == 1 and posted[0].text == text
            assert posted[0].conversation == "19:two@thread.v2"
            assert web.evaluate("JSON.parse(document.body.dataset.sent)", cancel) == [{"chat": "19:two@thread.v2", "text": text}]
            assert web.browser.connection is not None
            connection = web.browser.connection
            web.read(cancel)
            assert web.browser.connection is connection

            # A nonempty source editor must never be replaced or posted.
            web.evaluate("document.querySelector('[contenteditable]').textContent='Existing source draft'", cancel)
            with unittest.TestCase().assertRaisesRegex(BrowserError, "draft"):
                web.send("19:two@thread.v2", "Must not be sent", cancel)
            assert web.evaluate("JSON.parse(document.body.dataset.sent).length", cancel) == 1

            original_target = web.target
            web.open("19:one@thread.v2", cancel)
            assert web.target == original_target
            assert web.read(cancel).current == "19:one@thread.v2"

            # Changing the route while text is inserted must stop before Send.
            web.evaluate("(() => { const editor=document.querySelector('[contenteditable]'); editor.textContent='';"
                         " editor.addEventListener('input',()=>document.querySelector('button')"
                         ".setAttribute('data-track-thread-id','19:one@thread.v2'),{once:true}); return true; })()", cancel)
            with unittest.TestCase().assertRaisesRegex(BrowserError, "prepared"):
                web.send("19:two@thread.v2", "Route changed", cancel)
            assert web.evaluate("JSON.parse(document.body.dataset.sent).length", cancel) == 1
    finally:
        close_fixture(web, browser)


def test_chat_navigation_recovers_activity_frozen_pages_and_exact_launcher_destination(tmp_path: Path) -> None:
    installed()
    cancel = threading.Event()
    browser = Browser(tmp_path / "isolated-profile")
    activity = PAGE + """<div data-tid="app-layout-area--nav"><button aria-label="Chat" id="restore-chats">Chat</button></div>
            <script>
            const chatRows=[...document.querySelectorAll('[role=treeitem]')];
            for(const row of chatRows) row.remove();
            let navigation=0;
            document.querySelector('#restore-chats').onclick=()=>{
              navigation++;document.body.dataset.navigation=String(navigation);
              setTimeout(()=>{for(const row of chatRows)document.body.append(row);},300);
            };
            </script>"""
    empty = PAGE + """<div data-tid="app-layout-area--nav"><button aria-label="Chat" id="chat-nav">Chat</button></div>
            <script>
            const sidebar=[...document.querySelectorAll('[role=treeitem]')];
            for(const row of sidebar)row.remove();
            editor.remove();send.setAttribute('data-track-thread-id','');document.querySelector('#messages').replaceChildren();
            document.querySelector('#chat-nav').onclick=()=>setTimeout(()=>{
              for(const row of sidebar)document.body.append(row);
              document.body.append(editor);render();
            },300);
            </script>"""
    launcher = PAGE + """<button id="openTeamsClientInBrowser">Continue in this browser</button><script>
            if(location.pathname==='/dl/launcher/launcher.html'){
              for(const row of document.querySelectorAll('[role=treeitem]'))row.remove();
              editor.remove();send.setAttribute('data-track-thread-id','');document.querySelector('#messages').replaceChildren();
              document.querySelector('#openTeamsClientInBrowser').onclick=()=>location.assign('/?chat=two');
            }else if(new URLSearchParams(location.search).get('chat')==='two'){
              current='19:two@thread.v2';render();
              document.querySelector('#openTeamsClientInBrowser').remove();
            }</script>"""
    delayed = PAGE.replace("editor.textContent=''; render();", "editor.textContent='';setTimeout(render,300);")
    # Static routes give each navigation its own document while one native
    # process and server retain ownership across the recovery scenarios.
    with fixture(launcher, pages={"/activity": activity, "/delayed": delayed, "/empty": empty}) as url:
        adapter = FixtureBrowser(browser, url)
        web = TeamsWeb(tmp_path / "unused", browser=adapter)
        try:
            opened = request(browser, "open", url=url + "activity")
            web.target = cast(str, opened["target_id"])
            assert len(web.read(cancel).conversations) == 1
            second = web.select("19:two@thread.v2", cancel)
            assert second.current == "19:two@thread.v2" and second.messages[0].sender == "Sam"
            web.evaluate("(() => {for(const row of document.querySelectorAll('[role=treeitem]'))row.remove();return true;})()", cancel)
            first = web.select("19:one@thread.v2", cancel)
            assert first.current == "19:one@thread.v2"
            assert web.evaluate("document.body.dataset.navigation", cancel) == "2"

            opened = request(browser, "open", url=url + "delayed", target_id=web.target)
            web.target = cast(str, opened["target_id"])
            session = browser._session(web.target, cancel)  # pyright: ignore[reportPrivateUsage]
            browser._call("Page.setWebLifecycleState", {"state": "frozen"}, cancel, session=session)  # pyright: ignore[reportPrivateUsage]
            second = web.select("19:two@thread.v2", cancel)
            assert second.current == "19:two@thread.v2" and second.messages[0].sender == "Sam"

            opened = request(browser, "open", url=url + "empty", target_id=web.target)
            web.target = cast(str, opened["target_id"])
            assert web.read(cancel).current == ""
            found = web.discover(cancel)
            assert len(found.conversations) == 2 and found.current == "19:one@thread.v2"
            assert web.select("19:two@thread.v2", cancel).messages[0].sender == "Sam"

            opened = request(browser, "open", url=url, target_id=web.target)
            web.target = cast(str, opened["target_id"])
            with browser.awake(web.target, cancel):
                restored = web._reopen("19:two@thread.v2", cancel)  # pyright: ignore[reportPrivateUsage]
            assert ("open", {"target_id": web.target,
                             "url": "https://teams.cloud.microsoft/l/chat/19:two@thread.v2/conversations?webjoin=true"}) in adapter.requests
            assert restored.current == "19:two@thread.v2" and restored.messages[0].sender == "Sam"
            assert web.opening == {}
        finally:
            close_fixture(web, browser)
