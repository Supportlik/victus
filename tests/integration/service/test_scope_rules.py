"""T-SVC-200…205: scope requirements, role scopes and the use cases whose checks changed."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session, sessionmaker

from victus.application.errors import Forbidden, ValidationFailed
from victus.application.scope_profiles import PROFILES, WORKER, get_profile
from victus.application.tenant_context import (
    ALL_SCOPES,
    SCOPE_ADMIN,
    SCOPE_AGENT_WRITE,
    SCOPE_APPROVE,
    SCOPE_READ,
    SCOPE_WRITE,
    Requires,
    ScopeError,
    TenantContext,
    scopes_for_role,
)
from victus.application.use_cases import auth as auth_uc
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases import drafts as drafts_uc
from victus.application.use_cases import snapshots as snap_uc
from victus.application.use_cases import tenants as tenants_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.auth import sessions
from victus.infrastructure.auth.lookup import SqlAuthLookup
from victus.infrastructure.db import orm

pytestmark = pytest.mark.service

DAY = date(2026, 3, 10)


def _ctx(tenant: TenantContext, *scopes: str, user_id: str | None = None) -> TenantContext:
    return TenantContext(tenant_id=tenant.tenant_id, user_id=user_id, scopes=frozenset(scopes))


def test_t_svc_200_requires_reads_all_of_any_of() -> None:
    """T-SVC-200: groups must all hold, one scope of a group suffices, and the error says which."""
    r = Requires.of(SCOPE_READ, (SCOPE_AGENT_WRITE, SCOPE_WRITE))
    assert r.allows_scopes({SCOPE_READ, SCOPE_WRITE}) and r.allows_scopes(
        {SCOPE_READ, SCOPE_AGENT_WRITE}
    )
    assert not r.allows_scopes({SCOPE_READ}) and not r.allows_scopes({SCOPE_WRITE})
    assert r.allows_scopes({SCOPE_ADMIN}), "admin passes every check"
    assert r.minimal_sets() == [
        frozenset({SCOPE_AGENT_WRITE, SCOPE_READ}),
        frozenset({SCOPE_READ, SCOPE_WRITE}),
    ]
    assert r.label() == "read + (agent:write or write)"
    assert r.scopes == {SCOPE_READ, SCOPE_AGENT_WRITE, SCOPE_WRITE}
    with pytest.raises(ScopeError, match="scope 'agent:write' or 'write' required"):
        r.check(TenantContext(tenant_id="-", scopes=frozenset({SCOPE_READ})))
    with pytest.raises(ScopeError, match="scope 'read' required"):
        r.check(TenantContext(tenant_id="-", scopes=frozenset({SCOPE_WRITE})))
    r.check(TenantContext(tenant_id="-", scopes=frozenset({SCOPE_READ, SCOPE_WRITE})))
    assert Requires().allows_scopes(set()) and Requires().label() == "—"
    assert Requires.of(SCOPE_READ, SCOPE_READ).minimal_sets() == [frozenset({SCOPE_READ})]
    with pytest.raises(ValueError, match="unknown scopes"):
        Requires.of("settings")
    with pytest.raises(ValueError):
        Requires.of(())


def test_t_svc_201_role_scopes_and_resolution(
    factory: UowFactory, alice: TenantContext, session_factory: sessionmaker[Session]
) -> None:
    """T-SVC-201: a session carries its role's scopes, a token never more than its user's role."""
    assert scopes_for_role("owner") == ALL_SCOPES
    assert scopes_for_role("member") == ALL_SCOPES - {SCOPE_ADMIN}
    assert scopes_for_role("guest") == frozenset() and scopes_for_role(None) == frozenset()

    system = _ctx(alice, *ALL_SCOPES)
    member = tenants_uc.CreateUser(factory, system).execute("Carol", "carol@example.com")
    token = auth_uc.CreateToken(factory, system).execute("legacy", [SCOPE_READ, SCOPE_ADMIN], None)
    with session_factory() as s:
        row = s.get(orm.ApiToken, token.id)
        assert row is not None
        row.user_id = member.user.id  # minted for a member before the role cap existed
        sess = orm.Session(
            user_id=member.user.id,
            tenant_id=alice.tenant_id,
            expires_at=sessions.session_expiry(30),
        )
        s.add(sess)
        s.commit()
        session_id = sess.id
    with session_factory() as s:
        resolved = auth_uc.ResolveSession(SqlAuthLookup(s)).execute(session_id)
        assert resolved is not None
        ctx, recovery = resolved
        assert ctx.scopes == ALL_SCOPES - {SCOPE_ADMIN} and recovery is False
        capped = auth_uc.ResolveToken(SqlAuthLookup(s)).execute(token.token)
        assert capped is not None and capped.scopes == {SCOPE_READ}


class _Gone:
    """A lookup whose session and token point at a user that no longer exists."""

    def __init__(self) -> None:
        from datetime import UTC, datetime, timedelta
        from types import SimpleNamespace

        later = datetime.now(UTC) + timedelta(days=1)
        self.row = SimpleNamespace(
            id="x",
            tenant_id="t",
            user_id="usr_gone",
            expires_at=later,
            user_agent=None,
            revoked_at=None,
            scopes=["read"],
            last_used_at=None,
        )

    def session(self, _: str) -> object:
        return self.row

    def token_by_hash(self, _: str) -> object:
        return self.row

    def user(self, _: str) -> None:
        return None

    def commit(self) -> None:  # pragma: no cover - never reached
        raise AssertionError


def test_t_svc_201_a_vanished_user_resolves_to_nobody() -> None:
    """T-SVC-201: a session or token whose user is gone is no principal at all."""
    lookup = _Gone()
    assert auth_uc.ResolveSession(lookup).execute("x") is None  # type: ignore[arg-type]
    from victus.infrastructure.auth import tokens

    clear = tokens.generate_token().clear_text
    assert auth_uc.ResolveToken(lookup).execute(clear) is None  # type: ignore[arg-type]


def test_t_svc_202_tenant_administration_needs_admin(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-202: creating users, resetting recovery codes, listing users and reading the
    tenant need `admin`, on every path."""
    member_ctx = _ctx(alice, *(ALL_SCOPES - {SCOPE_ADMIN}))
    with pytest.raises(ScopeError):
        tenants_uc.CreateUser(factory, member_ctx).execute("M", "m@example.com", "owner")
    with pytest.raises(ScopeError):
        tenants_uc.ResetRecoveryCode(factory, member_ctx).execute("m@example.com")
    with pytest.raises(ScopeError):
        tenants_uc.ListUsers(factory, member_ctx).execute()
    with pytest.raises(ScopeError):
        tenants_uc.GetTenant(factory, member_ctx).execute()
    admin = _ctx(alice, SCOPE_ADMIN)
    created = tenants_uc.CreateUser(factory, admin).execute("M", "m@example.com")
    assert tenants_uc.ResetRecoveryCode(factory, admin).execute("m@example.com").recovery_code
    assert created.user.email in {u.email for u in tenants_uc.ListUsers(factory, admin).execute()}
    assert tenants_uc.GetTenant(factory, admin).execute().id == alice.tenant_id


def test_t_svc_203_tokens_grant_only_held_scopes_and_list_own(
    factory: UowFactory, alice: TenantContext
) -> None:
    """T-SVC-203: no grant beyond what the caller holds; a member lists and revokes only own."""
    system = _ctx(alice, *ALL_SCOPES)
    carol = tenants_uc.CreateUser(factory, system).execute("Carol", "carol@example.com")
    member = _ctx(alice, *(ALL_SCOPES - {SCOPE_ADMIN}), user_id=carol.user.id)
    with pytest.raises(Forbidden, match="admin"):
        auth_uc.CreateToken(factory, member).execute("x", [SCOPE_READ, SCOPE_ADMIN], None)
    own = auth_uc.CreateToken(factory, member).execute("own", [SCOPE_READ], None)
    other = auth_uc.CreateToken(factory, system).execute("other", [SCOPE_READ], None)
    assert [t.id for t in auth_uc.ListTokens(factory, member).execute()] == [own.id]
    with pytest.raises(Exception, match="not found"):
        auth_uc.RevokeToken(factory, member).execute(other.id)
    token_ctx = TenantContext(
        tenant_id=alice.tenant_id, token_id="tok_x", scopes=frozenset({SCOPE_READ})
    )
    with pytest.raises(ScopeError):
        auth_uc.ListTokens(factory, token_ctx).execute()
    with pytest.raises(ScopeError):
        auth_uc.RevokeToken(factory, token_ctx).execute(own.id)
    assert {t.id for t in auth_uc.ListTokens(factory, system).execute()} >= {own.id, other.id}


def test_t_svc_204_freezing_a_report_is_a_write(factory: UowFactory, alice: TenantContext) -> None:
    """T-SVC-204: `FreezeReport` needs `read` and `write`."""
    with pytest.raises(ScopeError, match="'write'"):
        snap_uc.FreezeReport(factory, _ctx(alice, SCOPE_READ)).execute(
            "checkup", "Check-up", {"x": 1}, period_start=DAY, period_end=DAY, today=DAY
        )
    view = snap_uc.FreezeReport(factory, _ctx(alice, SCOPE_READ, SCOPE_WRITE)).execute(
        "checkup", "Check-up", {"x": 1}, period_start=DAY, period_end=DAY, today=DAY
    )
    assert view.report_name == "checkup"


def test_t_svc_205_decisions_need_write_and_approve(
    factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-SVC-205: approving a day, an item or discarding drafts needs `write` + `approve`."""
    full = _ctx(alice, SCOPE_READ, SCOPE_WRITE, SCOPE_APPROVE)
    day_uc.CreateDay(factory, full).execute(DAY, reliable=True)
    approve_only = _ctx(alice, SCOPE_READ, SCOPE_APPROVE)
    with pytest.raises(ScopeError, match="'write'"):
        drafts_uc.ApproveDay(factory, approve_only).execute(DAY, [], close=True)
    with pytest.raises(ScopeError, match="'write'"):
        drafts_uc.DiscardDraft(factory, approve_only).execute(DAY)
    with pytest.raises(ScopeError, match="'write'"):
        drafts_uc.ApproveLineItem(factory, approve_only).execute(1)
    with pytest.raises(ValidationFailed):  # past the scope check: there is nothing to discard
        drafts_uc.DiscardDraft(factory, full).execute(DAY)


def test_t_svc_205_profiles_hold_known_scopes() -> None:
    """T-SVC-205: every profile names known scopes, none holds admin, the worker is the
    assistant, and only the full delegate decides."""
    for p in PROFILES:
        assert set(p.scopes) <= ALL_SCOPES and SCOPE_ADMIN not in p.scopes, p.key
        assert len(set(p.scopes)) == len(p.scopes)
    assert set(WORKER.scopes) == set(get_profile("assistant").scopes)
    assert [p.key for p in PROFILES if SCOPE_APPROVE in p.scopes] == ["full-delegate"]
    with pytest.raises(KeyError):
        get_profile("nope")
