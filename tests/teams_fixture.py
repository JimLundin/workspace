"""Local Teams document and tab adapters for collector policy tests.

Each instance owns its document transitions and effect receipts. Mutation stays
local to that test's browser lifetime; observations and receipts are tuples.
"""

import json
import threading
from collections.abc import Generator
from contextlib import contextmanager

from assistant.browser import BrowserResult
from assistant.browser_session import Attached, BrowserConnection, Owner, Product, Stopped
from assistant.browser_values import BrowserError
from assistant.communications_browser import ACTIVITY_OBSERVE, OBSERVE
from assistant.llm import Json


class Connection:
    # Preserve BrowserConnection's consumed CDP interface, including its
    # cancellation, session routing and bounded operation timeout inputs.
    def call(
        self, method: str, params: dict[str, Json], cancel: threading.Event, *, session: str = "", timeout: float = 15,
    ) -> dict[str, Json]:
        if method != "Browser.setPermission":
            raise AssertionError(f"Unexpected Teams connection operation: {method}")
        assert params["setting"] == "denied"
        return {}

    def close(self) -> None:
        pass


class Browser:
    def __init__(self, pages: tuple[dict[str, Json], ...] = ()) -> None:
        self.pages = pages
        self.document: Json = {"current": "", "title": "", "conversations": [], "messages": [], "editor_ready": False}
        self.documents: tuple[Json | Exception, ...] = ()
        self.activity: Json = {"ready": True, "items": []}
        self.visibility = "hidden"
        self.sidebar_click = False
        self.navigation_failure: BrowserError | None = None
        self.opens: tuple[dict[str, Json], ...] = ()
        self.wakes: tuple[str, ...] = ()
        self.activations: tuple[str, ...] = ()
        self.reads = 0
        self.connected = False
        self._connection = Connection()

    @property
    def connection(self) -> BrowserConnection | None:
        return self._connection if self.connected else None

    @property
    def owner(self) -> Owner:
        return Attached(Product.EDGE) if self.connected else Stopped.BROWSER

    def connect(self, cancel: threading.Event, *, visible: bool = False) -> None:
        self.connected = True

    @contextmanager
    def awake(self, target: str, cancel: threading.Event) -> Generator[None]:
        self.wakes += (target,)
        yield

    def activate_page(self, target: str, cancel: threading.Event) -> None:
        self.activations += (target,)

    def request(self, operation: str, args: dict[str, Json], cancel: threading.Event) -> BrowserResult:
        match operation:
            case "tabs":
                result: dict[str, object] = {"tabs": self.pages}
                return BrowserResult(json.dumps(result))
            case "open":
                self.opens += (dict(args),)
                if self.navigation_failure is not None:
                    raise self.navigation_failure
                return BrowserResult("Opened")
            case "evaluate":
                expression = args["expression"]
                assert isinstance(expression, str)
                if expression == OBSERVE:
                    self.reads += 1
                    if self.documents:
                        value, self.documents = self.documents[0], self.documents[1:]
                        if isinstance(value, Exception):
                            raise value
                        self.document = value
                    return BrowserResult(json.dumps(self.document))
                if expression == ACTIVITY_OBSERVE:
                    return BrowserResult(json.dumps(self.activity))
                if expression == "document.visibilityState":
                    return BrowserResult(json.dumps(self.visibility))
                if "row.click()" in expression:
                    return BrowserResult(json.dumps(self.sidebar_click))
                # The fixture has no Teams launcher or selectable sidebar. Exact
                # chat recovery must therefore navigate the existing tab.
                return BrowserResult("false")
            case _:
                raise AssertionError(f"Unexpected Teams browser operation: {operation}")

    def close(self) -> None:
        self.connected = False
