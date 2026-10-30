"""Background DOM automation in an attached browser or Workspace's own Edge."""

import base64
import binascii
import sys
import threading
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, assert_never
from urllib.parse import urlsplit

from pydantic import TypeAdapter, ValidationError

from assistant import browser_dom
from assistant.browser_documents import Download, Downloaded, download
from assistant.browser_session import (
    Attached,
    BrowserConnection,
    BrowserSession,
    Managed,
    NativeSessions,
    Owner,
    Process,
    Product,
    Separate,
    SessionOpener,
    Source,
    Stopped,
    setup_message,
    source_of,
)
from assistant.browser_tabs import TabStrip
from assistant.browser_values import (
    MAX_ID,
    ActionOptions,
    BrowserError,
    BrowserStatus,
    ChangeTab,
    ClosedTabsData,
    CloseGroup,
    ClosePage,
    CloseState,
    CloseTabs,
    Closure,
    CreateGroup,
    Destination,
    Disconnect,
    DisconnectedError,
    EditGroup,
    Frame,
    FrameTree,
    GroupData,
    InGroup,
    InterruptedError,
    MoveTab,
    NavigationLoadingError,
    Page,
    PageClosure,
    PageClosureData,
    PageRow,
    Point,
    Rendered,
    SignInPage,
    Snapshot,
    SnapshotOptions,
    StripData,
    TabData,
    TabEdit,
    Ungrouped,
    UngroupedData,
    UngroupTabs,
    closure,
    destination,
    evaluated,
    mapping,
    number,
    opening,
    pages_of,
    strip_page,
    strip_query,
    tab_edit,
    text,
)
from assistant.llm import Json
lazy from assistant.web_apps import Located, WebAppOperation, WebApps

MAX_OUTPUT = 20_000


_SNAPSHOT_OPTIONS = TypeAdapter(SnapshotOptions)
_ACTION_OPTIONS = TypeAdapter(ActionOptions)
_RENDERED = TypeAdapter(Rendered)
_FRAME_TREE = TypeAdapter(FrameTree)
_POINT = TypeAdapter(Point)
_SNAPSHOT = TypeAdapter(Snapshot)
_SIGN_IN = TypeAdapter(SignInPage)
_STATUS = TypeAdapter(BrowserStatus)
_STRIP = TypeAdapter(StripData)
_EDITED = TypeAdapter[GroupData | TabData | UngroupedData](GroupData | TabData | UngroupedData)
_CLOSED_TABS = TypeAdapter(ClosedTabsData)
_CLOSED_PAGE = TypeAdapter(PageClosureData)


def _decoded[T](shape: TypeAdapter[T], value: Json) -> T:
    """Validate a browser observation before any later step relies on it."""
    try:
        return shape.validate_python(value)
    except ValidationError as error:
        raise BrowserError("The browser returned an unexpected page observation.") from error


def _dumped[T](shape: TypeAdapter[T], value: T) -> str:
    return shape.dump_json(value, exclude_none=True).decode()


def _size[T](shape: TypeAdapter[T], value: T) -> int:
    return len(_dumped(shape, value))


def _frames(tree: FrameTree) -> tuple[Frame, ...]:
    """The first 40 frames, breadth first."""
    frames: tuple[Frame, ...] = ()
    pending: tuple[FrameTree, ...] = (tree,)
    while pending and len(frames) < 40:
        branch = pending[0]
        pending = (*pending[1:], *branch.children)
        frames = (*frames, Frame(branch.frame.id, branch.frame.url[:300], branch.frame.name[:100]))
    return frames


def web_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise BrowserError("Use a valid HTTP(S) page URL.") from error
    if value == "about:blank":
        return value
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 32 for c in value):
        raise BrowserError("Use an http(s) page URL without embedded credentials, or about:blank.")
    return value


@dataclass(frozen=True, slots=True)
class BrowserResult:
    text: str
    image: bytes | None = None


class Browser:
    """Own launched processes; borrow a personal browser through its opt-in CDP."""

    __slots__ = ("_live", "_opener", "created", "lock", "native_targets", "profile", "sessions", "source", "strip")

    def __init__(
        self,
        profile: Path,
        *,
        source: Source = Separate.PROFILE,
        executable: Path | None = None,
        opener: SessionOpener | None = None,
        strip: TabStrip | None = None,
    ) -> None:
        self.profile = profile
        self._opener = opener if opener is not None else NativeSessions(profile, executable=executable, persistent=sys.platform == "win32")
        self.source = source
        self._live: BrowserSession | None = None
        self.sessions: dict[str, str] = {}
        self.created: set[str] = set()
        self.native_targets: dict[str, int] = {}
        self.strip = strip if strip is not None else TabStrip()
        self.lock = threading.RLock()

    @property
    def connection(self) -> BrowserConnection | None:
        return self._live.connection if self._live is not None else None

    @property
    def owner(self) -> Owner:
        return self._live.owner if self._live is not None else Stopped.BROWSER

    @property
    def process(self) -> Process | None:
        match self.owner:
            case Managed(process=process):
                return process
            case _:
                return None

    @property
    def visible(self) -> bool:
        match self.owner:
            case Managed(visible=visible):
                return visible
            case _:
                return False

    @property
    def attached(self) -> bool:
        """Workspace borrows the user's own browser rather than owning a process."""
        match self.owner:
            case Attached():
                return True
            case _:
                return False

    def select(self, source: Source) -> None:
        if source != self.source:
            self.close()
            self.source = source

    def _attach(self, product: Product, cancel: threading.Event) -> None:
        if self.owner == Attached(product) and self.connection is not None:
            return
        self.close()
        self._live = self._opener.open(product, cancel)

    def _call(
        self,
        method: str,
        params: dict[str, Json],
        cancel: threading.Event,
        *,
        session: str = "",
        timeout: float = 15,
    ) -> dict[str, Json]:
        if self.connection is None:
            raise BrowserError("The automation browser is stopped. Use browser_open first.")
        return self.connection.call(method, params, cancel, session=session, timeout=timeout)

    def connect(self, cancel: threading.Event, *, visible: bool = False) -> None:
        """Connect the selected source without reading tabs or navigating a page."""
        with self.lock:
            if cancel.is_set():
                raise InterruptedError("Stopped before browser automation.")
            match self.source:
                case Product() as product:
                    self._attach(product, cancel)
                    return
                case _:
                    pass
            if self.process is not None and self.process.poll() is None and self.visible == visible and self.connection is not None:
                return
            self.close()
            self._live = self._opener.open(self.source, cancel, visible=visible)

    def close(self) -> None:
        """Detach personal browsers. Only terminate a process Workspace launched."""
        with self.lock:
            live, self._live = self._live, None
            try:
                if live is not None:
                    live.close()
            finally:
                self.sessions.clear()
                self.created.clear()
                self.native_targets.clear()
                self.strip.control = None

    def _tabs(self, cancel: threading.Event) -> tuple[Page, ...]:
        if self.connection is None:
            return ()
        return pages_of(self._call("Target.getTargets", {}, cancel))

    def _session(self, target: str, cancel: threading.Event) -> str:
        if not target or not any(tab.id == target for tab in self._tabs(cancel)):
            raise BrowserError("That page is closed or is not in the connected browser. Call browser_tabs for current ids.")
        if target not in self.sessions:
            self.sessions[target] = text(self._call("Target.attachToTarget", {"targetId": target, "flatten": True}, cancel), "sessionId")
        return self.sessions[target]

    def _reset_capture(self, session: str, cancel: threading.Event) -> None:
        try:
            self._call("Emulation.setFocusEmulationEnabled", {"enabled": False}, cancel, session=session)
        except BaseException as error:
            # Detaching also releases the browser's temporary visible capturer.
            try:
                self.close()
            except Exception as cleanup_error:
                error.add_note(f"Browser session cleanup also failed: {cleanup_error}")
            raise

    @contextmanager
    def awake(self, target: str, cancel: threading.Event) -> Generator[None]:
        """Resume page work without activating its native tab."""
        with self.lock:
            session = self._session(target, cancel)
            try:
                # Focus emulation changes visibility; a frozen lifecycle needs
                # its own explicit resume before JavaScript and timers run.
                self._call("Page.setWebLifecycleState", {"state": "active"}, cancel, session=session)
                self._call("Emulation.setFocusEmulationEnabled", {"enabled": True}, cancel, session=session)
                yield
            except BaseException as error:
                try:
                    self._reset_capture(session, threading.Event())
                except Exception as cleanup_error:
                    error.add_note(f"Browser activity cleanup also failed: {cleanup_error}")
                raise
            else:
                self._reset_capture(session, threading.Event())

    def _capture(self, session: str, cancel: threading.Event) -> dict[str, Json]:
        try:
            self._call("Emulation.setFocusEmulationEnabled", {"enabled": True}, cancel, session=session)
            result = self._call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}, cancel, session=session)
        except BaseException as error:
            try:
                self._reset_capture(session, cancel)
            except Exception as cleanup_error:
                error.add_note(f"Browser capture cleanup also failed: {cleanup_error}")
            raise
        self._reset_capture(session, cancel)
        return result

    def _world(self, session: str, frame: str, cancel: threading.Event) -> tuple[int, dict[str, Json]]:
        tree = mapping(self._call("Page.getFrameTree", {}, cancel, session=session).get("frameTree", {}))
        if not frame:
            frame = text(mapping(tree.get("frame", {})), "id")
        world = self._call("Page.createIsolatedWorld", {"frameId": frame, "worldName": "workspace"}, cancel, session=session)
        return number(world, "executionContextId", 0, 1, 2**53), tree

    def _evaluate(self, expression: str, session: str, context: int, cancel: threading.Event, *, timeout: float = 15) -> Json:
        result = self._call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "contextId": context,
                "awaitPromise": True,
                "returnByValue": True,
            },
            cancel,
            session=session,
            timeout=timeout,
        )
        return evaluated(result, "JavaScript failed.")

    def _snapshot(self, target: str, args: dict[str, Json], cancel: threading.Event) -> BrowserResult:
        session = self._session(target, cancel)
        context, tree = self._world(session, text(args, "frame_id"), cancel)
        options = SnapshotOptions(
            uuid.uuid4().hex[:10],
            number(args, "offset", 0, 0, 20000),
            number(args, "limit", 60, 1, 100),
            number(args, "text_offset", 0, 0, 10_000_000),
        )
        script = f"{browser_dom.SNAPSHOT}({_SNAPSHOT_OPTIONS.dump_json(options).decode()})"
        rendered = _decoded(_RENDERED, self._evaluate(script, session, context, cancel))
        frames = _frames(_decoded(_FRAME_TREE, tree))
        frame_offset = number(args, "frame_offset", 0, 0, 20000)
        snapshot = Snapshot(
            target,
            self.native_targets.get(target),
            rendered.title,
            rendered.url,
            rendered.text,
            rendered.text_offset,
            rendered.text_total,
            rendered.controls,
            rendered.offset,
            rendered.total,
            frames[frame_offset : frame_offset + 8],
            frame_offset,
            len(frames),
            frame_offset + 8 if frame_offset + 8 < len(frames) else None,
            more_controls=rendered.more_controls,
            scan_limited=rendered.scan_limited,
        )
        while _size(_SNAPSHOT, snapshot) > MAX_OUTPUT - 200 and len(snapshot.controls) > 1:
            snapshot = replace(snapshot, controls=snapshot.controls[:-1], more_controls=True)
        while _size(_SNAPSHOT, snapshot) > MAX_OUTPUT - 200:
            if not snapshot.text:
                raise BrowserError("The page snapshot exceeded the output limit. Request a smaller page section.")
            snapshot = replace(snapshot, text=snapshot.text[: len(snapshot.text) // 2])
        next_text = options.text_offset + len(snapshot.text)
        snapshot = replace(
            snapshot,
            next_control_offset=options.offset + len(snapshot.controls) if snapshot.more_controls else None,
            next_text_offset=next_text if next_text < snapshot.text_total else None,
        )
        return BrowserResult(_dumped(_SNAPSHOT, snapshot))

    def _native_target(self, placement: Destination, window: int | None, cancel: threading.Event) -> str:
        self._require_strip()
        plan = opening(self.strip.snapshot(self._call, cancel), placement, window)
        marker = "about:blank#workspace-" + uuid.uuid4().hex
        native = self.strip.open(self._call, marker, plan, cancel)
        deadline = time.monotonic() + 5
        while True:
            target = next((tab.id for tab in self._tabs(cancel) if tab.url == marker), "")
            if target:
                self.native_targets[target] = native.id
                self.created.add(target)
                return target
            if time.monotonic() >= deadline:
                raise BrowserError(
                    f"Created tab {native.id}, but its page is not available yet. Inspect browser_tabs with view=strip before opening another tab."
                )
            if cancel.wait(0.05):
                raise InterruptedError(f"Stopped after creating tab {native.id}. The tab remains in its group.")

    def _open(self, args: dict[str, Json], cancel: threading.Event, *, visible: bool) -> BrowserResult:
        url = web_url(text(args, "url", "about:blank"))
        requested = text(args, "target_id")
        placement = destination(args)
        window = number(args, "window_id", -1, 0, MAX_ID) if "window_id" in args else None
        if requested and ("group_id" in args or window is not None):
            raise BrowserError("group_id and window_id apply to new tabs. Use browser_group or browser_tab to move an existing tab.")
        previous_source = self.source
        if visible:
            self.select(Separate.PROFILE)
        elif "browser" in args:
            self.select(source_of(text(args, "browser")))
        switching_mode = self.source != previous_source or (self.connection is not None and self.visible != visible)
        self.connect(cancel, visible=visible)
        target = "" if switching_mode else requested
        tabs = self._tabs(cancel)
        self.created.intersection_update(tab.id for tab in tabs)
        if not target:
            match placement:
                case InGroup():
                    in_strip = True
                case _:
                    in_strip = self.owner == Attached(Product.EDGE) and placement is not Ungrouped.TABS
            if not visible and (in_strip or window is not None):
                target = self._native_target(placement, window, cancel)
            elif self.process is not None:
                target = next((tab.id for tab in tabs if tab.url == "about:blank"), "")
            if not target:
                target = text(self._call("Target.createTarget", {"url": "about:blank", "background": not visible}, cancel), "targetId")
                self.created.add(target)
        session = self._session(target, cancel)
        navigation = self._call("Page.navigate", {"url": url}, cancel, session=session)
        if navigation.get("errorText"):
            raise BrowserError(text(navigation, "errorText"))
        if visible:
            message = "Sign in in the separate Edge window. After the user finishes, browser_open resumes background work with this profile."
            return BrowserResult(_dumped(_SIGN_IN, SignInPage(target, url, message)))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if cancel.wait(0.1):
                raise InterruptedError("Stopped while navigating. The page may already have loaded.")
            try:
                context, tree = self._world(session, "", cancel)
                if navigation.get("loaderId") and mapping(tree.get("frame", {})).get("loaderId") != navigation["loaderId"]:
                    continue
                if self._evaluate("document.readyState", session, context, cancel) in ("interactive", "complete"):
                    return self._snapshot(target, args, cancel)
            except InterruptedError:
                raise
            except BrowserError:
                continue  # Navigating briefly destroys the previous execution context.
        raise NavigationLoadingError(f"Navigation is still loading. Inspect browser tab {target} before retrying.")

    def request(self, operation: str, args: dict[str, Json], cancel: threading.Event) -> BrowserResult:
        with self.lock:
            try:
                return self._request(operation, args, cancel)
            except InterruptedError, DisconnectedError:
                self.close()
                raise

    def web_app[Q: Located, R](self, operation: WebAppOperation[Q, R], query: Q, cancel: threading.Event) -> R:
        """Perform one web-app operation without another request interleaving on its page."""
        with self.lock:
            try:
                return WebApps(self).run(operation, query, cancel)
            except InterruptedError, DisconnectedError:
                self.close()
                raise

    def download_document(self, request: Download, cancel: threading.Event) -> Downloaded:
        with self.lock, self.awake(request.target_id, cancel):
            web_url(request.url)
            session = self._session(request.target_id, cancel)
            tree = mapping(self._call("Page.getFrameTree", {}, cancel, session=session).get("frameTree"))
            frame = text(mapping(tree.get("frame")), "id")

            def transport(method: str, arguments: dict[str, Json]) -> dict[str, Json]:
                options = {**arguments, "frameId": frame} if method == "Network.loadNetworkResource" else arguments
                return self._call(method, options, threading.Event() if method == "IO.close" else cancel, session=session)

            return download(request, cancel, transport)

    def activate_page(self, target: str, cancel: threading.Event) -> None:
        """Bring forward an exact CDP page without requiring session-local native tab metadata."""
        self.request("activate", {"target_id": target}, cancel)

    def _status(self, args: dict[str, Json], cancel: threading.Event) -> BrowserResult:
        view = text(args, "view", "pages")
        if view not in ("pages", "strip"):
            raise BrowserError("view must be pages or strip.")
        if view == "pages" and ("group_id" in args or "window_id" in args):
            raise BrowserError("Tab and window filters require view=strip.")
        if view == "strip" and self.connection is not None:
            return self._strip_status(args, cancel)
        tabs = self._tabs(cancel)
        offset = number(args, "offset", 0, 0, 20000)
        limit = number(args, "limit", 20, 1, 40)
        attached = self.attached
        rows = tuple(
            PageRow(tab.id, tab.title, tab.url, self.native_targets.get(tab.id), created_in_session=tab.id in self.created if attached else None)
            for tab in tabs[offset : offset + limit]
        )
        mode: Literal["stopped", "attached", "sign_in", "background"] = (
            "stopped" if self.connection is None else "attached" if attached else "sign_in" if self.visible else "background"
        )
        match self.source:
            case Product() as product:
                # Reading status never connects or triggers browser permission.
                setup = setup_message(product) if self.connection is None else None
                state = BrowserStatus(mode, rows, product.value, setup, len(tabs), offset)
            case _:
                state = BrowserStatus(mode, rows)
        while _size(_STATUS, state) > MAX_OUTPUT - 100 and len(state.tabs) > 1:
            state = replace(state, tabs=state.tabs[:-1])
        if offset + len(state.tabs) < len(tabs):
            state = replace(state, next_offset=offset + len(state.tabs))
        return BrowserResult(_dumped(_STATUS, state))

    def _require_strip(self) -> None:
        if self.connection is None:
            raise BrowserError("Connect with browser_attach before managing tabs and groups.")
        if self.source is Product.CHROME:
            raise BrowserError("Native tab/group controls currently require Edge. Chrome supports the page tools and closing by target_id.")

    def _strip_status(self, args: dict[str, Json], cancel: threading.Event) -> BrowserResult:
        query = strip_query(args)
        self._require_strip()
        state = self.strip.snapshot(self._call, cancel)
        result = strip_page(
            state,
            query,
            "attached" if self.attached else "sign_in" if self.visible else "background",
            self.native_targets,
            maximum=MAX_OUTPUT,
        )
        return BrowserResult(_STRIP.dump_json(result).decode())

    def _tab_operation(self, request: TabEdit, cancel: threading.Event) -> BrowserResult:
        self._require_strip()
        value: GroupData | TabData | UngroupedData
        match request:
            case CreateGroup() | EditGroup():
                value = self.strip.group(self._call, request, cancel).data()
            case ChangeTab() | MoveTab():
                value = self.strip.tab(self._call, request, cancel).data()
            case UngroupTabs(identities):
                value = self.strip.ungroup(self._call, identities, cancel).data()
            case _:
                assert_never(request)
        return BrowserResult(_EDITED.dump_json(value).decode())

    def _close(self, request: Closure, cancel: threading.Event) -> BrowserResult:
        match request:
            case ClosePage():
                return self._close_page(request, cancel)
            case CloseTabs() | CloseGroup():
                self._require_strip()
                closed = self.strip.close(self._call, request, cancel)
                for target, identity in tuple(self.native_targets.items()):
                    if identity in closed.tab_ids:
                        self.native_targets.pop(target)
                        self.sessions.pop(target, None)
                        self.created.discard(target)
                return BrowserResult(_CLOSED_TABS.dump_json(closed.data()).decode())
            case Disconnect.BROWSER:
                attached = self.attached
                self.close()
                return BrowserResult(
                    "Disconnected. Your browser and its tabs remain open." if attached else "Closed. The dedicated sign-in profile is retained."
                )
            case _:
                assert_never(request)

    def _close_page(self, request: ClosePage, cancel: threading.Event) -> BrowserResult:
        target = request.target_id
        if not any(tab.id == target for tab in self._tabs(cancel)):
            raise BrowserError("That page is closed or is not in the connected browser. Call browser_tabs for current ids.")
        result = self._call("Target.closeTarget", {"targetId": target}, cancel)
        if result.get("success") is not True:
            raise BrowserError("The browser did not accept the tab's close request. Inspect browser_tabs before retrying.")
        deadline = time.monotonic() + 3
        while any(tab.id == target for tab in self._tabs(cancel)):
            if time.monotonic() >= deadline:
                return BrowserResult(_CLOSED_PAGE.dump_json(PageClosure(target, CloseState.REQUESTED).data()).decode())
            if cancel.wait(0.05):
                raise InterruptedError("Stopped while waiting for the tab to close. Inspect browser_tabs before retrying.")
        self.sessions.pop(target, None)
        self.created.discard(target)
        self.native_targets.pop(target, None)
        return BrowserResult(_CLOSED_PAGE.dump_json(PageClosure(target, CloseState.CLOSED).data()).decode())

    def _attach_request(self, args: dict[str, Json], cancel: threading.Event) -> BrowserResult:
        match self.source:
            case Product() as current:
                default = current.value
            case _:
                default = "edge"
        match source_of(text(args, "browser", default)):
            case Product() as product:
                self.select(product)
                self._attach(product, cancel)
            case _:
                raise BrowserError("Choose edge or chrome to attach to your signed-in browser.")
        return self._status(args, cancel)

    def _action(self, session: str, args: dict[str, Json], cancel: threading.Event) -> BrowserResult:
        context, _tree = self._world(session, text(args, "frame_id"), cancel)
        match text(args, "action"):
            case "click" | "fill" | "select" | "check" as action:
                pass
            case _:
                raise BrowserError("Use click, fill, select or check with an id from the latest browser snapshot.")
        match args.get("checked", True):
            case bool() as checked if len(text(args, "value")) <= 60_000:
                pass
            case _:
                raise BrowserError("checked must be a boolean and field values may contain at most 60,000 characters.")
        dom_click = bool(text(args, "frame_id"))
        options = ActionOptions(text(args, "id"), action, text(args, "value"), checked=checked, dom_click=dom_click)
        result = self._evaluate(f"{browser_dom.ACTION}({_ACTION_OPTIONS.dump_json(options).decode()})", session, context, cancel)
        if action == "click" and not dom_click:
            point = _decoded(_POINT, result)
            for kind in ("mousePressed", "mouseReleased"):
                self._call(
                    "Input.dispatchMouseEvent",
                    {"type": kind, "x": point.x, "y": point.y, "button": "left", "clickCount": 1},
                    cancel,
                    session=session,
                )
        return BrowserResult("Browser action completed. Read a fresh browser_snapshot to verify the result.")

    def _request(self, operation: str, args: dict[str, Json], cancel: threading.Event) -> BrowserResult:
        if cancel.is_set():
            raise InterruptedError("Stopped before browser automation.")
        if operation in ("open", "sign_in"):
            return self._open(args, cancel, visible=operation == "sign_in")
        if operation == "attach":
            return self._attach_request(args, cancel)
        if operation == "tabs":
            return self._status(args, cancel)
        if operation == "activate":
            target = text(args, "target_id")
            if not any(page.id == target for page in self._tabs(cancel)):
                raise BrowserError("That browser page is closed. Refresh before opening its source.")
            self._call("Target.activateTarget", {"targetId": target}, cancel)
            return BrowserResult("Browser page activated.")
        if operation in ("group", "ungroup", "tab"):
            return self._tab_operation(tab_edit(operation, args), cancel)
        if operation == "close":
            return self._close(closure(args), cancel)
        target = text(args, "target_id")
        if operation == "snapshot":
            return self._snapshot(target, args, cancel)
        session = self._session(target, cancel)
        if operation == "screenshot":
            result = self._capture(session, cancel)
            try:
                image = base64.b64decode(text(result, "data"), validate=True)
                if len(image) < 33 or image[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
                    raise ValueError("Invalid PNG header")
                width, height = int.from_bytes(image[16:20], "big"), int.from_bytes(image[20:24], "big")
                if not 0 < width <= 8192 or not 0 < height <= 8192 or width * height > 16_000_000:
                    raise ValueError("Oversized PNG")
            except (binascii.Error, ValueError) as error:
                raise BrowserError("Edge returned an invalid or oversized viewport image.") from error
            return BrowserResult("Browser viewport screenshot. Use browser controls; these are not desktop mouse coordinates.", image)
        if operation == "action":
            return self._action(session, args, cancel)
        context, _tree = self._world(session, text(args, "frame_id"), cancel)
        if operation == "evaluate":
            expression = text(args, "expression")
            if not expression.strip() or len(expression) > 60_000:
                raise BrowserError("Provide a JavaScript expression of at most 60,000 characters.")
            wrapped = (
                "(async () => { const value = await (" + expression + "); const text = JSON.stringify(value ?? null) ?? String(value); "
                f"return text.length > {MAX_OUTPUT} ? text.slice(0, {MAX_OUTPUT - 30}) + '\\n[output truncated]' : text;" + "})()"
            )
            # The wrapper always returns its value's bounded JSON text.
            match self._evaluate(wrapped, session, context, cancel, timeout=number(args, "timeout_seconds", 15, 1, 30)):
                case str() as value:
                    return BrowserResult(value)
                case _:
                    raise BrowserError("The page did not return its evaluated value as text.")
        raise BrowserError("Unknown browser operation.")
