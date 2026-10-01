"""T-API-319…321: the tenant router — its read paths and today's user creation rule."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.api.conftest import Account, bearer
from tests.integration.api.cov_support import API, assert_problem
from victus.application.use_cases._base import UowFactory

pytestmark = pytest.mark.api


@pytest.mark.covers("GET /api/v1/tenant", "GET /api/v1/tenant/users")
def test_t_api_319_tenant_and_users(
    client: TestClient, alice_token: dict[str, str], alice_account: Account
) -> None:
    """T-API-319: the tenant and its users are read from the caller's own tenant."""
    t = client.get(f"{API}/tenant", headers=alice_token)
    assert t.status_code == 200, t.text
    assert t.json() == {"id": alice_account.tenant_id, "slug": "alice", "name": "Alice"}
    users = client.get(f"{API}/tenant/users", headers=alice_token).json()
    assert users == [
        {
            "id": alice_account.user_id,
            "display_name": "Alice",
            "email": "alice@example.com",
            "role": "owner",
        }
    ]
    assert_problem(client.get(f"{API}/tenant"), 401)


@pytest.mark.covers("GET /api/v1/tenant", "GET /api/v1/tenant/users")
def test_t_api_320_tenant_isolation(
    client: TestClient, bob_token: dict[str, str], alice_account: Account
) -> None:
    """T-API-320: Bob sees his tenant and his users only."""
    assert client.get(f"{API}/tenant", headers=bob_token).json()["slug"] == "bob"
    emails = [u["email"] for u in client.get(f"{API}/tenant/users", headers=bob_token).json()]
    assert emails == ["bob@example.com"]


@pytest.mark.covers("POST /api/v1/tenant/users")
def test_t_api_321_create_user_with_and_without_admin(
    client: TestClient, alice_token: dict[str, str], api_factory: UowFactory, alice_account: Account
) -> None:
    """T-API-321: a token without admin is refused; with admin the user and a code come back."""
    body = {"display_name": "Carol", "email": "carol@example.com"}
    no_admin = bearer(api_factory, alice_account, ["read", "write"])
    assert (
        "admin"
        in assert_problem(client.post(f"{API}/tenant/users", json=body, headers=no_admin), 403)[
            "detail"
        ]
    )
    r = client.post(f"{API}/tenant/users", json=body, headers=alice_token)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["user"]["email"] == "carol@example.com" and created["user"]["role"] == "member"
    assert created["recovery_code"]
    assert_problem(client.post(f"{API}/tenant/users", json=body, headers=alice_token), 409)
