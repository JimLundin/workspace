"""The bar's plain reading of agent Markdown."""

from assistant.agent_session import notice_text
from desktop_ui.plain_text import Plain, plain


def test_marks_leave_the_words_and_a_canvas_link_becomes_its_target() -> None:
    # Defects: Markdown marks show in the bar, an ordinary link loses its label,
    # or the canvas link's "Open on canvas" label stays in the prose.
    reply = "## Totals\n\n**Revenue** is up; see [the sheet](https://example.com/sheet).\n\n- `Q3` grew\n* Q4 fell"
    assert plain(notice_text(reply, "result:budget")) == Plain("Totals\n\nRevenue is up; see the sheet.\n\n• Q3 grew\n• Q4 fell", "result:budget")
