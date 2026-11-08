"""WASAPI ABI and continuous capture with synthetic devices, never the real mic."""

import sys
import threading
import time
import unittest
from array import array
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows continuous audio bindings")

from assistant.meeting_store import MeetingStore
from winapi.pcm import RATE


def test_transcript_refresh_waits_for_a_real_windows_reader_to_release_the_file(tmp_path: Path) -> None:
    store = MeetingStore.create(tmp_path, "microphone")
    store.append(array("h", [1200] * RATE).tobytes())
    store.finish_capture()
    batch = store.batch()
    assert batch is not None
    store.complete(batch, "The complete transcript.")
    with store.transcript.open("r", encoding="utf-8") as reader:

        def release() -> None:
            time.sleep(0.15)
            reader.close()

        closer = threading.Thread(target=release)
        closer.start()
        try:
            store.export()
        finally:
            closer.join(timeout=2)
    assert "The complete transcript." in store.transcript.read_text(encoding="utf-8")
