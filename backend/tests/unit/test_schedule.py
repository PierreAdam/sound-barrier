from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.services.scans import next_run
from app.services.server_settings import ScanSchedule

PARIS = ZoneInfo("Europe/Paris")


def paris(*args: int) -> datetime:
    return datetime(*args, tzinfo=PARIS)


def test_next_run_later_today() -> None:
    assert next_run(paris(2026, 6, 1, 1, 30), 2, 0, PARIS) == paris(2026, 6, 1, 2, 0)


def test_next_run_tomorrow_when_time_passed() -> None:
    assert next_run(paris(2026, 6, 1, 2, 0), 2, 0, PARIS) == paris(2026, 6, 2, 2, 0)
    assert next_run(paris(2026, 6, 1, 23, 59), 2, 0, PARIS) == paris(2026, 6, 2, 2, 0)


def test_next_run_from_utc_now() -> None:
    # 00:30 UTC is 02:30 in Paris (summer): the 02:00 run is tomorrow.
    now = datetime(2026, 6, 1, 0, 30, tzinfo=UTC)
    assert next_run(now, 2, 0, PARIS) == paris(2026, 6, 2, 2, 0)


def test_next_run_keeps_wall_clock_across_dst() -> None:
    # Night of the switch to winter time (25 Oct 2026): still 04:00 local, one hour more UTC.
    before = next_run(paris(2026, 10, 24, 5, 0), 4, 0, PARIS)
    assert before == paris(2026, 10, 25, 4, 0)
    assert before.utcoffset() == paris(2026, 12, 1, 4, 0).utcoffset()


@pytest.mark.parametrize("value", ["24:00", "2:00", "02:60", "", "noon"])
def test_schedule_rejects_bad_times(value: str) -> None:
    with pytest.raises(ValidationError):
        ScanSchedule(time=value)


def test_schedule_defaults() -> None:
    schedule = ScanSchedule()
    assert (schedule.enabled, schedule.time, schedule.scan_on_startup) == (True, "02:00", True)
    assert schedule.hour_minute == (2, 0)
