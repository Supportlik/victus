"""Which calendar day a moment belongs to.

Timestamps are stored in UTC, which is right, but a day is a local thing: a weigh-in at
half past midnight in Berlin is 22:30 UTC the day before. Every place that turns a moment
into a day, or asks what "today" is, goes through here with the configured zone (R69).
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: Used when nothing is configured. Central European time, where this was first used.
DEFAULT_TIMEZONE = "Europe/Berlin"


def zone(name: str | None) -> ZoneInfo:
    """The named zone, falling back to the default when it is unknown.

    An unusable zone must not take the application down: a report is still worth more
    than an error page, and the fallback is a documented default rather than UTC.
    """
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def day_of(moment: dt.datetime, tz: str | None = None) -> dt.date:
    """The calendar day a moment falls on, in ``tz``."""
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=dt.UTC)
    return aware.astimezone(zone(tz)).date()


def today_in(tz: str | None = None, *, now: dt.datetime | None = None) -> dt.date:
    """Today in ``tz``. ``now`` is injectable so tests do not depend on the wall clock."""
    return day_of(now or dt.datetime.now(dt.UTC), tz)


def day_start(day: dt.date, tz: str | None = None) -> dt.datetime:
    """The UTC moment a local day begins, for range queries against stored timestamps."""
    return dt.datetime.combine(day, dt.time.min, tzinfo=zone(tz)).astimezone(dt.UTC)


def day_end(day: dt.date, tz: str | None = None) -> dt.datetime:
    """The UTC moment the local day ends, exclusive."""
    return day_start(day + dt.timedelta(days=1), tz)
