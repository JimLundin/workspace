"""The observer's site selection, complete reads and failed connection ownership."""

import threading

from assistant.browser import BrowserResult
from assistant.browser_requests import BrowserRequest, Evaluate
from assistant.browser_values import BrowserStatus, PageList, PageRow
from assistant.meeting_browser import OBSERVE, STATUS, TeamsCalls
from contracts.meeting_detection import Call, Calls, ObservationFailure


class PublishedPages:
    """A concrete browser port exposes immutable saved page observations.

    The fixture owns request receipts and client release; it never replaces
    imported functions or the production browser's native methods.
    """

    def __init__(self, wire: str) -> None:
        self.wire = wire
        self.requests: tuple[BrowserRequest, ...] = ()
        self.closed = 0

    def connect(self, cancel: threading.Event, *, visible: bool = False) -> None:
        pass

    def request(self, request: BrowserRequest, cancel: threading.Event) -> BrowserResult:
        self.requests += (request,)
        match request:
            case PageList(offset=0):
                status = BrowserStatus("attached", (PageRow("mail", "Mail", "https://outlook.office.com/"),), next_offset=1)
                return BrowserResult(STATUS.dump_json(status).decode())
            case PageList(offset=1):
                status = BrowserStatus("attached", (PageRow("call", "Teams", "https://teams.cloud.microsoft/v2/"),))
                return BrowserResult(STATUS.dump_json(status).decode())
            case Evaluate(target_id="call"):
                return BrowserResult(self.wire)
            case _:
                raise AssertionError(f"Unexpected browser effect: {request}")

    def close(self) -> None:
        self.closed += 1


def test_observer_reads_only_teams_across_paginated_browser_pages() -> None:
    # Defect: Teams beyond the first page is missed, or monitoring evaluates
    # another site's DOM or changes focus/navigation instead of reading it.
    port = PublishedPages('{"phase":"connected","title":"Private call"}')
    observer = TeamsCalls(port)
    assert observer.observe(threading.Event()) == Calls((Call("call", "Private call"),))
    assert port.requests == (PageList(0, 100), PageList(1, 100), Evaluate("call", OBSERVE, timeout_seconds=3))
    observer.close()
    assert port.closed == 1


def test_invalid_page_read_is_unknown_and_releases_client_for_reconnection() -> None:
    # Defect: invalid/missing call evidence appears as leaving, or a stale client
    # is retained so a restarted personal browser can never reconnect.
    port = PublishedPages('{"phase":"loading"}')
    observer = TeamsCalls(port)
    assert observer.observe(threading.Event()) is ObservationFailure.UNAVAILABLE
    assert port.closed == 1
