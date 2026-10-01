"""T-SVC-404…408: tenants and users, health, the tenant context and the schema loader."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from victus import __version__
from victus.application import schemas_loader
from victus.application.errors import Conflict, NotFound, ValidationFailed
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import system
from victus.application.use_cases import tenants as uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.auth import recovery
from victus.infrastructure.db import orm

pytestmark = pytest.mark.service


def test_tenants_are_created_once_with_a_valid_slug(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-404: a slug is lowercase and unique; the name falls back to the slug."""
    for bad in ("A", "Carol", "-carol", "carol_1", "x"):
        with pytest.raises(ValidationFailed):
            uc.CreateTenant(factory, alice).execute(bad, "Carol")
    carol = uc.CreateTenant(factory, alice).execute("carol", "")
    assert (carol.slug, carol.name) == ("carol", "carol")
    named = uc.CreateTenant(factory, alice).execute("dave-2", "Dave")
    assert (named.slug, named.name) == ("dave-2", "Dave")
    with pytest.raises(Conflict):
        uc.CreateTenant(factory, alice).execute("alice", "Alice again")

    assert uc.GetTenant(factory, alice).execute().slug == "alice"
    ctx = TenantContext(tenant_id=carol.id)
    assert uc.GetTenant(factory, ctx).execute() == carol
    with pytest.raises(NotFound):
        uc.GetTenant(factory, TenantContext(tenant_id="no-such-tenant")).execute()


def test_users_get_a_recovery_code_that_can_be_reset(
    factory: UowFactory, alice: TenantContext, bob: TenantContext
) -> None:
    """T-SVC-405: e-mail and role are checked, twins refused, the code verifies and rotates."""
    with pytest.raises(ValidationFailed):
        uc.CreateUser(factory, alice).execute("Alice", "not-an-address")
    with pytest.raises(ValidationFailed):
        uc.CreateUser(factory, alice).execute("Alice", "alice@victus.example.com", role="root")
    made = uc.CreateUser(factory, alice).execute(
        "Alice", "  Alice@Victus.Example.com ", role="owner"
    )
    assert (made.user.email, made.user.role) == ("alice@victus.example.com", "owner")
    with pytest.raises(Conflict):
        uc.CreateUser(factory, alice).execute("Alice", "alice@victus.example.com")
    member = uc.CreateUser(factory, alice).execute("Guest", "guest@victus.example.com")
    assert member.user.role == "member"
    # the same address in another tenant is another person
    assert uc.CreateUser(factory, bob).execute("Bob", "alice@victus.example.com").user.email

    users = uc.ListUsers(factory, alice).execute()
    assert sorted(u.email or "" for u in users) == [
        "alice@victus.example.com",
        "guest@victus.example.com",
    ]
    assert [u.email for u in uc.ListUsers(factory, bob).execute()] == ["alice@victus.example.com"]

    reset = uc.ResetRecoveryCode(factory, alice).execute("ALICE@victus.example.com")
    assert reset.user.id == made.user.id and reset.recovery_code != made.recovery_code
    with factory(alice) as uow:
        stored = uow.users.get_by_email("alice@victus.example.com")
        assert stored is not None
        assert recovery.verify_recovery_code(stored.recovery_code_hash, reset.recovery_code)
        assert not recovery.verify_recovery_code(stored.recovery_code_hash, made.recovery_code)
    with pytest.raises(NotFound):
        uc.ResetRecoveryCode(factory, alice).execute("nobody@victus.example.com")


def _backup(session_factory: sessionmaker[Session], hours_ago: float) -> None:
    with session_factory() as s:
        s.add(
            orm.BackupJob(
                status="finished", finished_at=datetime.now(UTC) - timedelta(hours=hours_ago)
            )
        )
        s.commit()


def test_health_reports_each_check(
    engine: Engine,
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-SVC-406: database, migrations, storage and backup age, and the degraded switch."""
    monkeypatch.delenv("VICTUS_HEALTH_FORCE_DEGRADED", raising=False)
    health = system.Health(engine, session_factory, tmp_path / "blobs")
    fresh = health.execute()
    # no backup Victus knows about is a warning, not silence (#36)
    assert fresh.status == "degraded" and fresh.version == __version__
    assert fresh.checks == {
        "process": "ok",
        "db": "ok",
        "migrations": "ok",
        "storage": "ok",
        "backup": "degraded",
    }
    assert fresh.backup_age_hours is None
    assert not (tmp_path / "blobs" / ".victus-write-probe").exists(), "the probe is removed"

    _backup(session_factory, hours_ago=40)
    stale = health.execute()
    assert stale.checks["backup"] == "degraded" and stale.status == "degraded"
    assert stale.backup_age_hours == pytest.approx(40, abs=0.2)

    _backup(session_factory, hours_ago=2)
    recent = health.execute()
    assert recent.checks["backup"] == "ok" and recent.status == "ok"
    assert recent.backup_age_hours == pytest.approx(2, abs=0.2)

    blocker = tmp_path / "a-file"
    blocker.write_text("x", encoding="utf-8")
    unwritable = system.Health(engine, session_factory, blocker).execute()
    assert unwritable.checks["storage"] == "not writable" and unwritable.status == "degraded"

    monkeypatch.setenv("VICTUS_HEALTH_FORCE_DEGRADED", "1")
    assert health.execute().status == "degraded"


def test_the_actor_is_the_token_then_the_user_then_the_system() -> None:
    """T-SVC-407: audit rows name who acted; scopes are checked, admin holds them all."""
    assert TenantContext("t", user_id="u", token_id="k").actor_kind == "token"
    user = TenantContext("t", user_id="u")
    assert (user.actor_kind, user.actor_id) == ("user", "u")
    assert (TenantContext("t").actor_kind, TenantContext("t").actor_id) == ("system", None)
    admin = TenantContext("t", scopes=frozenset({"admin"}))
    assert admin.has_scope("approve")
    reader = TenantContext("t", scopes=frozenset({"read"}))
    with pytest.raises(PermissionError, match="write"):
        reader.require("write")


def test_schemas_come_from_the_package_or_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-SVC-408: a bundled schema wins, the checkout copy is the fallback, and a missing
    one says so."""
    load = schemas_loader.load_schema.__wrapped__  # the uncached function
    checkout = load("tenant-settings")
    assert checkout["type"] == "object"

    bundled = tmp_path / "schemas"
    bundled.mkdir()
    (bundled / "tenant-settings.schema.json").write_text(
        json.dumps({"title": "bundled"}), encoding="utf-8"
    )
    monkeypatch.setattr(schemas_loader.resources, "files", lambda _pkg: tmp_path)
    assert load("tenant-settings") == {"title": "bundled"}

    def missing_package(_pkg: str) -> Path:
        raise ModuleNotFoundError("victus")

    monkeypatch.setattr(schemas_loader.resources, "files", missing_package)
    assert load("tenant-settings") == checkout
    with pytest.raises(FileNotFoundError, match="no-such"):
        load("no-such")
