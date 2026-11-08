"""The assistant's startup order."""

from assistant.control_policy import initialize_controls
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
