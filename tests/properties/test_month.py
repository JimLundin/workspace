"""Every month's calendar is six whole weeks that hold the month, and paging moves by whole months."""

from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise

from hypothesis import strategies

from desktop_ui.month import WEEKS, Month, weeks
from tests.properties.generation import cases, property_test


@dataclass(frozen=True, slots=True)
class MonthCase:
    month: Month
    first_weekday: int
    pages: int


def month_cases(draw: strategies.DrawFn) -> MonthCase:
    return MonthCase(
        Month(draw(strategies.integers(1900, 2200)), draw(strategies.integers(1, 12))),
        draw(strategies.integers(0, 6)),
        draw(strategies.integers(-300, 300)),
    )


@property_test(cases(month_cases))
def test_a_month_shows_six_consecutive_weeks_from_its_first_weekday_holding_every_day(case: MonthCase) -> None:
    # Defects: a five-week month leaves a short grid (the panel jumps as it turns), the
    # padding repeats or skips a day where two months meet, a column starts on the wrong
    # weekday, or the month's own days fall outside the grid.
    shown = weeks(case.month, case.first_weekday)
    days = tuple(day for week in shown for day in week)
    assert len(shown) == WEEKS and all(len(week) == 7 for week in shown)
    assert all(later - earlier == timedelta(days=1) for earlier, later in pairwise(days))
    assert days[0].weekday() == case.first_weekday
    assert days[0] <= case.month.first() and case.month.paged(1).first() - timedelta(days=1) <= days[-1]


@property_test(cases(month_cases))
def test_paging_moves_by_whole_months_across_years_and_back(case: MonthCase) -> None:
    # Defects: turning past December or January lands in the wrong year, or a page
    # forward and back again doesn't return to the month it left.
    turned = case.month.paged(case.pages)
    assert (turned.year * 12 + turned.month) - (case.month.year * 12 + case.month.month) == case.pages
    assert turned.paged(-case.pages) == case.month
    assert Month.of(date(case.month.year, case.month.month, 28)) == case.month
