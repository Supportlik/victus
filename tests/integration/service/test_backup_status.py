"""T-SVC-250…253: the backup check of `Health`, recording a job, and `ListBackupJobs`."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from victus.application.errors import ValidationFailed
from victus.application.tenant_context import SCOPE_ADMIN, SCOPE_READ, ScopeError, TenantContext
from victus.application.use_cases._base import UowFactory
from victus.application.use_cases.backups import ListBackupJobs
from victus.application.use_cases.system import Health
from victus.backup.jobs import RecordError, parse_timestamp, record_job, tenant_id_for

pytestmark = pytest.mark.service

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _health(
    engine: Engine, sf: sessionmaker[Session], tmp_path: Path, max_age: int = 30
) -> tuple[str, str, float | None]:
    view = Health(engine, sf, tmp_path / "blobs", backup_max_age_hours=max_age, now=NOW).execute()
    return view.checks["backup"], view.status, view.backup_age_hours


def test_t_svc_250_backup_check_boundaries(
    engine: Engine, session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    """T-SVC-250: none → degraded; exactly max age → ok; a tenth of an hour past → degraded;
    a failed job never counts; `status` follows the backup check."""
    assert _health(engine, session_factory, tmp_path) == ("degraded", "degraded", None)
    record_job(
        engine,
        path="/b/failed.tar",
        finished_at=NOW - timedelta(hours=1),
        status="failed",
        error="x",
        now=NOW,
    )
    assert _health(engine, session_factory, tmp_path)[0] == "degraded"
    record_job(engine, path="/b/ok.tar", finished_at=NOW - timedelta(hours=30), now=NOW)
    assert _health(engine, session_factory, tmp_path) == ("ok", "ok", 30.0)
    assert _health(engine, session_factory, tmp_path, max_age=29)[0] == "degraded"
    view = Health(
        engine, session_factory, tmp_path / "blobs", now=NOW + timedelta(minutes=6)
    ).execute()
    assert view.checks["backup"] == "degraded" and view.backup_age_hours == 30.1
    assert view.backup_last_at == NOW - timedelta(hours=30)


def test_t_svc_251_record_job_refuses_what_it_cannot_trust(engine: Engine) -> None:
    """T-SVC-251: empty path, naive or future time, negative size, unknown status, a
    failure without an error or a success with one are refused and write nothing."""
    ok = {"path": "/b/x.tar", "finished_at": NOW - timedelta(hours=1), "now": NOW}
    for bad, msg in (
        ({"path": "  "}, "path"),
        ({"finished_at": datetime(2026, 9, 15, 3, 0)}, "time zone"),
        ({"finished_at": NOW + timedelta(minutes=1)}, "future"),
        ({"size": -1}, "negative"),
        ({"status": "verify_failed"}, "status"),
        ({"status": "failed"}, "error"),
        ({"status": "finished", "error": "boom"}, "failed"),
    ):
        with pytest.raises(RecordError, match=msg):
            record_job(engine, **{**ok, **bad})  # type: ignore[arg-type]
    job = record_job(
        engine,
        path=" /b/x.tar ",
        size=7,
        finished_at=(NOW - timedelta(hours=1)).astimezone(timezone(timedelta(hours=2))),
        now=NOW,
    )
    assert job.status == "finished" and job.finished_at == NOW - timedelta(hours=1)
    assert job.finished_at.tzinfo is UTC


def test_t_svc_252_parse_timestamp_and_tenant(
    engine: Engine, tenants: tuple[TenantContext, TenantContext]
) -> None:
    """T-SVC-252: `Z` and offsets parse to UTC; a time without offset and garbage are
    refused; a tenant slug resolves to its id, an unknown one is refused."""
    assert parse_timestamp("2026-09-15T03:00:00Z") == datetime(2026, 9, 15, 3, tzinfo=UTC)
    assert parse_timestamp("2026-09-15T05:00:00+02:00") == datetime(2026, 9, 15, 3, tzinfo=UTC)
    with pytest.raises(RecordError, match="offset"):
        parse_timestamp("2026-09-15T03:00:00")
    with pytest.raises(RecordError, match="ISO 8601"):
        parse_timestamp("last night")
    assert tenant_id_for(engine, "alice") == tenants[0].tenant_id
    with pytest.raises(RecordError, match="carol"):
        tenant_id_for(engine, "carol")


def test_t_svc_253_list_backup_jobs(
    engine: Engine, factory: UowFactory, alice: TenantContext, bob: TenantContext
) -> None:
    """T-SVC-253: needs `admin`; newest first; own and all-tenant jobs only; limit bounded."""
    record_job(engine, path="/b/all-old", finished_at=NOW - timedelta(hours=9), now=NOW)
    record_job(
        engine,
        path="/b/alice",
        finished_at=NOW - timedelta(hours=5),
        tenant_id=alice.tenant_id,
        now=NOW,
    )
    record_job(
        engine,
        path="/b/bob",
        finished_at=NOW - timedelta(hours=1),
        tenant_id=bob.tenant_id,
        now=NOW,
    )
    reader = replace(alice, scopes=frozenset({SCOPE_READ}))
    with pytest.raises(ScopeError, match="admin"):
        ListBackupJobs(factory, reader).execute()
    admin = replace(alice, scopes=frozenset({SCOPE_ADMIN}))
    jobs = ListBackupJobs(factory, admin).execute()
    assert [j.path for j in jobs] == ["/b/alice", "/b/all-old"]
    assert jobs[0].tenant_id == alice.tenant_id and jobs[1].tenant_id is None
    assert jobs[0].finished_at == NOW - timedelta(hours=5)
    assert [j.path for j in ListBackupJobs(factory, admin).execute(limit=1)] == ["/b/alice"]
    for bad in (0, 201):
        with pytest.raises(ValidationFailed):
            ListBackupJobs(factory, admin).execute(limit=bad)
