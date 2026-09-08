"""T-API-001…010: passkeys, sessions, CSRF, recovery and tokens over HTTP."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.integration.api.conftest import ORIGIN, RP_ID, Account, Session, bearer
from tests.integration.api.webauthn_device import SoftAuthenticator
from victus.application.tenant_context import SCOPE_READ, SCOPE_WRITE
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.auth.sessions import CSRF_HEADER, SESSION_COOKIE

pytestmark = pytest.mark.api


def _register(session: Session, device: SoftAuthenticator, name: str = "Phone") -> dict:  # type: ignore[type-arg]
    options = session.post(
        "/api/v1/auth/webauthn/register/options", json={"name": name}, headers=session.csrf
    )
    assert options.status_code == 200, options.text
    body = options.json()
    attestation = device.register(body)
    attestation["ceremony_id"] = body["ceremony_id"]
    attestation["name"] = name
    r = session.post(
        "/api/v1/auth/webauthn/register/verify", json=attestation, headers=session.csrf
    )
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def _login(
    client: TestClient, device: SoftAuthenticator, email: str | None = None, **kw: int
) -> object:
    options = client.post(
        "/api/v1/auth/webauthn/login/options", json={"email": email} if email else {}
    )
    assert options.status_code == 200, options.text
    body = options.json()
    assertion = device.authenticate(body, **kw)
    assertion["ceremony_id"] = body["ceremony_id"]
    return client.post("/api/v1/auth/webauthn/login/verify", json=assertion)


def test_t_api_006_recovery_session_is_restricted(api_app: FastAPI, alice_account: Account) -> None:
    """T-API-006: a recovery session may only manage passkeys and read /auth/me."""
    session = Session(api_app, alice_account)
    assert session.me["recovery_session"] is True and session.me["passkeys"] == 0
    assert session.get("/api/v1/auth/me").status_code == 200
    r = session.get("/api/v1/products?q=skyr")
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")


def test_t_api_001_002_003_passkey_register_login_replay(
    api_app: FastAPI, alice_account: Account
) -> None:
    """T-API-001 registration, T-API-002 login sets a cookie,
    T-API-003 sign-count regression is rejected."""
    session = Session(api_app, alice_account)
    device = SoftAuthenticator(RP_ID, ORIGIN)
    passkey = _register(session, device)
    assert passkey["name"] == "Phone"
    assert session.get("/api/v1/auth/me").json()["passkeys"] == 1

    client = TestClient(api_app)
    r = _login(client, device, email=alice_account.email)
    assert r.status_code == 200, r.text  # type: ignore[attr-defined]
    me = r.json()  # type: ignore[attr-defined]
    assert me["user"]["email"] == alice_account.email and me["recovery_session"] is False
    cookie = r.headers.get("set-cookie", "")  # type: ignore[attr-defined]
    assert (
        SESSION_COOKIE in cookie
        and "HttpOnly" in cookie
        and "SameSite=lax" in cookie.lower().replace("samesite=lax", "SameSite=lax")
    )
    assert client.get("/api/v1/auth/me").status_code == 200
    # a fully authenticated session may use the API
    assert (
        client.get("/api/v1/products?q=", headers={CSRF_HEADER: me["csrf_token"]}).status_code
        == 200
    )

    # discoverable login without e-mail works too
    fresh = TestClient(api_app)
    assert _login(fresh, device).status_code == 200  # type: ignore[attr-defined]

    # replay with a stale sign count
    stale = TestClient(api_app)
    r = _login(stale, device, sign_count=1)
    assert r.status_code == 401  # type: ignore[attr-defined]

    # logout clears the session
    assert (
        client.post("/api/v1/auth/logout", headers={CSRF_HEADER: me["csrf_token"]}).status_code
        == 204
    )
    assert client.get("/api/v1/auth/me").status_code == 401


def test_t_api_004_csrf_required_for_cookie_writes(
    api_app: FastAPI, alice_account: Account
) -> None:
    """T-API-004: cookie-authenticated writes without the CSRF header are refused."""
    session = Session(api_app, alice_account)
    device = SoftAuthenticator(RP_ID, ORIGIN)
    _register(session, device)
    client = TestClient(api_app)
    me = _login(client, device, email=alice_account.email).json()  # type: ignore[attr-defined]
    r = client.post("/api/v1/days/2026-03-10", json={"reliable": True})
    assert r.status_code == 403
    r = client.post(
        "/api/v1/days/2026-03-10", json={"reliable": True}, headers={CSRF_HEADER: me["csrf_token"]}
    )
    assert r.status_code == 201


def test_second_passkey_and_delete_last_refused(api_app: FastAPI, alice_account: Account) -> None:
    session = Session(api_app, alice_account)
    first = _register(session, SoftAuthenticator(RP_ID, ORIGIN), "Phone")
    second = _register(session, SoftAuthenticator(RP_ID, ORIGIN), "Laptop")
    assert len(session.get("/api/v1/auth/passkeys").json()) == 2
    assert (
        session.delete(f"/api/v1/auth/passkeys/{second['id']}", headers=session.csrf).status_code
        == 204
    )
    r = session.delete(f"/api/v1/auth/passkeys/{first['id']}", headers=session.csrf)
    assert r.status_code == 422


def test_t_api_007_010_tokens_over_http(
    api_app: FastAPI, alice_account: Account, api_factory: UowFactory
) -> None:
    """T-API-007 single display, T-API-008 scopes, T-API-010 revocation."""
    admin = bearer(api_factory, alice_account, ["admin"])
    client = TestClient(api_app)
    r = client.post(
        "/api/v1/auth/tokens",
        json={"name": "ci", "scopes": [SCOPE_READ], "expires_at": None},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["token"].startswith("vct_")
    listed = client.get("/api/v1/auth/tokens", headers=admin).json()
    assert all("token" not in t for t in listed) and any(
        t["prefix"] == created["prefix"] for t in listed
    )

    read_only = {"Authorization": f"Bearer {created['token']}"}
    assert client.get("/api/v1/products?q=", headers=read_only).status_code == 200
    r = client.post("/api/v1/products", json={"name": "Oat milk"}, headers=read_only)
    assert r.status_code == 403
    assert r.json()["detail"].startswith("scope 'write'")

    assert client.delete(f"/api/v1/auth/tokens/{created['id']}", headers=admin).status_code == 204
    assert client.get("/api/v1/products?q=", headers=read_only).status_code == 401  # T-API-010


def test_t_api_009_expired_token(
    api_app: FastAPI, alice_account: Account, api_factory: UowFactory
) -> None:
    from datetime import UTC, datetime, timedelta

    from victus.application.use_cases import auth as auth_uc

    created = auth_uc.CreateToken(api_factory, alice_account.ctx).execute(
        "old", [SCOPE_READ, SCOPE_WRITE], None
    )
    with api_factory(alice_account.ctx) as u:
        row = next(t for t in u.users.tokens() if t.id == created.id)
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        u.commit()
    r = TestClient(api_app).get(
        "/api/v1/products?q=", headers={"Authorization": f"Bearer {created.token}"}
    )
    assert r.status_code == 401
