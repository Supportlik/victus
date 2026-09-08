"""Retention: keep the newest N daily, weekly and monthly archives; delete the rest.

Timestamps come from the file name (``victus-<scope>-<UTC>.zip``), never from
the file system. Archives with a ``<name>.failed`` marker (written by the
scheduler when verification failed) and the newest archive are never deleted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from victus.backup.export import parse_archive_name

FAILED_SUFFIX = ".failed"


@dataclass(slots=True)
class RetentionPlan:
    keep: list[Path] = field(default_factory=list)
    delete: list[Path] = field(default_factory=list)
    protected: list[Path] = field(default_factory=list)


def _newest_per_bucket(archives: list[tuple[datetime, Path]], key: str, limit: int) -> set[Path]:
    """Newest archive of each bucket (day / ISO week / month) for the ``limit`` newest buckets."""
    buckets: dict[str, tuple[datetime, Path]] = {}
    for ts, path in archives:
        if key == "day":
            b = ts.strftime("%Y-%m-%d")
        elif key == "week":
            iso = ts.isocalendar()
            b = f"{iso.year}-W{iso.week:02d}"
        else:
            b = ts.strftime("%Y-%m")
        if b not in buckets or ts > buckets[b][0]:
            buckets[b] = (ts, path)
    newest = sorted(buckets.values(), key=lambda t: t[0], reverse=True)[:limit]
    return {p for _, p in newest}


def plan_retention(
    target_dir: Path,
    *,
    daily: int = 7,
    weekly: int = 8,
    monthly: int = 12,
    scope: str | None = None,
    now: datetime | None = None,
) -> RetentionPlan:
    """Decide without touching anything. Per scope (tenant / all) independently."""
    plan = RetentionPlan()
    if not target_dir.is_dir():
        return plan
    now = now or datetime.now(UTC)
    by_scope: dict[str, list[tuple[datetime, Path]]] = {}
    for p in target_dir.iterdir():
        parsed = parse_archive_name(p)
        if parsed is None:
            continue
        s, ts = parsed
        if scope is not None and s != scope:
            continue
        if ts > now:
            continue
        by_scope.setdefault(s, []).append((ts, p))

    for archives in by_scope.values():
        archives.sort(key=lambda t: t[0], reverse=True)
        keep = set()
        keep |= _newest_per_bucket(archives, "day", daily)
        keep |= _newest_per_bucket(archives, "week", weekly)
        keep |= _newest_per_bucket(archives, "month", monthly)
        keep.add(archives[0][1])  # newest is always kept
        for _ts, path in archives:
            if path.with_name(path.name + FAILED_SUFFIX).exists():
                plan.protected.append(path)
                keep.add(path)
        for _ts, path in archives:
            (plan.keep if path in keep else plan.delete).append(path)
    return plan


def apply_retention(
    target_dir: Path,
    *,
    daily: int = 7,
    weekly: int = 8,
    monthly: int = 12,
    scope: str | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """Delete archives outside the retention windows; return what was (or would be) deleted."""
    plan = plan_retention(
        target_dir, daily=daily, weekly=weekly, monthly=monthly, scope=scope, now=now
    )
    if not dry_run:
        for path in plan.delete:
            path.unlink(missing_ok=True)
    return plan.delete


def mark_failed(archive: Path, reason: str) -> Path:
    marker = archive.with_name(archive.name + FAILED_SUFFIX)
    marker.write_text(reason + "\n", encoding="utf-8")
    return marker


__all__ = ["FAILED_SUFFIX", "RetentionPlan", "apply_retention", "mark_failed", "plan_retention"]
