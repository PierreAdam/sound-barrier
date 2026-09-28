from datetime import date

from app.services.new_releases import in_period, months_before


def test_months_before() -> None:
    assert months_before(date(2026, 9, 28), 6) == date(2026, 3, 28)
    assert months_before(date(2026, 3, 31), 1) == date(2026, 2, 28)  # shorter month
    assert months_before(date(2026, 1, 15), 12) == date(2025, 1, 15)


def test_in_period_at_the_date_precision() -> None:
    start, today = date(2026, 3, 28), date(2026, 9, 28)
    assert in_period("2026-05-01", start, today) == (True, False)
    assert in_period("2026-03-01", start, today) == (False, False)  # before the 28th
    assert in_period("2026-03", start, today) == (True, False)  # March is in the period
    assert in_period("2026", start, today) == (True, True)  # month unknown
    assert in_period("2025", start, today) == (False, True)
    assert in_period(None, start, today) == (False, False)
