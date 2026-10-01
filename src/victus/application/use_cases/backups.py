"""Backup jobs as the API shows them: what ran, when, where it went and how it ended."""

from __future__ import annotations

from victus.application import dto
from victus.application.errors import ValidationFailed
from victus.application.tenant_context import SCOPE_ADMIN
from victus.application.use_cases._base import UseCase

#: Enough for a month of nightly runs; the table keeps everything.
MAX_JOBS = 200


class ListBackupJobs(UseCase):
    """Newest first: this tenant's jobs and the all-tenant ones. Needs ``admin``.

    A job names paths on the server's disk and says whether the data is safe, which is
    operator knowledge, not something a read token for the diary should see.
    """

    def execute(self, limit: int = 20) -> list[dto.BackupJobView]:
        self.ctx.require(SCOPE_ADMIN)
        if not 1 <= limit <= MAX_JOBS:
            raise ValidationFailed(f"limit must be between 1 and {MAX_JOBS}")
        with self._uow() as uow:
            return [
                dto.BackupJobView(
                    id=j.id,
                    tenant_id=j.tenant_id,
                    started_at=j.started_at,
                    finished_at=j.finished_at,
                    status=j.status,
                    path=j.path,
                    size=j.size,
                    verified=j.verified,
                    error=j.error,
                )
                for j in uow.backup_jobs.list(limit)
            ]
