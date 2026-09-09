"""T-DOM-080: a day is local, even though timestamps are stored in UTC (R69)."""

from __future__ import annotations

import datetime as dt

import pytest

from victus.domain.services.calendar import (
    DEFAULT_TIMEZONE,
    day_end,
    day_of,
    day_start,
    today_in,
    zone,
)

pytestmark = pytest.mark.domain

BERLIN = "Europe/Berlin"


def test_a_moment_just_after_local_midnight_belongs_to_the_new_day() -> None:
    # 22:30 UTC in winter is 23:30 in Berlin: still the same day
    assert day_of(dt.datetime(2026, 1, 5, 22, 30, tzinfo=dt.UTC), BERLIN) == dt.date(2026, 1, 5)
    # 23:30 UTC is half past midnight in Berlin: the next day
    assert day_of(dt.datetime(2026, 1, 5, 23, 30, tzinfo=dt.UTC), BERLIN) == dt.date(2026, 1, 6)
    # in summer Berlin is two hours ahead, so the boundary moves an hour earlier
    assert day_of(dt.datetime(2026, 7, 5, 22, 30, tzinfo=dt.UTC), BERLIN) == dt.date(2026, 7, 6)
    # UTC itself still reads the plain date
    assert day_of(dt.datetime(2026, 1, 5, 23, 30, tzinfo=dt.UTC), "UTC") == dt.date(2026, 1, 5)


def test_naive_timestamps_are_read_as_utc() -> None:
    """Rows written before the timezone column existed carry no offset."""
    assert day_of(dt.datetime(2026, 1, 5, 23, 30), BERLIN) == dt.date(2026, 1, 6)


def test_day_bounds_are_utc_moments_of_the_local_day() -> None:
    start = day_start(dt.date(2026, 1, 6), BERLIN)
    assert start == dt.datetime(2026, 1, 5, 23, 0, tzinfo=dt.UTC)
    assert day_end(dt.date(2026, 1, 6), BERLIN) == dt.datetime(2026, 1, 6, 23, 0, tzinfo=dt.UTC)
    # summer time shortens the offset to the UTC day by an hour
    assert day_start(dt.date(2026, 7, 6), BERLIN) == dt.datetime(2026, 7, 5, 22, 0, tzinfo=dt.UTC)


def test_an_unknown_zone_falls_back_instead_of_failing() -> None:
    assert zone("Mars/Olympus_Mons").key == DEFAULT_TIMEZONE
    assert zone(None).key == DEFAULT_TIMEZONE
    assert zone("").key == DEFAULT_TIMEZONE


def test_today_uses_the_given_moment() -> None:
    late = dt.datetime(2026, 3, 1, 23, 30, tzinfo=dt.UTC)
    assert today_in(BERLIN, now=late) == dt.date(2026, 3, 2)
    assert today_in("UTC", now=late) == dt.date(2026, 3, 1)
