"""Passkey, session and token use cases: refusals and edge cases (T-SVC-447..451)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.api.webauthn_device import SoftAuthenticator
from victus.application.errors import Forbidden, NotFound, Unauthenticated, ValidationFailed
from victus.application.tenant_context import SCOPE_READ, TenantContext
from victus.application.use_cases import auth as uc
from victus.application.use_cases import tenants as tenants_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.auth.lookup import SqlAuthLookup
from victus.infrastructure.auth.webauthn import InMemoryChallengeStore, WebAuthnService

pytestmark = pytest.mark.service

RP_ID = "victus.example.com"
ORIGIN = "https://victus.example.com"


@pytest.fixture
def webauthn() -> WebAuthnService:
    return WebAuthnService(RP_ID, "Victus", ORIGIN, InMemoryChallengeStore())


def _user(factory: UowFactory, tenant: TenantContext, email: str) -> TenantContext:
    created = tenants_uc.CreateUser(factory, tenant).execute("Alice", email, "owner")
    return TenantContext(tenant_id=tenant.tenant_id, user_id=created.user.id)


def _register(
    factory: UowFactory, ctx: TenantContext, webauthn: WebAuthnService, name: str | None
) -> tuple[SoftAuthenticator, dict[str, object], str]:
    device = SoftAuthenticator(RP_ID, ORIGIN)
    options = uc.BeginRegistration(factory, ctx, webauthn).execute(name)
    return device, device.register(options), str(options["ceremony_id"])


def test_t_svc_447_registration_needs_a_known_user_and_a_fresh_passkey(
    factory: UowFactory, alice: TenantContext, webauthn: WebAuthnService
) -> None:
    """T-SVC-447: registering a passkey needs a user session for an existing user; a
    failed verification is a validation error; the same credential cannot be added twice;
    the label falls back to the one chosen when the ceremony began."""
    with pytest.raises(Unauthenticated, match="user session"):
        uc.BeginRegistration(factory, alice, webauthn).execute("Laptop")
    ghost = TenantContext(tenant_id=alice.tenant_id, user_id="no-such-user")
    with pytest.raises(Unauthenticated, match="user not found"):
        uc.BeginRegistration(factory, ghost, webauthn).execute("Laptop")
    with pytest.raises(Unauthenticated, match="user session"):
        uc.FinishRegistration(factory, alice, webauthn).execute("x", {}, None)

    me = _user(factory, alice, "alice@victus.example.com")
    with pytest.raises(ValidationFailed, match="registration failed"):
        uc.FinishRegistration(factory, me, webauthn).execute("unknown-ceremony", {}, None)

    device, attestation, ceremony = _register(factory, me, webauthn, "Laptop")
    view = uc.FinishRegistration(factory, me, webauthn).execute(ceremony, attestation, None)
    assert view.name == "Laptop"

    # the same authenticator answers a second ceremony with the credential it already has
    options = uc.BeginRegistration(factory, me, webauthn).execute(None)
    same = device.register(options)
    with pytest.raises(ValidationFailed, match="already registered"):
        uc.FinishRegistration(factory, me, webauthn).execute(
            str(options["ceremony_id"]), same, None
        )
    assert [p.name for p in uc.ListPasskeys(factory, me).execute()] == ["Laptop"]


def test_t_svc_448_a_ceremony_belongs_to_the_user_who_began_it(
    factory: UowFactory, alice: TenantContext, webauthn: WebAuthnService
) -> None:
    """T-SVC-448: another user of the tenant cannot finish someone else's registration."""
    me = _user(factory, alice, "alice@victus.example.com")
    other = _user(factory, alice, "second@victus.example.com")
    _, attestation, ceremony = _register(factory, me, webauthn, "Phone")
    with pytest.raises(Forbidden, match="another user"):
        uc.FinishRegistration(factory, other, webauthn).execute(ceremony, attestation, "Mine")
    assert uc.ListPasskeys(factory, other).execute() == []


def test_t_svc_449_login_refuses_malformed_and_unknown_credentials(
    factory: UowFactory,
    alice: TenantContext,
    webauthn: WebAuthnService,
    session_factory: sessionmaker[Session],
) -> None:
    """T-SVC-449: a response without a credential id and a credential nobody registered
    are both refused as unauthenticated; logging out an unknown session is a no-op."""
    with session_factory() as s:
        lookup = SqlAuthLookup(s)
        with pytest.raises(Unauthenticated, match="credential id missing"):
            uc.FinishLogin(lookup, webauthn, 30).execute("c", {"rawId": 42}, None)
        stranger = SoftAuthenticator(RP_ID, ORIGIN)
        options = uc.BeginLogin(lookup, webauthn).execute(None)
        assertion = stranger.authenticate(options)
        with pytest.raises(Unauthenticated, match="unknown passkey"):
            uc.FinishLogin(lookup, webauthn, 30).execute("c", assertion, "ua")
        uc.Logout(lookup).execute("no-such-session")
        assert uc.ResolveSession(lookup).execute("no-such-session") is None


def test_t_svc_450_profile_and_passkey_management_refusals(
    factory: UowFactory, alice: TenantContext, webauthn: WebAuthnService
) -> None:
    """T-SVC-450: the profile needs a known tenant and a known user (tokens have none);
    passkey listing and deletion need a user session; an unknown passkey is NotFound and
    the last passkey cannot be deleted."""
    with pytest.raises(Unauthenticated, match="tenant not found"):
        uc.Me(factory, TenantContext(tenant_id="no-such-tenant", user_id="u")).execute()
    with pytest.raises(Unauthenticated, match="token contexts"):
        uc.Me(factory, alice).execute()
    ghost = TenantContext(tenant_id=alice.tenant_id, user_id="no-such-user")
    with pytest.raises(Unauthenticated, match="user not found"):
        uc.Me(factory, ghost).execute()
    with pytest.raises(Unauthenticated):
        uc.ListPasskeys(factory, alice).execute()
    with pytest.raises(Unauthenticated):
        uc.DeletePasskey(factory, alice).execute("p")

    me = _user(factory, alice, "alice@victus.example.com")
    profile = uc.Me(factory, me).execute()
    assert profile.csrf_token == "" and profile.passkeys == 0
    _, attestation, ceremony = _register(factory, me, webauthn, "Laptop")
    only = uc.FinishRegistration(factory, me, webauthn).execute(ceremony, attestation, None)
    with pytest.raises(NotFound):
        uc.DeletePasskey(factory, me).execute("no-such-passkey")
    with pytest.raises(ValidationFailed, match="last passkey"):
        uc.DeletePasskey(factory, me).execute(only.id)
    assert uc.Me(factory, me).execute().passkeys == 1


def test_t_svc_451_token_creation_edges(factory: UowFactory, alice: TenantContext) -> None:
    """T-SVC-451: a token needs at least one scope; a naive expiry is read as UTC; an
    unknown token cannot be revoked."""
    with pytest.raises(ValidationFailed, match="at least one scope"):
        uc.CreateToken(factory, alice).execute("empty", [], None)
    naive = (datetime.now() + timedelta(days=30)).replace(tzinfo=None, microsecond=0)
    created = uc.CreateToken(factory, alice).execute("naive", [SCOPE_READ], naive)
    assert created.expires_at is not None and created.expires_at.tzinfo is not None
    assert created.expires_at.replace(tzinfo=None) == naive
    with pytest.raises(NotFound, match="token not found"):
        uc.RevokeToken(factory, alice).execute("no-such-token")
    assert [t.revoked_at for t in uc.ListTokens(factory, alice).execute()] == [None]
