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


class Health:
    def __init__(
        self, engine: Engine, session_factory: sessionmaker[Session], storage_path: Path
    ) -> None:
        self.engine = engine
        self.session_factory = session_factory
        self.storage_path = storage_path

    def execute(self) -> dto.HealthView:
        checks: dict[str, str] = {"process": "ok"}
        backup_age: float | None = None
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
                backup_age = round(
                    (datetime.now(UTC) - latest.finished_at).total_seconds() / 3600, 1
                )
                checks["backup"] = "ok" if backup_age <= 30 else "stale"
            else:
                checks["backup"] = "none"
        except Exception:  # pragma: no cover
            checks["backup"] = "unknown"
        status = (
            "ok"
            if all(v in ("ok", "none") for k, v in checks.items() if k != "backup")
            else "degraded"
        )
        if os.environ.get("VICTUS_HEALTH_FORCE_DEGRADED"):
            status = "degraded"
        return dto.HealthView(
            status=status, version=__version__, checks=checks, backup_age_hours=backup_age
        )
