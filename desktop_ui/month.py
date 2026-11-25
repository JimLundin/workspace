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
        if not date.min.year < self.year < date.max.year:
            raise ValueError(
                "A month's weeks must stay within the dates Python represents."
            )

    @classmethod
    def of(cls, day: date) -> Month:
        return cls(day.year, day.month)

    def paged(self, months: int) -> Month:
        year, index = divmod(self.year * 12 + self.month - 1 + months, 12)
        return Month(year, index + 1)

    def first(self) -> date:
        return date(self.year, self.month, 1)


def weeks(month: Month, first_weekday: int) -> tuple[tuple[date, ...], ...]:
    grid, later = calendar.Calendar(first_weekday), month.paged(1)
    shown = grid.monthdatescalendar(month.year, month.month)
    after = grid.monthdatescalendar(later.year, later.month)
    following = after[1:] if after[0][0] <= shown[-1][-1] else after
    return tuple(tuple(week) for week in (*shown, *following)[:WEEKS])
