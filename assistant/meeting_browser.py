"""Read in-call controls in existing Teams tabs, without navigation or focus changes."""

import threading
from contextlib import suppress
from dataclasses import dataclass
from typing import Annotated, Final, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import Field, TypeAdapter, ValidationError

from assistant.browser import BrowserResult
from assistant.browser_dom import script
from assistant.browser_requests import BrowserRequest, Evaluate
from assistant.browser_values import BrowserError, BrowserStatus, PageList
from contracts.meeting_detection import Call, Calls, Observation, ObservationFailure

HOSTS = frozenset({"teams.microsoft.com", "teams.cloud.microsoft"})

# Teams' in-call toolbar owns these controls. Prejoin, lobby and chat are not
# evidence; microphone alone is also present before joining. Read only visible
# controls, including a minimized call's retained hang-up toolbar.
OBSERVE: Final = script("meeting_browser.observe")


@dataclass(frozen=True, slots=True)
class PageCall:
    phase: Literal["connected", "outside"]
    title: Annotated[str, Field(strict=True, max_length=240)]


PAGE_CALL = TypeAdapter(PageCall)
STATUS = TypeAdapter(BrowserStatus)


class BrowserPort(Protocol):
    def connect(self, cancel: threading.Event, *, visible: bool = False) -> None: ...
    def request(self, request: BrowserRequest, cancel: threading.Event) -> BrowserResult: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class TeamsCalls:
    browser: BrowserPort

    def observe(self, cancel: threading.Event) -> Observation:
        """A complete read or unknown; a failed page must not look like leaving."""
        try:
            self.browser.connect(cancel)
            calls: tuple[Call, ...] = ()
            offset = 0
            while True:
                status = STATUS.validate_json(self.browser.request(PageList(offset, 100), cancel).text)
                for page in status.tabs:
                    if urlsplit(page.url).hostname not in HOSTS:
                        continue
                    seen = PAGE_CALL.validate_json(self.browser.request(Evaluate(page.id, OBSERVE, timeout_seconds=3), cancel).text)
                    if seen.phase == "connected":
                        calls += (Call(page.id, seen.title or "Teams meeting"),)
                if status.next_offset is None:
                    return Calls(calls)
                offset = status.next_offset
        except BrowserError, ValidationError, ValueError:
            # A restarted personal browser invalidates this client's sessions.
            # Detach only our client so the next poll can borrow a fresh connection.
            with suppress(OSError):
                self.browser.close()
            return ObservationFailure.UNAVAILABLE

    def close(self) -> None:
        self.browser.close()
