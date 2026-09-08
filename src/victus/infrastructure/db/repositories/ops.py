"""Audit log and backup jobs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, select

from victus.infrastructure.db import orm
from victus.infrastructure.db.repositories._base import Repo


class AuditRepo(Repo):
    def add(self, entry: orm.AuditLog) -> orm.AuditLog:
        self.guard(entry)
        if not entry.actor_kind:
            entry.actor_kind = self.ctx.actor_kind
            entry.actor_id = self.ctx.actor_id
        self.session.add(entry)
        self.session.flush()
        return entry

    def record(
        self, action: str, target_type: str, target_id: str, diff: dict[str, object] | None = None
    ) -> orm.AuditLog:
        return self.add(
            orm.AuditLog(
                tenant_id=self.tenant_id,
                actor_kind=self.ctx.actor_kind,
                actor_id=self.ctx.actor_id,
                action=action,
                target_type=target_type,
                target_id=str(target_id),
                diff=diff,
            )
        )

    def for_target(self, target_type: str, target_id: str) -> Sequence[orm.AuditLog]:
        return self.session.scalars(
            self.scoped(
                select(orm.AuditLog).where(
                    orm.AuditLog.target_type == target_type,
                    orm.AuditLog.target_id == str(target_id),
                ),
                orm.AuditLog,
            ).order_by(orm.AuditLog.created_at)
        ).all()


class BackupJobRepo(Repo):
    """Backup jobs may span all tenants (``tenant_id`` NULL); scoping is therefore
    "this tenant or global"."""

    def _scope(self, stmt: Select[Any]) -> Select[Any]:
        return stmt.where(
            (orm.BackupJob.tenant_id == self.tenant_id) | (orm.BackupJob.tenant_id.is_(None))
        )

    def add(self, job: orm.BackupJob) -> orm.BackupJob:
        if job.tenant_id is not None and job.tenant_id != self.tenant_id:
            raise PermissionError("backup job belongs to another tenant")
        self.session.add(job)
        self.session.flush()
        return job

    def get(self, job_id: str) -> orm.BackupJob | None:
        return self.session.scalar(
            self._scope(select(orm.BackupJob).where(orm.BackupJob.id == job_id))
        )

    def list(self, limit: int = 50) -> Sequence[orm.BackupJob]:
        return self.session.scalars(
            self._scope(select(orm.BackupJob))
            .order_by(orm.BackupJob.started_at.desc())
            .limit(limit)
        ).all()

    def latest_finished(self) -> orm.BackupJob | None:
        return self.session.scalar(
            self._scope(select(orm.BackupJob).where(orm.BackupJob.status == "finished"))
            .order_by(orm.BackupJob.finished_at.desc())
            .limit(1)
        )
