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

from pydantic import TypeAdapter

from assistant import browser_dom
from assistant.browser_documents import Download, Downloaded, download
from assistant.browser_requests import (
    Activate,
    Attach,
    BrowserRequest,
    Evaluate,
    Open,
    PageAction,
    PageSnapshot,
    Screenshot,
    SignIn,
    Status,
    web_url,
)
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
)
from assistant.browser_tabs import TabStrip
from assistant.browser_values import (
    CREATED_TARGET,
    STRIP_PAGE,
    TARGET_SESSION,
    ActionOptions,
    BrowserError,
    BrowserStatus,
    Capture,
    ChangeTab,
    ClosedTabs,
    ClosedTarget,
    CloseGroup,
    ClosePage,
    CloseState,
    CloseTabs,
    Closure,
    CreateGroup,
    DefaultGroup,
    Destination,
    Disconnect,
    DisconnectedError,
    EditGroup,
    Frame,
    FrameTree,
    FrameTreeReply,
    GroupRow,
    InGroup,
    InterruptedError,
    MoveTab,
    Navigated,
    NavigationLoadingError,
    Page,
    PageClosure,
    PageList,
    PageRow,
    Point,
    Rendered,
    SignInPage,
    Snapshot,
    SnapshotOptions,
    StripQuery,
    TabEdit,
    TabRow,
    Ungrouped,
    UngroupResult,
    UngroupTabs,
    World,
    decoded,
    evaluated,
    opening,
    pages_of,
    strip_page,
)
from automation.json_value import Json
lazy from assistant.web_apps import Located, WebAppOperation, WebApps

MAX_OUTPUT = 20_000
_UNEXPECTED = "The browser returned an unexpected page observation."

_SNAPSHOT_OPTIONS = TypeAdapter(SnapshotOptions)
_ACTION_OPTIONS = TypeAdapter(ActionOptions)
_RENDERED = TypeAdapter(Rendered)
_FRAME_TREE = TypeAdapter(FrameTreeReply)
_WORLD = TypeAdapter(World)
_NAVIGATED = TypeAdapter(Navigated)
_CAPTURE = TypeAdapter(Capture)
_CLOSED_TARGET = TypeAdapter(ClosedTarget)
_POINT = TypeAdapter(Point)
_SNAPSHOT = TypeAdapter(Snapshot)
_SIGN_IN = TypeAdapter(SignInPage)
_STATUS = TypeAdapter(BrowserStatus)
_GROUP_ROW = TypeAdapter(GroupRow)
_TAB_ROW = TypeAdapter(TabRow)
_UNGROUPED = TypeAdapter(UngroupResult)
_CLOSED_TABS = TypeAdapter(ClosedTabs)
_CLOSED_PAGE = TypeAdapter(PageClosure)
# Resolves after a visible page renders a new frame. Hidden pages never run
# animation frames; Chromium's capture keeps them producing frames itself.
_PRESENTED = (
    "new Promise(resolve => document.visibilityState === 'visible'"
    " ? requestAnimationFrame(() => requestAnimationFrame(() => resolve(true))) : resolve(false))"
)


def _remaining(deadline: float) -> float:
    """Probes share their operation's budget; one hung probe cannot overrun it."""
    return max(0.001, deadline - time.monotonic())


def _dumped[T](shape: TypeAdapter[T], value: T) -> str:
    return shape.dump_json(value, exclude_none=True).decode()


def _size[T](shape: TypeAdapter[T], value: T) -> int:
    return len(_dumped(shape, value))


def _frame_rows(tree: FrameTree) -> tuple[Frame, ...]:
    """The first 40 frames, breadth first."""
    frames: tuple[Frame, ...] = ()
    pending: tuple[FrameTree, ...] = (tree,)
    while pending and len(frames) < 40:
        branch = pending[0]
        pending = (*pending[1:], *branch.children)
        frames = (*frames, Frame(branch.frame.id, branch.frame.url[:300], branch.frame.name[:100]))
    return frames


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
            reply = self._call("Target.attachToTarget", {"targetId": target, "flatten": True}, cancel)
            self.sessions[target] = decoded(TARGET_SESSION, reply, "The browser did not attach that page.").session_id
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

    def _capture(self, session: str, cancel: threading.Event) -> Capture:
        try:
            self._call("Emulation.setFocusEmulationEnabled", {"enabled": True}, cancel, session=session)
            # A background tab can be shown without a compositor surface yet;
            # Chromium then fails the copy at once instead of waiting for it.
            context, _tree = self._world(session, "", cancel)
            self._evaluate(_PRESENTED, session, context, cancel, timeout=5)
            result = self._call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}, cancel, session=session)
        except BaseException as error:
            try:
                self._reset_capture(session, cancel)
            except Exception as cleanup_error:
                error.add_note(f"Browser capture cleanup also failed: {cleanup_error}")
            raise
        self._reset_capture(session, cancel)
        return decoded(_CAPTURE, result, "Edge returned an invalid or oversized viewport image.")

    def _frames(self, session: str, cancel: threading.Event, *, timeout: float = 15) -> FrameTree:
        reply = self._call("Page.getFrameTree", {}, cancel, session=session, timeout=timeout)
        return decoded(_FRAME_TREE, reply, "The browser did not describe the page's frames.").tree

    def _world(self, session: str, frame: str, cancel: threading.Event) -> tuple[int, FrameTree]:
        tree = self._frames(session, cancel)
        world = self._call("Page.createIsolatedWorld", {"frameId": frame or tree.frame.id, "worldName": "workspace"}, cancel, session=session)
        return decoded(_WORLD, world, "The browser did not create the page's script world.").context, tree

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

    def _snapshot(self, request: PageSnapshot, cancel: threading.Event) -> BrowserResult:
        target = request.target_id
        session = self._session(target, cancel)
        context, tree = self._world(session, request.frame_id, cancel)
        options = SnapshotOptions(uuid.uuid4().hex[:10], request.offset, request.limit, request.text_offset)
        script = f"{browser_dom.SNAPSHOT}({_SNAPSHOT_OPTIONS.dump_json(options).decode()})"
        rendered = decoded(_RENDERED, self._evaluate(script, session, context, cancel), _UNEXPECTED)
        frames = _frame_rows(tree)
        frame_offset = request.frame_offset
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

    def _open(self, request: Open, cancel: threading.Event, *, visible: bool) -> BrowserResult:
        url = web_url(request.url)
        placement, window = request.placement, request.window_id
        if request.target_id and (placement is not DefaultGroup.WORKSPACE or window is not None):
            raise BrowserError("group_id and window_id apply to new tabs. Use browser_group or browser_tab to move an existing tab.")
        previous_source = self.source
        if visible:
            self.select(Separate.PROFILE)
        elif request.source is not None:
            self.select(request.source)
        switching_mode = self.source != previous_source or (self.connection is not None and self.visible != visible)
        self.connect(cancel, visible=visible)
        target = "" if switching_mode else request.target_id
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
                created = self._call("Target.createTarget", {"url": "about:blank", "background": not visible}, cancel)
                target = decoded(CREATED_TARGET, created, "The browser did not create a tab.").target_id
                self.created.add(target)
        session = self._session(target, cancel)
        navigation = decoded(_NAVIGATED, self._call("Page.navigate", {"url": url}, cancel, session=session), "The browser did not navigate.")
        if navigation.error_text:
            raise BrowserError(navigation.error_text)
        if visible:
            message = "Sign in in the separate Edge window. After the user finishes, browser_open resumes background work with this profile."
            return BrowserResult(_dumped(_SIGN_IN, SignInPage(target, url, message)))
        return self._settle(target, navigation, cancel)

    def _settle(self, target: str, navigation: Navigated, cancel: threading.Event) -> BrowserResult:
        """Snapshot the navigated page once its main document is ready, within one budget."""
        session = self.sessions[target]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if cancel.wait(0.1):
                raise InterruptedError("Stopped while navigating. The page may already have loaded.")
            try:
                tree = self._frames(session, cancel, timeout=_remaining(deadline))
                if navigation.loader_id and tree.frame.loader_id != navigation.loader_id:
                    continue
                world = self._call(
                    "Page.createIsolatedWorld",
                    {"frameId": tree.frame.id, "worldName": "workspace"},
                    cancel,
                    session=session,
                    timeout=_remaining(deadline),
                )
                context = decoded(_WORLD, world, "The browser did not create the page's script world.").context
                if self._evaluate("document.readyState", session, context, cancel, timeout=_remaining(deadline)) in ("interactive", "complete"):
                    return self._snapshot(PageSnapshot(target), cancel)
            except InterruptedError:
                raise
            except BrowserError:
                continue  # Navigating briefly destroys the previous execution context.
        raise NavigationLoadingError(f"Navigation is still loading. Inspect browser tab {target} before retrying.")

    def request(self, request: BrowserRequest, cancel: threading.Event) -> BrowserResult:
        with self.lock:
            try:
                return self._request(request, cancel)
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
            frame = self._frames(session, cancel).frame.id

            def transport(method: str, arguments: dict[str, Json]) -> dict[str, Json]:
                options = {**arguments, "frameId": frame} if method == "Network.loadNetworkResource" else arguments
                return self._call(method, options, threading.Event() if method == "IO.close" else cancel, session=session)

            return download(request, cancel, transport)

    def activate_page(self, target: str, cancel: threading.Event) -> None:
        """Bring forward an exact CDP page without requiring session-local native tab metadata."""
        self.request(Activate(target), cancel)

    def _status(self, request: Status, cancel: threading.Event) -> BrowserResult:
        match request:
            case StripQuery() if self.connection is not None:
                return self._strip_status(request, cancel)
            case StripQuery(offset, limit) | PageList(offset, limit):
                pass
            case _:
                assert_never(request)
        tabs = self._tabs(cancel)
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

    def _strip_status(self, query: StripQuery, cancel: threading.Event) -> BrowserResult:
        self._require_strip()
        state = self.strip.snapshot(self._call, cancel)
        result = strip_page(
            state,
            query,
            "attached" if self.attached else "sign_in" if self.visible else "background",
            self.native_targets,
            maximum=MAX_OUTPUT,
        )
        return BrowserResult(_dumped(STRIP_PAGE, result))

    def _tab_operation(self, request: TabEdit, cancel: threading.Event) -> BrowserResult:
        self._require_strip()
        match request:
            case CreateGroup() | EditGroup():
                return BrowserResult(_dumped(_GROUP_ROW, self.strip.group(self._call, request, cancel).row()))
            case ChangeTab() | MoveTab():
                return BrowserResult(_dumped(_TAB_ROW, self.strip.tab(self._call, request, cancel).row()))
            case UngroupTabs(identities):
                return BrowserResult(_dumped(_UNGROUPED, self.strip.ungroup(self._call, identities, cancel)))
            case _:
                assert_never(request)

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
                return BrowserResult(_dumped(_CLOSED_TABS, closed.row()))
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
        result = decoded(_CLOSED_TARGET, self._call("Target.closeTarget", {"targetId": target}, cancel), "The browser did not answer the close.")
        if not result.success:
            raise BrowserError("The browser did not accept the tab's close request. Inspect browser_tabs before retrying.")
        deadline = time.monotonic() + 3
        while any(tab.id == target for tab in self._tabs(cancel)):
            if time.monotonic() >= deadline:
                return BrowserResult(_dumped(_CLOSED_PAGE, PageClosure(target, CloseState.REQUESTED)))
            if cancel.wait(0.05):
                raise InterruptedError("Stopped while waiting for the tab to close. Inspect browser_tabs before retrying.")
        self.sessions.pop(target, None)
        self.created.discard(target)
        self.native_targets.pop(target, None)
        return BrowserResult(_dumped(_CLOSED_PAGE, PageClosure(target, CloseState.CLOSED)))

    def _attach_request(self, request: Attach, cancel: threading.Event) -> BrowserResult:
        match request.browser, self.source:
            case Product() as product, _:
                pass
            case None, Product() as product:
                pass
            case None, Separate.PROFILE:
                product = Product.EDGE
        self.select(product)
        self._attach(product, cancel)
        return self._status(PageList(), cancel)

    def _screenshot(self, request: Screenshot, cancel: threading.Event) -> BrowserResult:
        capture = self._capture(self._session(request.target_id, cancel), cancel)
        try:
            image = base64.b64decode(capture.data, validate=True)
            if len(image) < 33 or image[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
                raise ValueError("Invalid PNG header")
            width, height = int.from_bytes(image[16:20], "big"), int.from_bytes(image[20:24], "big")
            if not 0 < width <= 8192 or not 0 < height <= 8192 or width * height > 16_000_000:
                raise ValueError("Oversized PNG")
        except (binascii.Error, ValueError) as error:
            raise BrowserError("Edge returned an invalid or oversized viewport image.") from error
        return BrowserResult("Browser viewport screenshot. Use browser controls; these are not desktop mouse coordinates.", image)

    def _action(self, request: PageAction, cancel: threading.Event) -> BrowserResult:
        session = self._session(request.target_id, cancel)
        context, _tree = self._world(session, request.frame_id, cancel)
        # A frame's control coordinates are relative to that frame, not the
        # viewport, so the page dispatches the click itself there.
        dom_click = bool(request.frame_id)
        options = ActionOptions(request.id, request.action, request.value, checked=request.checked, dom_click=dom_click)
        result = self._evaluate(f"{browser_dom.ACTION}({_ACTION_OPTIONS.dump_json(options).decode()})", session, context, cancel)
        if request.action == "click" and not dom_click:
            point = decoded(_POINT, result, _UNEXPECTED)
            for kind in ("mousePressed", "mouseReleased"):
                self._call(
                    "Input.dispatchMouseEvent",
                    {"type": kind, "x": point.x, "y": point.y, "button": "left", "clickCount": 1},
                    cancel,
                    session=session,
                )
        return BrowserResult("Browser action completed. Read a fresh browser_snapshot to verify the result.")

    def _evaluate_request(self, request: Evaluate, cancel: threading.Event) -> BrowserResult:
        session = self._session(request.target_id, cancel)
        context, _tree = self._world(session, request.frame_id, cancel)
        wrapped = (
            "(async () => { const value = await (" + request.expression + "); const text = JSON.stringify(value ?? null) ?? String(value); "
            f"return text.length > {MAX_OUTPUT} ? text.slice(0, {MAX_OUTPUT - 30}) + '\\n[output truncated]' : text;" + "})()"
        )
        # The wrapper always returns its value's bounded JSON text.
        match self._evaluate(wrapped, session, context, cancel, timeout=request.timeout_seconds):
            case str() as value:
                return BrowserResult(value)
            case _:
                raise BrowserError("The page did not return its evaluated value as text.")

    def _activate(self, request: Activate, cancel: threading.Event) -> BrowserResult:
        if not any(page.id == request.target_id for page in self._tabs(cancel)):
            raise BrowserError("That browser page is closed. Refresh before opening its source.")
        self._call("Target.activateTarget", {"targetId": request.target_id}, cancel)
        return BrowserResult("Browser page activated.")

    def _request(self, request: BrowserRequest, cancel: threading.Event) -> BrowserResult:
        if cancel.is_set():
            raise InterruptedError("Stopped before browser automation.")
        match request:
            case Open():
                return self._open(request, cancel, visible=False)
            case SignIn(url):
                return self._open(Open(url), cancel, visible=True)
            case Attach():
                return self._attach_request(request, cancel)
            case PageList() | StripQuery():
                return self._status(request, cancel)
            case Activate():
                return self._activate(request, cancel)
            case CreateGroup() | EditGroup() | ChangeTab() | MoveTab() | UngroupTabs():
                return self._tab_operation(request, cancel)
            case ClosePage() | CloseTabs() | CloseGroup() | Disconnect.BROWSER:
                return self._close(request, cancel)
            case PageSnapshot():
                return self._snapshot(request, cancel)
            case Screenshot():
                return self._screenshot(request, cancel)
            case PageAction():
                return self._action(request, cancel)
            case Evaluate():
                return self._evaluate_request(request, cancel)
            case _:
                assert_never(request)
