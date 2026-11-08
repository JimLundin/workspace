"""The assistant's startup order and its meeting-file handoff."""

import queue
from collections.abc import Callable
from pathlib import Path

from assistant.control_policy import initialize_controls, meeting_file_job
from protocol import WM_QUERY_LAYOUT_STATE
from tests.test_desktop_controls import LayoutFixture


def test_assistant_queries_a_layout_that_started_before_it() -> None:
    """Detect a layout query sent before worker startup, or a running layout never asked to replay its state."""
    for layout in (2, None):
        effects = LayoutFixture(layout)
        assert initialize_controls(7, effects.start_workers, effects) == 17
        if layout is None:
            assert effects.messages == ()
            assert effects.timeline == ("timer", "workers", "find layout")
        else:
            assert effects.messages == ((2, WM_QUERY_LAYOUT_STATE, 0, 0),)
            assert effects.timeline == ("timer", "workers", "find layout", "post layout")


def test_meeting_file_handoff_keeps_canonical_path_and_reports_shell_failure(tmp_path: Path) -> None:
    path = tmp_path / "transcript.md"
    opened: list[Path] = []
    problems: list[str] = []

    def unavailable(target: Path) -> None:
        opened.append(target)
        raise OSError("The registered application cannot open this path")

    jobs: queue.Queue[Callable[[], None]] = queue.Queue()
    jobs.put(meeting_file_job(path, unavailable, problems.append))
    assert not opened and not problems
    jobs.get_nowait()()
    assert opened == [path]
    assert problems == ["Windows could not open this file. Choose Open meeting transcripts in All Workspace controls to find it."]
