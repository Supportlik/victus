"""T-SVC-454…457: repository read paths the use-case tests do not reach, and the blob store."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from victus.application.ports.blob_storage import BlobNotFoundError
from victus.application.tenant_context import TenantContext
from victus.infrastructure.db import orm
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork
from victus.infrastructure.storage.fs_blob import FsBlobStorage

pytestmark = pytest.mark.service

Make = Callable[[TenantContext], SqlAlchemyUnitOfWork]
SHA = "ab" + "0" * 62


def test_t_svc_454_tenants_users_sessions_and_passkeys(
    uow_for: Make, tenants: tuple[TenantContext, TenantContext]
) -> None:
    """T-SVC-454: tenants are listed by slug; users are listed per tenant; a passkey for a
    user of another tenant is refused on add and on delete; a session is deleted once and
    a second delete is a no-op; tokens are listed per tenant."""
    alice, bob = tenants
    with uow_for(alice) as uow:
        assert [t.slug for t in uow.tenants.list()] == ["alice", "bob"]
        user = uow.users.add(orm.User(tenant_id=alice.tenant_id, display_name="Alice"))
        assert [u.id for u in uow.users.list()] == [user.id]
        session = uow.users.add_session(
            orm.Session(
                user_id=user.id,
                tenant_id=alice.tenant_id,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        uow.users.add_token(
            orm.ApiToken(
                tenant_id=alice.tenant_id,
                name="ci",
                prefix="vic_ci",
                token_hash="h1",
                scopes=["read"],
            )
        )
        uow.commit()
        session_id, user_id = session.id, user.id
    with uow_for(bob) as uow:
        foreign = orm.PasskeyCredential(
            user_id=user_id, credential_id=b"cred", public_key=b"key", sign_count=0
        )
        with pytest.raises(PermissionError):
            uow.users.add_passkey(foreign)
        with pytest.raises(PermissionError):
            uow.users.delete_passkey(foreign)
        assert uow.users.tokens() == []
    with uow_for(alice) as uow:
        assert [t.name for t in uow.users.tokens()] == ["ci"]
        uow.users.delete_session(session_id)
        assert uow.users.get_session(session_id) is None
        uow.users.delete_session(session_id)  # already gone: nothing happens
        uow.commit()


def test_t_svc_455_audit_and_backup_jobs(
    uow_for: Make, tenants: tuple[TenantContext, TenantContext]
) -> None:
    """T-SVC-455: an audit entry without an actor takes the context's; entries are read per
    target; backup jobs are this tenant's or global, a foreign one is refused, the newest
    finished one is found."""
    alice, bob = tenants
    with uow_for(alice) as uow:
        entry = uow.audit.add(
            orm.AuditLog(
                tenant_id=alice.tenant_id,
                actor_kind="",
                action="x.test",
                target_type="thing",
                target_id="1",
            )
        )
        assert entry.actor_kind == alice.actor_kind
        assert [e.action for e in uow.audit.for_target("thing", "1")] == ["x.test"]

        with pytest.raises(PermissionError):
            uow.backup_jobs.add(orm.BackupJob(tenant_id=bob.tenant_id))
        t0 = datetime(2026, 3, 1, tzinfo=UTC)
        own = uow.backup_jobs.add(
            orm.BackupJob(
                tenant_id=alice.tenant_id, status="finished", started_at=t0, finished_at=t0
            )
        )
        everyone = uow.backup_jobs.add(
            orm.BackupJob(
                tenant_id=None,
                status="finished",
                started_at=t0 + timedelta(hours=1),
                finished_at=t0 + timedelta(hours=1),
            )
        )
        uow.backup_jobs.add(orm.BackupJob(tenant_id=None, started_at=t0 + timedelta(hours=2)))
        assert uow.backup_jobs.get(own.id) is not None
        assert [j.id for j in uow.backup_jobs.list(limit=2)][1] == everyone.id
        latest = uow.backup_jobs.latest_finished()
        assert latest is not None and latest.id == everyone.id
        uow.commit()
    with uow_for(bob) as uow:
        assert uow.backup_jobs.get(own.id) is None


def test_t_svc_456_blob_store_writes_reads_and_refuses_escapes(tmp_path: Path) -> None:
    """T-SVC-456: a blob is written once and read back; a key with a path separator or
    ``..`` is refused when built and treated as missing when read, checked or deleted."""
    store = FsBlobStorage(tmp_path)
    key = store.put("t1", SHA, b"hello")
    assert key == f"t1/ab/{SHA}"
    assert store.put("t1", SHA, b"other bytes") == key  # already there: kept as it was
    assert store.get(key) == b"hello" and store.exists(key)

    for tenant, sha in (("t1", ""), ("t1", "a/b"), ("../t", SHA), ("t1", "..")):
        with pytest.raises(ValueError):
            store.key_for(tenant, sha)
    for bad in ("/etc/passwd", "../outside", ""):
        with pytest.raises(BlobNotFoundError):
            store.get(bad)
        assert store.exists(bad) is False
        store.delete(bad)  # nothing to do, no error

    with pytest.raises(BlobNotFoundError):
        store.get(f"t1/cd/{'c' * 64}")
    store.delete(key)
    assert not store.exists(key)
    store.delete(key)  # twice is fine


def test_t_svc_457_a_failed_write_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-SVC-457: when the final rename fails the temporary file is removed and the error
    surfaces."""
    store = FsBlobStorage(tmp_path)

    def refuse(_src: str, _dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("victus.infrastructure.storage.fs_blob.os.replace", refuse)
    with pytest.raises(OSError, match="disk full"):
        store.put("t1", SHA, b"data")
    assert list((tmp_path / "t1" / "ab").iterdir()) == []
