"""The pager's row: where its controls and the rules between them sit."""

from desktop_ui.shell_surface import Row, ruled_row
from tests.test_bar_specs import BASE

CAPSULE = BASE.capsule


def test_a_rule_sits_midway_between_each_two_controls_and_an_empty_row_has_none() -> None:
    # Defects: an empty pager (a single desktop) fails to lay out, a rule lands on
    # a control or nearer one neighbour, or the strip cuts off its last control.
    assert ruled_row((), CAPSULE) == Row((), (), 0)
    assert ruled_row((30,), CAPSULE) == Row((0,), (), 30)
    widths = (30, 54, 30)
    row = ruled_row(widths, CAPSULE)
    ends = tuple(left + width for left, width in zip(row.lefts, widths, strict=True))
    after = tuple(rule - end for rule, end in zip(row.rules, ends, strict=False))
    before = tuple(left - (rule + round(CAPSULE.hairline)) for rule, left in zip(row.rules, row.lefts[1:], strict=True))
    assert after == before and all(space > 0 for space in after)
    assert row.width == ends[-1]
