"""T-API-150…156: backup state on /health and the read-only backup jobs API."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.integration.api.conftest import ORIGIN, RP_ID, Account, Session, bearer
from tests.integration.api.test_auth_api import _login, _register
from tests.integration.api.webauthn_device import SoftAuthenticator
from victus.api.app import create_app
from victus.application.tenant_context import (
    SCOPE_ADMIN,
    SCOPE_AGENT_WRITE,
    SCOPE_APPROVE,
    SCOPE_CAPTURE_READ,
    SCOPE_CAPTURE_WRITE,
    SCOPE_READ,
    SCOPE_WRITE,
)
from victus.application.use_cases._base import UowFactory
from victus.backup.jobs import record_job
from victus.config.server import ServerConfig
from victus.infrastructure.migrations import runner

pytestmark = pytest.mark.api

JOBS = "/api/v1/backup/jobs"


def _job(
    app: FastAPI,
    hours_ago: float,
    *,
    path: str = "/backups/victus-all.zip",
    tenant_id: str | None = None,
    status: str = "finished",
    error: str | None = None,
) -> str:
    return record_job(
        app.state.engine,
        path=path,
        size=1024,
        finished_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        tenant_id=tenant_id,
        status=status,
        error=error,
    ).id


def test_t_api_150_health_without_any_backup_is_degraded(client: TestClient) -> None:
    """T-API-150: never a successful backup → `checks.backup` and `status` read `degraded`."""
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["backup"] == "degraded"
    assert body["status"] == "degraded"
    assert body["backup_age_hours"] is None and body["backup_last_at"] is None
    assert body["backup_max_age_hours"] == 30
    # everything else is still fine; only the backup pulls the status down
    assert all(v == "ok" for k, v in body["checks"].items() if k != "backup")


def test_t_api_151_health_with_a_fresh_backup_is_ok(api_app: FastAPI, client: TestClient) -> None:
    """T-API-151: a backup two hours old → `ok`, its age and when it finished."""
    _job(api_app, 2)
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"]["backup"] == "ok" and body["status"] == "ok"
    assert body["backup_age_hours"] == pytest.approx(2.0, abs=0.1)
    last = datetime.fromisoformat(body["backup_last_at"])
    assert abs((datetime.now(UTC) - last) - timedelta(hours=2)) < timedelta(minutes=1)


def test_t_api_152_health_with_a_stale_backup_is_degraded(
    api_app: FastAPI, client: TestClient
) -> None:
    """T-API-152: the newest success 40 h old → `degraded` with its age; a newer failed
    job does not count as a backup."""
    _job(api_app, 40)
    _job(api_app, 1, status="failed", error="disk full")
    r = client.get("/api/v1/health")
    assert r.status_code == 200  # a warning, not an outage: the healthcheck stays green
    body = r.json()
    assert body["checks"]["backup"] == "degraded" and body["status"] == "degraded"
    assert body["backup_age_hours"] == pytest.approx(40.0, abs=0.1)


@pytest.fixture
def lenient_app(tmp_path: Path) -> Iterator[FastAPI]:
    cfg = ServerConfig(  # type: ignore[call-arg]
        _env_file=None,
        database={"url": "sqlite://"},
        storage={"path": str(tmp_path / "blobs")},
        auth={"rp_id": RP_ID, "origin": ORIGIN},
        backup={"max_age_hours": 72},
    )
    application = create_app(cfg)
    runner.upgrade(engine=application.state.engine)
    yield application
    application.state.engine.dispose()


def test_t_api_152_max_age_hours_is_configurable(lenient_app: FastAPI) -> None:
    """T-API-152: with `backup.max_age_hours: 72` the same 40-hour-old backup is `ok`."""
    _job(lenient_app, 40)
    with TestClient(lenient_app) as c:
        body = c.get("/api/v1/health").json()
    assert body["checks"]["backup"] == "ok" and body["backup_max_age_hours"] == 72


def test_t_api_153_backup_routes_need_authentication(client: TestClient) -> None:
    """T-API-153: anonymous → 401 on the jobs list; the old 501 placeholder is gone, so
    other paths under /backup are plain 404 and never answer 501 before authentication."""
    r = client.get(JOBS)
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    for method, path in (
        ("POST", "/api/v1/backup/export"),
        ("GET", "/api/v1/backup/schedule"),
        ("GET", "/api/v1/backup"),
    ):
        assert client.request(method, path).status_code == 404, path
    r = client.get(JOBS, headers={"Authorization": "Bearer vct_not-a-real-token"})
    assert r.status_code == 401


def test_t_api_154_jobs_need_the_admin_scope(
    api_app: FastAPI, client: TestClient, api_factory: UowFactory, alice_account: Account
) -> None:
    """T-API-154: every scope short of `admin` → 403; `admin` → 200."""
    _job(api_app, 3)
    for scope in (
        SCOPE_READ,
        SCOPE_WRITE,
        SCOPE_APPROVE,
        SCOPE_CAPTURE_READ,
        SCOPE_CAPTURE_WRITE,
        SCOPE_AGENT_WRITE,
    ):
        r = client.get(JOBS, headers=bearer(api_factory, alice_account, [scope]))
        assert r.status_code == 403, scope
        assert "admin" in r.json()["detail"]
    r = client.get(JOBS, headers=bearer(api_factory, alice_account, [SCOPE_ADMIN]))
    assert r.status_code == 200 and len(r.json()) == 1


@pytest.mark.covers("GET /api/v1/backup/jobs")
def test_t_api_155_jobs_list_newest_first_with_limit(
    api_app: FastAPI, client: TestClient, alice_token: dict[str, str]
) -> None:
    """T-API-155: newest first, every field, `limit` honoured and bounded."""
    assert client.get(JOBS, headers=alice_token).json() == []
    _job(api_app, 50, path="/backups/old.zip")
    failed = _job(api_app, 5, path="/mnt/backup/host.tar.gpg", status="failed", error="no space")
    _job(api_app, 1, path="/mnt/backup/host.tar.gpg")
    rows = client.get(JOBS, headers=alice_token).json()
    assert [r["path"] for r in rows] == [
        "/mnt/backup/host.tar.gpg",
        "/mnt/backup/host.tar.gpg",
        "/backups/old.zip",
    ]
    assert set(rows[0]) == {
        "id",
        "tenant_id",
        "started_at",
        "finished_at",
        "status",
        "path",
        "size",
        "verified",
        "error",
    }
    assert rows[0]["status"] == "finished" and rows[0]["size"] == 1024
    assert rows[0]["verified"] is False and rows[0]["tenant_id"] is None
    assert rows[1]["id"] == failed and rows[1]["status"] == "failed"
    assert rows[1]["error"] == "no space"
    assert len(client.get(JOBS, params={"limit": 1}, headers=alice_token).json()) == 1
    assert client.get(JOBS, params={"limit": 0}, headers=alice_token).status_code == 422
    assert client.get(JOBS, params={"limit": 201}, headers=alice_token).status_code == 422


def test_t_api_155_jobs_are_tenant_scoped(
    api_app: FastAPI,
    client: TestClient,
    alice_account: Account,
    bob_account: Account,
    alice_token: dict[str, str],
    bob_token: dict[str, str],
) -> None:
    """T-API-155: a tenant sees its own jobs and the all-tenant ones, never another's."""
    _job(api_app, 1, path="/backups/all.zip")
    _job(api_app, 2, path="/backups/alice.zip", tenant_id=alice_account.tenant_id)
    _job(api_app, 3, path="/backups/bob.zip", tenant_id=bob_account.tenant_id)
    alice = [r["path"] for r in client.get(JOBS, headers=alice_token).json()]
    bob = [r["path"] for r in client.get(JOBS, headers=bob_token).json()]
    assert alice == ["/backups/all.zip", "/backups/alice.zip"]
    assert bob == ["/backups/all.zip", "/backups/bob.zip"]


def test_t_api_156_sessions_full_and_recovery(api_app: FastAPI, alice_account: Account) -> None:
    """T-API-156: a signed-in owner reads the jobs; a recovery session is refused."""
    _job(api_app, 4)
    session = Session(api_app, alice_account)
    assert session.get(JOBS).status_code == 403  # recovery sessions only manage passkeys
    device = SoftAuthenticator(RP_ID, ORIGIN)
    _register(session, device)
    client = TestClient(api_app)
    r = _login(client, device, email=alice_account.email)
    assert r.status_code == 200  # type: ignore[attr-defined]
    rows = client.get(JOBS)
    assert rows.status_code == 200 and len(rows.json()) == 1
