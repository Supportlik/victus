"""Scheduled backups without extra dependencies: a five-field cron parser and a loop.

Each cycle: create → verify → retention, recorded in ``backup_job``. The loop
touches ``<target>/.victus-backup.alive`` at least once a minute; the Compose
healthcheck of the ``backup`` service watches that file.
"""

from __future__ import annotations

import time as _time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from victus.backup.export import create_backup
from victus.backup.retention import apply_retention, mark_failed
from victus.backup.verify import verify_backup
from victus.infrastructure.db import orm

ALIVE_MARKER = ".victus-backup.alive"


# ── cron ─────────────────────────────────────────────────────────────────────


class CronError(ValueError):
    pass


def _expand(field_text: str, lo: int, hi: int) -> set[int]:
    values: set[int] = set()
    for part in field_text.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            step = int(step_text)
            if step < 1:
                raise CronError(f"bad step in {field_text!r}")
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
            if step != 1:
                end = hi
        if start < lo or end > hi or start > end:
            raise CronError(f"value out of range in {field_text!r}")
        values.update(range(start, end + 1, step))
    return values


@dataclass(frozen=True, slots=True)
class CronSpec:
    """Five-field cron expression: minute hour day-of-month month day-of-week (0/7 = Sunday)."""

    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    text: str

    @classmethod
    def parse(cls, expr: str) -> CronSpec:
        parts = expr.split()
        if len(parts) != 5:
            raise CronError(f"cron expression needs 5 fields: {expr!r}")
        try:
            weekdays = {7 if d == 0 else d for d in _expand(parts[4], 0, 7)}  # 0 and 7 = Sunday
            return cls(
                minutes=frozenset(_expand(parts[0], 0, 59)),
                hours=frozenset(_expand(parts[1], 0, 23)),
                days=frozenset(_expand(parts[2], 1, 31)),
                months=frozenset(_expand(parts[3], 1, 12)),
                weekdays=frozenset(weekdays),
                text=expr,
            )
        except ValueError as exc:
            raise CronError(f"invalid cron expression {expr!r}: {exc}") from exc

    def matches(self, dt: datetime) -> bool:
        return (
            dt.minute in self.minutes
            and dt.hour in self.hours
            and dt.day in self.days
            and dt.month in self.months
            and dt.isoweekday() in self.weekdays
        )

    def next_after(self, dt: datetime) -> datetime:
        """First matching minute strictly after ``dt`` (searches up to 366 days)."""
        candidate = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = candidate + timedelta(days=366)
        while candidate <= limit:
            if self.matches(candidate):
                return candidate
            candidate += timedelta(minutes=1)
        raise CronError(f"cron expression {self.text!r} never matches")


# ── one job ──────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class JobOutcome:
    job_id: str
    archive: Path | None
    verified: bool
    deleted: list[Path] = field(default_factory=list)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None


def run_backup_job(
    engine: Engine,
    *,
    target_dir: Path,
    storage_path: Path | None,
    tenant_slug: str | None = None,
    tenant_id: str | None = None,
    include_snapshot: bool = True,
    verify: bool = True,
    retention: tuple[int, int, int] | None = (7, 8, 12),
    now: datetime | None = None,
) -> JobOutcome:
    """create → verify → retention, recorded as one ``backup_job`` row."""
    now = now or datetime.now(UTC)
    with Session(engine) as session:
        job = orm.BackupJob(tenant_id=tenant_id, started_at=now, status="running")
        session.add(job)
        session.commit()
        job_id = job.id

    outcome = JobOutcome(job_id=job_id, archive=None, verified=False)
    status = "finished"
    try:
        archive = create_backup(
            engine,
            target_dir,
            tenant_slug,
            include_sqlite_snapshot=include_snapshot,
            storage_path=storage_path,
            now=now,
        )
        outcome.archive = archive.path
        outcome.warnings.extend(archive.warnings)
        if verify:
            vr = verify_backup(archive.path)
            outcome.verified = vr.ok
            if not vr.ok:
                status = "verify_failed"
                outcome.error = "verification failed: " + "; ".join(vr.problems)
                mark_failed(archive.path, outcome.error)
        if retention is not None and outcome.error is None:
            d, w, m = retention
            outcome.deleted = apply_retention(target_dir, daily=d, weekly=w, monthly=m, now=now)
    except Exception as exc:
        status = "failed"
        outcome.error = f"{type(exc).__name__}: {exc}"

    with Session(engine) as session:
        stored = session.get(orm.BackupJob, job_id)
        if stored is not None:
            stored.finished_at = datetime.now(UTC)
            stored.status = status
            stored.verified = outcome.verified
            stored.error = outcome.error
            if outcome.archive is not None and outcome.archive.exists():
                stored.path = str(outcome.archive)
                stored.size = outcome.archive.stat().st_size
            session.commit()
    return outcome


# ── loop ─────────────────────────────────────────────────────────────────────


def touch_alive(target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    marker = target_dir / ALIVE_MARKER
    marker.write_text(datetime.now(UTC).isoformat() + "\n", encoding="utf-8")
    return marker


def run_scheduled(
    engine: Engine,
    *,
    cron: str,
    target_dir: Path,
    storage_path: Path | None,
    retention: tuple[int, int, int] = (7, 8, 12),
    include_snapshot: bool = True,
    once: bool = False,
    sleep: Callable[[float], None] = _time.sleep,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    on_outcome: Callable[[JobOutcome], None] | None = None,
    max_cycles: int | None = None,
) -> list[JobOutcome]:
    """Run backups on ``cron``. ``once=True`` runs one job immediately and returns."""
    spec = CronSpec.parse(cron)
    outcomes: list[JobOutcome] = []
    touch_alive(target_dir)
    if once:
        outcome = run_backup_job(
            engine,
            target_dir=target_dir,
            storage_path=storage_path,
            include_snapshot=include_snapshot,
            retention=retention,
            now=clock(),
        )
        outcomes.append(outcome)
        if on_outcome:
            on_outcome(outcome)
        touch_alive(target_dir)
        return outcomes

    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        now = clock()
        due = spec.next_after(now)
        while (remaining := (due - clock()).total_seconds()) > 0:
            sleep(min(remaining, 60.0))
            touch_alive(target_dir)
        outcome = run_backup_job(
            engine,
            target_dir=target_dir,
            storage_path=storage_path,
            include_snapshot=include_snapshot,
            retention=retention,
            now=clock(),
        )
        outcomes.append(outcome)
        if on_outcome:
            on_outcome(outcome)
        touch_alive(target_dir)
        cycles += 1
    return outcomes


__all__ = [
    "ALIVE_MARKER",
    "CronError",
    "CronSpec",
    "JobOutcome",
    "run_backup_job",
    "run_scheduled",
    "touch_alive",
]
