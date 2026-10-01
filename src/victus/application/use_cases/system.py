"""Health: database, migrations, storage, backup age."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from victus import __version__
from victus.application import dto
from victus.infrastructure.db import orm
from victus.infrastructure.migrations import runner

#: What ``checks.backup`` reads when the newest successful backup is recent enough.
BACKUP_OK = "ok"
#: No successful backup ever, or the newest one older than ``backup.max_age_hours``.
BACKUP_DEGRADED = "degraded"


class Health:
    """Every check is ``ok`` or says what is wrong; ``status`` is ``ok`` only if all are.

    The backup counts like the others: an instance without a backup Victus knows about is
    one that loses its data on the next disk failure, and ``/health`` is where that shows.
    """

    def __init__(
        self,
        engine: Engine,
        session_factory: sessionmaker[Session],
        storage_path: Path,
        *,
        backup_max_age_hours: int = 30,
        now: datetime | None = None,
    ) -> None:
        self.engine = engine
        self.session_factory = session_factory
        self.storage_path = storage_path
        self.backup_max_age_hours = backup_max_age_hours
        self.now = now

    def execute(self) -> dto.HealthView:
        checks: dict[str, str] = {"process": "ok"}
        backup_age: float | None = None
        backup_last_at: datetime | None = None
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["db"] = "ok"
        except Exception as exc:  # pragma: no cover - depends on a broken database
            checks["db"] = f"error: {exc.__class__.__name__}"
        try:
            checks["migrations"] = "ok" if runner.is_up_to_date(engine=self.engine) else "pending"
        except Exception as exc:  # pragma: no cover
            checks["migrations"] = f"error: {exc.__class__.__name__}"
        try:
            self.storage_path.mkdir(parents=True, exist_ok=True)
            probe = self.storage_path / ".victus-write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            checks["storage"] = "ok"
        except OSError:
            checks["storage"] = "not writable"
        try:
            with self.session_factory() as s:
                latest = s.scalar(
                    select(orm.BackupJob)
                    .where(orm.BackupJob.status == "finished")
                    .order_by(orm.BackupJob.finished_at.desc())
                    .limit(1)
                )
            if latest is not None and latest.finished_at is not None:
                backup_last_at = latest.finished_at
                now = self.now or datetime.now(UTC)
                backup_age = round(max(0.0, (now - backup_last_at).total_seconds()) / 3600, 1)
                fresh = backup_age <= self.backup_max_age_hours
                checks["backup"] = BACKUP_OK if fresh else BACKUP_DEGRADED
            else:
                checks["backup"] = BACKUP_DEGRADED
        except Exception:  # pragma: no cover
            checks["backup"] = "unknown"
        status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
        if os.environ.get("VICTUS_HEALTH_FORCE_DEGRADED"):
            status = "degraded"
        return dto.HealthView(
            status=status,
            version=__version__,
            checks=checks,
            backup_age_hours=backup_age,
            backup_last_at=backup_last_at,
            backup_max_age_hours=self.backup_max_age_hours,
        )
