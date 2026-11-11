"""The pager's row: where its desktops sit."""

from desktop_ui.shell_surface import Row, spaced_row
from tests.test_bar_specs import BASE

CAPSULE = BASE.capsule


def test_desktops_sit_one_gap_apart_and_an_empty_row_lays_out() -> None:
    # Defects: an empty pager (a single desktop) fails to lay out, two desktops
    # touch or sit unevenly apart, or the strip cuts off its last control.
    assert spaced_row((), CAPSULE) == Row((), 0)
    assert spaced_row((30,), CAPSULE) == Row((0,), 30)
    widths = (30, 54, 30)
    row = spaced_row(widths, CAPSULE)
    ends = tuple(left + width for left, width in zip(row.lefts, widths, strict=True))
    gaps = {left - end for end, left in zip(ends, row.lefts[1:], strict=False)}
    assert gaps == {round(CAPSULE.slot_gap)} and row.width == ends[-1]
