"""Tokens, recovery codes and sessions at the use-case level."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from victus.application.errors import Unauthenticated, ValidationFailed
from victus.application.tenant_context import SCOPE_READ, SCOPE_WRITE, TenantContext
from victus.application.use_cases import auth as auth_uc
from victus.application.use_cases import tenants as tenants_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.auth import recovery, tokens
from victus.infrastructure.auth.lookup import SqlAuthLookup

pytestmark = pytest.mark.service


def test_recovery_code_roundtrip() -> None:
    code = recovery.generate_recovery_code()
    assert len(code) == 29 and code.count("-") == 4
    h = recovery.hash_recovery_code(code)
    assert recovery.verify_recovery_code(h, code.upper().replace("-", " "))
    assert not recovery.verify_recovery_code(h, "wrong-code")
    assert not recovery.verify_recovery_code(None, code)


def test_token_format_and_hash() -> None:
    t = tokens.generate_token()
    assert t.clear_text.startswith("vct_") and t.prefix == t.clear_text[:12]
    assert tokens.hash_token(t.clear_text) == t.token_hash
    assert tokens.looks_like_token(t.clear_text)
    assert not tokens.looks_like_token("Bearer xyz")


def test_t_api_007_010_token_lifecycle(
    factory: UowFactory, alice: TenantContext, session_factory: sessionmaker[Session]
) -> None:
    """T-API-007/008/009/010 at use-case level: single display, scopes, expiry, revocation."""
    created = auth_uc.CreateToken(factory, alice).execute("ci", [SCOPE_READ], None)
    assert created.token.startswith("vct_")
    listed = auth_uc.ListTokens(factory, alice).execute()
    assert listed[0].prefix == created.prefix and not hasattr(listed[0], "token")

    with session_factory() as s:
        ctx = auth_uc.ResolveToken(SqlAuthLookup(s)).execute(created.token)
        assert ctx is not None and ctx.tenant_id == alice.tenant_id
        assert ctx.has_scope(SCOPE_READ) and not ctx.has_scope(SCOPE_WRITE)
        assert auth_uc.ResolveToken(SqlAuthLookup(s)).execute("vct_nope_xxxxxxxx") is None

    with pytest.raises(ValidationFailed):
        auth_uc.CreateToken(factory, alice).execute("bad", ["fly"], None)
    with pytest.raises(ValidationFailed):
        auth_uc.CreateToken(factory, alice).execute(
            "long", [SCOPE_READ], datetime.now(UTC) + timedelta(days=400)
        )

    expired = auth_uc.CreateToken(factory, alice).execute(
        "old", [SCOPE_READ], datetime.now(UTC) + timedelta(seconds=1)
    )
    with factory(alice) as u:
        row = next(t for t in u.users.tokens() if t.id == expired.id)
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        u.commit()
    with session_factory() as s:
        assert auth_uc.ResolveToken(SqlAuthLookup(s)).execute(expired.token) is None

    auth_uc.RevokeToken(factory, alice).execute(created.id)
    with session_factory() as s:
        assert auth_uc.ResolveToken(SqlAuthLookup(s)).execute(created.token) is None


def test_t_api_006_recovery_creates_restricted_session(
    factory: UowFactory, alice: TenantContext, session_factory: sessionmaker[Session]
) -> None:
    """T-API-006: recovery code → short session flagged as recovery."""
    created = tenants_uc.CreateUser(factory, alice).execute("Alice", "alice@example.com", "owner")
    with session_factory() as s:
        lookup = SqlAuthLookup(s)
        with pytest.raises(Unauthenticated):
            auth_uc.Recover(lookup).execute("alice@example.com", "nope", "ua")
        info = auth_uc.Recover(lookup).execute("alice@example.com", created.recovery_code, "ua")
        assert info.recovery is True
        assert info.expires_at - datetime.now(UTC) < timedelta(minutes=16)
        resolved = auth_uc.ResolveSession(lookup).execute(info.session_id)
        assert resolved is not None and resolved[1] is True
        ctx = resolved[0]
        assert ctx.user_id == created.user.id
        auth_uc.Logout(lookup).execute(info.session_id)
        assert auth_uc.ResolveSession(lookup).execute(info.session_id) is None

    reset = tenants_uc.ResetRecoveryCode(factory, alice).execute("alice@example.com")
    with session_factory() as s:
        with pytest.raises(Unauthenticated):
            auth_uc.Recover(SqlAuthLookup(s)).execute(
                "alice@example.com", created.recovery_code, "ua"
            )
        assert auth_uc.Recover(SqlAuthLookup(s)).execute(
            "alice@example.com", reset.recovery_code, "ua"
        )
