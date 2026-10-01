"""Record a backup that happened as one ``backup_job`` row.

The scheduler records its own runs (:func:`victus.backup.schedule.run_backup_job`). This
module is for everything else: ``victus backup create`` run by hand, and a backup the host
made without Victus (an encrypted ``tar`` of the data volume on a timer, a snapshot of the
disk) that reports in with ``victus backup record``. ``/health`` and ``GET /backup/jobs``
read these rows, so a backup that is never recorded is a backup Victus cannot know about.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from victus.infrastructure.db import orm

#: What a recorded job may say about itself. ``verify_failed`` belongs to the scheduler,
#: which is the only one that verifies.
RECORDABLE_STATUSES = ("finished", "failed")


class RecordError(ValueError):
    """The report of a backup cannot be recorded as given."""


@dataclass(frozen=True, slots=True)
class RecordedJob:
    id: str
    status: str
    finished_at: datetime


def parse_timestamp(text: str) -> datetime:
    """An ISO 8601 instant with its offset (``2026-09-15T03:00:00Z``).

    A time without an offset is refused rather than guessed: the host's clock and the
    server's may disagree, and a backup placed hours off is a wrong age on ``/health``.
    """
    try:
        value = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise RecordError(f"not an ISO 8601 timestamp: {text!r}") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise RecordError(f"timestamp needs an offset, e.g. {text.strip()}Z: {text!r}")
    return value.astimezone(UTC)


def tenant_id_for(engine: Engine, slug: str) -> str:
    with Session(engine) as session:
        tenant_id = session.scalar(select(orm.Tenant.id).where(orm.Tenant.slug == slug))
    if tenant_id is None:
        raise RecordError(f"no tenant with slug {slug!r}")
    return tenant_id


def record_job(
    engine: Engine,
    *,
    path: str,
    finished_at: datetime,
    size: int | None = None,
    tenant_id: str | None = None,
    status: str = "finished",
    error: str | None = None,
    verified: bool = False,
    now: datetime | None = None,
) -> RecordedJob:
    """Write one ``backup_job`` row for a backup that already happened.

    ``finished_at`` must carry an offset and must not lie in the future; ``size`` is in
    bytes. A ``failed`` job needs its ``error``; a ``finished`` one must not have one.
    """
    now = now or datetime.now(UTC)
    if not path.strip():
        raise RecordError("path must not be empty")
    if status not in RECORDABLE_STATUSES:
        raise RecordError(f"status must be one of {', '.join(RECORDABLE_STATUSES)}")
    if finished_at.tzinfo is None or finished_at.utcoffset() is None:
        raise RecordError("finished_at needs a time zone")
    finished_at = finished_at.astimezone(UTC)
    if finished_at > now:
        raise RecordError(f"finished_at {finished_at.isoformat()} lies in the future")
    if size is not None and size < 0:
        raise RecordError("size must not be negative")
    if status == "failed" and not (error and error.strip()):
        raise RecordError("a failed backup needs its error")
    if status == "finished" and error:
        raise RecordError("a finished backup has no error; record it as failed")
    with Session(engine) as session:
        job = orm.BackupJob(
            tenant_id=tenant_id,
            started_at=finished_at,
            finished_at=finished_at,
            status=status,
            path=path.strip(),
            size=size,
            verified=verified,
            error=error.strip() if error else None,
        )
        session.add(job)
        session.commit()
        return RecordedJob(id=job.id, status=job.status, finished_at=finished_at)


__all__ = [
    "RECORDABLE_STATUSES",
    "RecordError",
    "RecordedJob",
    "parse_timestamp",
    "record_job",
    "tenant_id_for",
]
