"""T-API-104…109: who may manage tokens and users, what a session holds, and REST
catalogue writes without ``approve``.

Every principal kind is exercised: an owner's session, a member's session, a token with
``admin`` and tokens without it. A session is created the way a passkey login creates one
(the passkey ceremony itself is T-API-001/002).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.integration.api.conftest import Account, bearer
from victus.application.tenant_context import (
    ALL_SCOPES,
    SCOPE_ADMIN,
    SCOPE_AGENT_WRITE,
    SCOPE_APPROVE,
    SCOPE_CAPTURE_READ,
    SCOPE_READ,
    SCOPE_WRITE,
    TenantContext,
)
from victus.application.use_cases import tenants as tenants_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.auth import sessions
from victus.infrastructure.db import orm

pytestmark = pytest.mark.api

API = "/api/v1"


def _session(app: FastAPI, account: Account) -> TestClient:
    """A signed-in browser: a full (not recovery) session cookie plus its CSRF header."""
    with app.state.session_factory() as s:
        row = orm.Session(
            user_id=account.user_id,
            tenant_id=account.tenant_id,
            expires_at=sessions.session_expiry(30),
            user_agent="test",
        )
        s.add(row)
        s.commit()
        session_id = row.id
    client = TestClient(app)
    client.cookies.set(sessions.SESSION_COOKIE, session_id)
    client.headers[sessions.CSRF_HEADER] = sessions.csrf_token_for(session_id)
    return client


@pytest.fixture
def make_member(api_factory: UowFactory) -> Callable[[Account, str], Account]:
    def make(owner: Account, name: str) -> Account:
        system = TenantContext(tenant_id=owner.tenant_id, scopes=ALL_SCOPES)
        created = tenants_uc.CreateUser(api_factory, system).execute(
            name.title(), f"{name}@example.com", "member"
        )
        return Account(
            name,
            owner.tenant_id,
            created.user.id,
            created.user.email or "",
            created.recovery_code,
            TenantContext(tenant_id=owner.tenant_id, user_id=created.user.id),
        )

    return make


def _mint(client: TestClient, scopes: list[str], name: str = "t") -> dict[str, str]:
    r = client.post(f"{API}/auth/tokens", json={"name": name, "scopes": scopes})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "id": r.json()["id"]}


def test_t_api_109_session_scopes_follow_the_role(
    api_app: FastAPI, alice_account: Account, make_member: Callable[[Account, str], Account]
) -> None:
    """T-API-109: an owner's session administers; a member's holds every scope but admin."""
    owner = _session(api_app, alice_account)
    member = _session(api_app, make_member(alice_account, "carol"))
    assert owner.get(f"{API}/tenant").status_code == 200
    assert member.get(f"{API}/tenant").status_code == 403
    # a member still does everything else a person does in the app, decisions included
    assert member.get(f"{API}/products").status_code == 200
    product = member.post(f"{API}/products", json={"name": "Skyr", "kcal": 63})
    assert product.status_code == 201, product.text
    assert member.post(f"{API}/days/2026-03-10", json={"reliable": True}).status_code == 201
    assert member.post(f"{API}/days/2026-03-10/close").status_code == 200


def test_t_api_106_tenant_reads_need_admin(
    api_app: FastAPI,
    alice_account: Account,
    api_factory: UowFactory,
    make_member: Callable[[Account, str], Account],
) -> None:
    """T-API-106: `/tenant` and `/tenant/users` answer an owner or `admin`, and nobody else."""
    owner = _session(api_app, alice_account)
    member = _session(api_app, make_member(alice_account, "carol"))
    client = TestClient(api_app)
    admin = bearer(api_factory, alice_account, [SCOPE_ADMIN])
    capture_only = bearer(api_factory, alice_account, [SCOPE_CAPTURE_READ])
    everything_else = bearer(api_factory, alice_account, sorted(ALL_SCOPES - {SCOPE_ADMIN}))
    for path in ("/tenant", "/tenant/users"):
        assert owner.get(API + path).status_code == 200, path
        assert client.get(API + path, headers=admin).status_code == 200, path
        assert member.get(API + path).status_code == 403, path
        assert client.get(API + path, headers=capture_only).status_code == 403, path
        assert client.get(API + path, headers=everything_else).status_code == 403, path
    users = owner.get(f"{API}/tenant/users").json()
    assert {u["role"] for u in users} == {"owner", "member"}


def test_t_api_107_creating_users_needs_admin_on_both_paths(
    api_app: FastAPI,
    alice_account: Account,
    api_factory: UowFactory,
    make_member: Callable[[Account, str], Account],
) -> None:
    """T-API-107: a member's session cannot create users (owners least of all); `admin` can."""
    owner = _session(api_app, alice_account)
    member = _session(api_app, make_member(alice_account, "carol"))
    client = TestClient(api_app)
    escalate = {"display_name": "Mallory", "email": "mallory@example.com", "role": "owner"}
    refused = member.post(f"{API}/tenant/users", json=escalate)
    assert refused.status_code == 403 and "admin" in refused.json()["detail"]
    write_token = bearer(api_factory, alice_account, sorted(ALL_SCOPES - {SCOPE_ADMIN}))
    assert client.post(f"{API}/tenant/users", json=escalate, headers=write_token).status_code == 403
    assert all(u["email"] != "mallory@example.com" for u in owner.get(f"{API}/tenant/users").json())

    made = owner.post(
        f"{API}/tenant/users", json={"display_name": "Dave", "email": "dave@example.com"}
    )
    assert made.status_code == 201 and made.json()["recovery_code"]
    admin = bearer(api_factory, alice_account, [SCOPE_ADMIN])
    by_token = client.post(
        f"{API}/tenant/users",
        json={"display_name": "Erin", "email": "erin@example.com"},
        headers=admin,
    )
    assert by_token.status_code == 201, by_token.text


def test_t_api_108_minting_tokens_is_capped_by_role_and_scope(
    api_app: FastAPI,
    alice_account: Account,
    api_factory: UowFactory,
    make_member: Callable[[Account, str], Account],
) -> None:
    """T-API-108: nobody grants a scope they do not hold, and a token never outgrows its owner."""
    carol = make_member(alice_account, "carol")
    owner = _session(api_app, alice_account)
    member = _session(api_app, carol)
    client = TestClient(api_app)

    denied = member.post(f"{API}/auth/tokens", json={"name": "x", "scopes": [SCOPE_ADMIN]})
    assert denied.status_code == 403 and "admin" in denied.json()["detail"]
    own = _mint(member, [SCOPE_READ, SCOPE_WRITE])
    assert (
        client.get(f"{API}/products", headers={"Authorization": own["Authorization"]}).status_code
        == 200
    )
    assert _mint(owner, [SCOPE_ADMIN])  # an owner may

    # a token without admin mints nothing, whatever else it holds
    plain = bearer(api_factory, alice_account, sorted(ALL_SCOPES - {SCOPE_ADMIN}))
    r = client.post(f"{API}/auth/tokens", json={"name": "y", "scopes": [SCOPE_READ]}, headers=plain)
    assert r.status_code == 403

    # an admin token minted for a member before the role cap existed loses admin on use
    legacy = bearer(api_factory, carol, [SCOPE_READ, SCOPE_ADMIN])
    assert client.get(f"{API}/tenant", headers=legacy).status_code == 403
    assert client.get(f"{API}/products", headers=legacy).status_code == 200


def test_t_api_105_token_list_and_revoke_are_limited(
    api_app: FastAPI,
    alice_account: Account,
    api_factory: UowFactory,
    make_member: Callable[[Account, str], Account],
) -> None:
    """T-API-105: a member sees and revokes only their own tokens; a low token none at all."""
    carol = make_member(alice_account, "carol")
    owner = _session(api_app, alice_account)
    member = _session(api_app, carol)
    client = TestClient(api_app)
    owners_token = _mint(owner, [SCOPE_READ], "owner-script")
    carols_token = _mint(member, [SCOPE_READ], "carol-script")

    # a phone shortcut's capture token can neither list nor revoke anything
    shortcut = bearer(api_factory, alice_account, [SCOPE_CAPTURE_READ])
    assert client.get(f"{API}/auth/tokens", headers=shortcut).status_code == 403
    r = client.delete(f"{API}/auth/tokens/{owners_token['id']}", headers=shortcut)
    assert r.status_code == 403

    listed = {t["id"] for t in member.get(f"{API}/auth/tokens").json()}
    assert carols_token["id"] in listed and owners_token["id"] not in listed
    assert member.delete(f"{API}/auth/tokens/{owners_token['id']}").status_code == 404
    still = client.get(f"{API}/products", headers={"Authorization": owners_token["Authorization"]})
    assert still.status_code == 200

    every = {t["id"] for t in owner.get(f"{API}/auth/tokens").json()}
    assert {carols_token["id"], owners_token["id"]} <= every
    admin = bearer(api_factory, alice_account, [SCOPE_ADMIN])
    assert {t["id"] for t in client.get(f"{API}/auth/tokens", headers=admin).json()} >= every
    assert member.delete(f"{API}/auth/tokens/{carols_token['id']}").status_code == 204
    assert owner.delete(f"{API}/auth/tokens/{owners_token['id']}").status_code == 204
    gone = client.get(f"{API}/products", headers={"Authorization": owners_token["Authorization"]})
    assert gone.status_code == 401


def test_t_api_104_catalogue_writes_without_approve_become_proposals(
    api_app: FastAPI, alice_account: Account, api_factory: UowFactory
) -> None:
    """T-API-104: REST product, version and portion writes behave like the MCP tools."""
    client = TestClient(api_app)
    full = bearer(api_factory, alice_account, [SCOPE_READ, SCOPE_WRITE, SCOPE_APPROVE])
    product = client.post(f"{API}/products", json={"name": "Skyr", "kcal": 63}, headers=full)
    assert product.status_code == 201
    pid = product.json()["id"]
    portion = client.post(
        f"{API}/products/{pid}/portions",
        json={"unit_code": "tub", "label": "tub", "amount": 400},
        headers=full,
    )
    assert portion.status_code == 201
    portion_id = portion.json()["id"]

    for scopes in ([SCOPE_READ, SCOPE_WRITE], [SCOPE_READ, SCOPE_AGENT_WRITE]):
        h = bearer(api_factory, alice_account, scopes)
        new = client.post(f"{API}/products", json={"name": "Oat milk", "kcal": 45}, headers=h)
        assert new.status_code == 202 and new.json()["kind"] == "new", new.text
        assert new.json()["status"] == "pending" and new.json()["consumable_id"]
        patch = client.patch(f"{API}/products/{pid}", json={"kcal": 64}, headers=h)
        assert patch.status_code == 202 and patch.json()["changes"]["kcal"] == 64
        version = client.post(
            f"{API}/products/{pid}/versions",
            json={"valid_from": "2026-06-01", "changes": {"kcal": 70}},
            headers=h,
        )
        assert version.status_code == 202 and version.json()["kind"] == "version"
        add = client.post(
            f"{API}/products/{pid}/portions",
            json={"unit_code": "slice", "label": "slice", "amount": 30},
            headers=h,
        )
        assert add.status_code == 202 and add.json()["changes"]["portions"][0]["op"] == "add"
        upd = client.patch(f"{API}/portions/{portion_id}", json={"amount": 380}, headers=h)
        assert upd.status_code == 202 and upd.json()["changes"]["portions"][0]["op"] == "update"
        rm = client.delete(f"{API}/portions/{portion_id}", headers=h)
        assert rm.status_code == 202 and rm.json()["changes"]["portions"][0]["op"] == "delete"

    # nothing became a fact: the product kept its values and its portion
    same = client.get(f"{API}/products/{pid}", headers=full).json()
    assert same["kcal"] == 63 and [p["amount"] for p in same["portions"]] == [400]
    pending = client.get(f"{API}/proposals", headers=full).json()
    assert len(pending) == 12

    # with approve, the same requests are applied
    assert (
        client.patch(f"{API}/portions/{portion_id}", json={"amount": 390}, headers=full).status_code
        == 200
    )
    assert client.delete(f"{API}/portions/{portion_id}", headers=full).status_code == 204
    assert (
        client.patch(f"{API}/products/{pid}", json={"kcal": 65}, headers=full).json()["kcal"] == 65
    )
    v = client.post(
        f"{API}/products/{pid}/versions",
        json={"valid_from": "2026-07-01", "changes": {"kcal": 71}},
        headers=full,
    )
    assert v.status_code == 201 and v.json()["kcal"] == 71

    # deciding stays write + approve
    h = bearer(api_factory, alice_account, [SCOPE_READ, SCOPE_WRITE])
    r = client.post(f"{API}/proposals/{pending[0]['id']}/approve", json={}, headers=h)
    assert r.status_code == 403 and "approve" in r.json()["detail"]


def test_t_api_111_upload_only_token_hears_a_failed_transcription(
    api_app: FastAPI, alice_account: Account, api_factory: UowFactory
) -> None:
    """T-API-111: `capture:write` alone uploads audio and learns it failed, without reading."""
    from victus.infrastructure.transcription.fake import FakeTranscription

    api_app.state.transcription = FakeTranscription(fail=True)
    shortcut = bearer(api_factory, alice_account, ["capture:write"])
    client = TestClient(api_app)
    r = client.post(
        f"{API}/captures",
        files={"file": ("note.oga", b"OggS-fake", "application/octet-stream")},
        headers=shortcut,
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "failed" and r.json()["transcript"] is None
    assert client.get(f"{API}/captures/{r.json()['id']}", headers=shortcut).status_code == 403
    reader = bearer(api_factory, alice_account, [SCOPE_CAPTURE_READ])
    stored = client.get(f"{API}/captures/{r.json()['id']}", headers=reader).json()
    assert stored["status"] == "failed"
