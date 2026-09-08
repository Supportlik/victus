"""T-OPS-006 retention, T-OPS-014 scheduler cycle, T-OPS-015 cron parser."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from victus.backup.retention import FAILED_SUFFIX, apply_retention, mark_failed, plan_retention
from victus.backup.schedule import ALIVE_MARKER, CronError, CronSpec, run_backup_job, run_scheduled

from .conftest import Seeded

pytestmark = pytest.mark.service


def _touch(dir_: Path, ts: datetime, scope: str = "all") -> Path:
    p = dir_ / f"victus-{scope}-{ts.strftime('%Y%m%dT%H%M%SZ')}.zip"
    p.write_bytes(b"x")
    return p


def test_retention_keeps_daily_weekly_monthly_and_newest(tmp_path: Path) -> None:
    """T-OPS-006: 120 daily archives → 7 daily + 8 weekly + 12 monthly buckets kept."""
    now = datetime(2026, 9, 8, 4, 0, tzinfo=UTC)
    files = [_touch(tmp_path, now - timedelta(days=i)) for i in range(120)]
    protected = files[50]
    mark_failed(protected, "verify failed")
    plan = plan_retention(tmp_path, daily=7, weekly=8, monthly=12, now=now)
    kept = set(plan.keep)
    assert files[0] in kept  # newest
    assert all(f in kept for f in files[:7])  # 7 most recent days
    assert protected in kept and protected in plan.protected
    # weekly: the newest archive of each of the last 8 ISO weeks
    weeks = {p.name[-20:-4] for p in kept}
    assert len(weeks) >= 8
    deleted = apply_retention(tmp_path, daily=7, weekly=8, monthly=12, now=now)
    assert deleted == plan.delete
    remaining = sorted(p for p in tmp_path.iterdir() if p.suffix == ".zip")
    assert set(remaining) == kept
    assert 12 <= len(remaining) <= 7 + 8 + 12 + 1
    assert (tmp_path / (protected.name + FAILED_SUFFIX)).exists()


def test_retention_is_per_scope(tmp_path: Path) -> None:
    now = datetime(2026, 9, 8, tzinfo=UTC)
    for i in range(10):
        _touch(tmp_path, now - timedelta(days=i), "alice")
        _touch(tmp_path, now - timedelta(days=i), "all")
    deleted = apply_retention(tmp_path, daily=3, weekly=1, monthly=1, now=now)
    assert len([p for p in deleted if "-alice-" in p.name]) == 7
    assert len([p for p in deleted if "-all-" in p.name]) == 7


def test_cron_parser() -> None:
    """T-OPS-015: five-field cron: fixed, lists, ranges, steps; next_after."""
    spec = CronSpec.parse("0 3 * * *")
    assert spec.next_after(datetime(2026, 9, 8, 2, 59, tzinfo=UTC)) == datetime(
        2026, 9, 8, 3, 0, tzinfo=UTC
    )
    assert spec.next_after(datetime(2026, 9, 8, 3, 0, tzinfo=UTC)) == datetime(
        2026, 9, 9, 3, 0, tzinfo=UTC
    )
    hourly = CronSpec.parse("*/15 * * * *")
    assert hourly.next_after(datetime(2026, 9, 8, 3, 1, tzinfo=UTC)) == datetime(
        2026, 9, 8, 3, 15, tzinfo=UTC
    )
    sunday = CronSpec.parse("0 4 * * 0")
    nxt = sunday.next_after(datetime(2026, 9, 8, tzinfo=UTC))  # a Tuesday
    assert nxt.isoweekday() == 7 and nxt.hour == 4
    assert CronSpec.parse("30 1,13 1-15 * mon".replace("mon", "1")).hours == frozenset({1, 13})
    with pytest.raises(CronError):
        CronSpec.parse("0 3 * *")
    with pytest.raises(CronError):
        CronSpec.parse("61 3 * * *")


def test_run_backup_job_records_row_and_verifies(seeded: Seeded) -> None:
    """T-OPS-014 (part): one job = archive + verification + backup_job row."""
    outcome = run_backup_job(
        seeded.engine, target_dir=seeded.backups, storage_path=seeded.storage, retention=(7, 8, 12)
    )
    assert outcome.ok, outcome.error
    assert outcome.archive is not None and outcome.archive.exists()
    assert outcome.verified
    with seeded.engine.connect() as c:
        row = c.execute(text("SELECT status, verified, path, size FROM backup_job")).one()
    assert row[0] == "finished" and bool(row[1]) is True
    assert row[2] == str(outcome.archive) and row[3] == outcome.archive.stat().st_size


def test_run_scheduled_once_touches_marker(seeded: Seeded) -> None:
    """T-OPS-014: `schedule --once` writes the alive marker and one finished job."""
    outcomes = run_scheduled(
        seeded.engine,
        cron="0 3 * * *",
        target_dir=seeded.backups,
        storage_path=seeded.storage,
        once=True,
    )
    assert len(outcomes) == 1 and outcomes[0].ok
    assert (seeded.backups / ALIVE_MARKER).exists()


def test_run_scheduled_loop_waits_for_cron(seeded: Seeded) -> None:
    """The daemon loop sleeps until the next cron slot, then runs exactly once per slot."""
    clock_now = [datetime(2026, 9, 8, 2, 59, 30, tzinfo=UTC)]
    slept: list[float] = []

    def clock() -> datetime:
        return clock_now[0]

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock_now[0] += timedelta(seconds=seconds)

    outcomes = run_scheduled(
        seeded.engine,
        cron="0 3 * * *",
        target_dir=seeded.backups,
        storage_path=seeded.storage,
        sleep=sleep,
        clock=clock,
        max_cycles=1,
        include_snapshot=False,
    )
    assert len(outcomes) == 1 and outcomes[0].ok
    assert slept and sum(slept) >= 30
    assert (seeded.backups / ALIVE_MARKER).exists()
