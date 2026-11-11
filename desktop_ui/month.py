"""A calendar month as the clock's panel shows it: six whole weeks, and paging by months."""

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Final

WEEKS: Final = 6
"""Every month shows six weeks, so paging never changes the panel's height."""


@dataclass(frozen=True, slots=True, order=True)
class Month:
    year: int
    month: int

    def __post_init__(self) -> None:
        if not 1 <= self.month <= 12:
            raise ValueError("A month runs from 1 to 12.")
        # A month's six weeks reach a week into the months on either side.
        if not date.min.year < self.year < date.max.year:
            raise ValueError("A month's weeks must stay within the dates Python represents.")

    @classmethod
    def of(cls, day: date) -> Month:
        return cls(day.year, day.month)

    def paged(self, months: int) -> Month:
        """The month `months` later (earlier when negative)."""
        year, index = divmod(self.year * 12 + self.month - 1 + months, 12)
        return Month(year, index + 1)

    def first(self) -> date:
        return date(self.year, self.month, 1)


def weeks(month: Month, first_weekday: int) -> tuple[tuple[date, ...], ...]:
    """The month's weeks, each starting on `first_weekday` (0 is Monday), padded with the next month's to six."""
    grid, later = calendar.Calendar(first_weekday), month.paged(1)
    shown = grid.monthdatescalendar(month.year, month.month)
    after = grid.monthdatescalendar(later.year, later.month)
    # The next month's first week overlaps this month's last unless the month ends on the week's last day.
    following = after[1:] if after[0][0] <= shown[-1][-1] else after
    return tuple(tuple(week) for week in (*shown, *following)[:WEEKS])
