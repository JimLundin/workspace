"""Document effect cleanup and bounded collection on real local files."""

import sys
import threading
from pathlib import Path
from unittest import SkipTest, TestCase

from assistant.browser_documents import Download, download
from assistant.browser_values import BrowserError
from assistant.llm import Json
from automation.work_documents import LocalDocument

if sys.platform != "win32":
    raise SkipTest("Windows document paths")


class DocumentStream:
    """Concrete stream adapter owns cursor, cancellation and its call receipt."""

    def __init__(self, response: dict[str, Json], chunks: tuple[str, ...], cancel: threading.Event | None = None) -> None:
        self.response = response
        self.chunks = chunks
        self.cancel = cancel
        self.index = 0
        self.calls: list[str] = []

    def __call__(self, method: str, arguments: dict[str, Json]) -> dict[str, Json]:
        self.calls.append(method)
        match method:
            case "Network.loadNetworkResource":
                assert arguments["options"] == {"disableCache": False, "includeCredentials": True}
                return self.response
            case "IO.read":
                data = self.chunks[self.index]
                self.index += 1
                if self.cancel is not None:
                    self.cancel.set()
                return {"data": data, "eof": self.index == len(self.chunks)}
            case "IO.close":
                assert arguments == {"handle": "owned-stream"}
                return {}
            case _:
                raise AssertionError(method)


def test_rejected_responses_and_partial_cancellation_leave_no_collected_document(tmp_path: Path) -> None:
    # Defect: an auth/error page is registered as a file, a cancelled partial
    # document survives, or the browser stream leaks when collection fails.
    path = tmp_path / "document.txt"
    request = Download("mail-target", "https://outlook.office.com/attachment", LocalDocument(str(path)))
    rejected: tuple[dict[str, Json], ...] = (
        {"resource": {"success": False, "httpStatusCode": 401, "stream": "owned-stream"}},
        {"resource": {"success": True, "httpStatusCode": 200, "stream": "owned-stream", "headers": {"Content-Type": "text/html; charset=UTF-8"}}},
    )
    for response in rejected:
        stream = DocumentStream(response, ())
        with TestCase().assertRaises(BrowserError):
            download(request, threading.Event(), stream)
        assert not path.exists() and stream.calls == ["Network.loadNetworkResource", "IO.close"]
    cancel = threading.Event()
    successful: dict[str, Json] = {"resource": {"success": True, "httpStatusCode": 200, "stream": "owned-stream"}}
    interrupted = DocumentStream(successful, ("partial", "never"), cancel)
    with TestCase().assertRaisesRegex(BrowserError, "Stopped"):
        download(request, cancel, interrupted)
    assert not path.exists() and interrupted.calls[-1] == "IO.close"
    empty = DocumentStream(successful, ("",))
    with TestCase().assertRaisesRegex(BrowserError, "empty"):
        download(request, threading.Event(), empty)
    assert not path.exists() and empty.calls[-1] == "IO.close"


def test_collection_limit_removes_partial_output_and_preserves_existing_versions(tmp_path: Path) -> None:
    # Defect: the byte limit only checks metadata, or a failed collection
    # overwrites/deletes a version that already belongs to the user.
    path = tmp_path / "document.txt"
    request = Download("mail-target", "https://outlook.office.com/attachment", LocalDocument(str(path)))
    response: dict[str, Json] = {"resource": {"success": True, "httpStatusCode": 200, "stream": "owned-stream"}}
    oversized = DocumentStream(response, ("a" * 65536,) * 513)
    with TestCase().assertRaisesRegex(BrowserError, "32 MiB"):
        download(request, threading.Event(), oversized)
    assert not path.exists() and oversized.calls[-1] == "IO.close"
    path.write_text("Existing approved version", encoding="utf-8")
    existing = DocumentStream(response, ("replacement",))
    with TestCase().assertRaises(FileExistsError):
        download(request, threading.Event(), existing)
    assert path.read_text(encoding="utf-8") == "Existing approved version" and existing.calls[-1] == "IO.close"
