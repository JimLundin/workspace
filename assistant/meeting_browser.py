"""Read in-call controls in existing Teams tabs, without navigation or focus changes."""

import threading
from contextlib import suppress
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import Field, TypeAdapter, ValidationError

from assistant.browser import BrowserResult
from assistant.browser_requests import BrowserRequest, Evaluate
from assistant.browser_values import BrowserError, BrowserStatus, PageList
from assistant.meeting_detection import Call, Calls, Observation, ObservationFailure

HOSTS = frozenset({"teams.microsoft.com", "teams.cloud.microsoft"})

# Teams' in-call toolbar owns these controls. Prejoin, lobby and chat are not
# evidence; microphone alone is also present before joining. Read only visible
# controls, including a minimized call's retained hang-up toolbar.
OBSERVE = """(() => {
  const visible=e=>!!e && e.getClientRects().length>0 && getComputedStyle(e).visibility!=='hidden';
  const has=s=>[...document.querySelectorAll(s)].some(visible);
  const leaving=has('[data-tid="call-hangup"], [data-tid="hangup-button"], #hangup-button');
  const microphone=has('[data-tid="call-microphone"], #microphone-button');
  const joining=has('[data-tid="prejoin-join-button"], #prejoin-join-button');
  const lobby=has('[data-tid="lobby-screen"], [data-tid="calling-lobby-screen"]');
  const duration=[...document.querySelectorAll('[data-tid="call-duration"]')]
    .some(e=>visible(e) && /^(?:\\d+:)?\\d{1,2}:\\d{2}$/.test(e.innerText.trim()));
  return {phase:leaving && microphone && duration && !joining && !lobby ? 'connected' : 'outside',
    title:document.title.slice(0,240)};
})()"""


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


class TeamsCalls:
    __slots__ = ("browser",)

    def __init__(self, browser: BrowserPort) -> None:
        self.browser = browser

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
