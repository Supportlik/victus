"""Backup jobs (read-only). Creating and restoring backups stays on the CLI (docs/BACKUP.md)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from victus.api.deps import Ctx, Uow
from victus.api.schemas.common import Out
from victus.application.use_cases import backups as uc

router = APIRouter(tags=["backup"])


class BackupJobOut(Out):
    id: str
    #: ``null`` for a job that covers every tenant.
    tenant_id: str | None
    started_at: datetime
    finished_at: datetime | None
    #: ``running`` | ``finished`` | ``verify_failed`` | ``failed``
    status: str
    path: str | None
    size: int | None
    verified: bool
    error: str | None


@router.get(
    "/backup/jobs",
    response_model=list[BackupJobOut],
    summary="Recorded backups, newest first (admin)",
)
def list_backup_jobs(
    ctx: Ctx,
    uow: Uow,
    limit: Annotated[int, Query(ge=1, le=uc.MAX_JOBS)] = 20,
) -> list[BackupJobOut]:
    """Scheduled runs, ``victus backup create`` and host backups that reported in with
    ``victus backup record``: this tenant's and the all-tenant ones. Needs ``admin``."""
    return [BackupJobOut.model_validate(j) for j in uc.ListBackupJobs(uow, ctx).execute(limit)]
