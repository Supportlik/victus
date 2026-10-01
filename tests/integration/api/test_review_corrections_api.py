"""T-API-200…206: `meal_id` on a line item and `PATCH /proposals/{id}` over HTTP (R81, R84)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.integration.api.conftest import ORIGIN, RP_ID, Account, Session
from tests.integration.api.webauthn_device import SoftAuthenticator
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import auth as auth_uc
from victus.application.use_cases import products as products_uc
from victus.application.use_cases import proposals as prop_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.auth.sessions import CSRF_HEADER

DAY = "2026-03-14"
AGENT = ["read", "write", "capture:read", "capture:write", "agent:write"]


def _token(factory: UowFactory, account: Account, scopes: list[str]) -> tuple[dict[str, str], str]:
    """A bearer header and the token's id, which is who a proposal filed with it names."""
    created = auth_uc.CreateToken(factory, account.ctx).execute("test", scopes, None)
    return {"Authorization": f"Bearer {created.token}"}, created.id


def _as_token(account: Account, token_id: str, scopes: list[str]) -> TenantContext:
    return TenantContext(tenant_id=account.tenant_id, token_id=token_id, scopes=frozenset(scopes))


def _product(factory: UowFactory, account: Account) -> int:
    return (
        products_uc.CreateProduct(factory, account.ctx)
        .execute(products_uc.ProductInput(name="Skyr natural", kcal=63, protein=11, carbs=4))
        .id
    )


def _day(client: TestClient, headers: dict[str, str], date: str = DAY) -> tuple[int, int]:
    assert client.post(f"/api/v1/days/{date}", headers=headers, json={"reliable": True}).is_success
    meals = [
        client.post(f"/api/v1/days/{date}/meals", headers=headers, json={"name": name}).json()["id"]
        for name in ("Breakfast", "Lunch")
    ]
    return meals[0], meals[1]


def _item(client: TestClient, headers: dict[str, str], meal: int, product: int) -> dict[str, Any]:
    r = client.post(
        f"/api/v1/meals/{meal}/line-items",
        headers=headers,
        json={"consumable_id": product, "amount": 100, "unit_code": "g"},
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def _browser(app: FastAPI, account: Account) -> tuple[TestClient, dict[str, str]]:
    """A signed-in browser: a passkey registered through recovery, then a real sign-in."""
    recovery = Session(app, account)
    device = SoftAuthenticator(RP_ID, ORIGIN)
    options = recovery.post(
        "/api/v1/auth/webauthn/register/options", json={"name": "Phone"}, headers=recovery.csrf
    ).json()
    attestation = device.register(options)
    attestation.update(ceremony_id=options["ceremony_id"], name="Phone")
    assert recovery.post(
        "/api/v1/auth/webauthn/register/verify", json=attestation, headers=recovery.csrf
    ).is_success
    browser = TestClient(app)
    options = browser.post("/api/v1/auth/webauthn/login/options", json={}).json()
    assertion = device.authenticate(options)
    assertion["ceremony_id"] = options["ceremony_id"]
    me = browser.post("/api/v1/auth/webauthn/login/verify", json=assertion)
    assert me.status_code == 200, me.text
    return browser, {CSRF_HEADER: me.json()["csrf_token"]}


# ── line items ─────────────────────────────────────────────────────────────


def test_t_api_200_patch_moves_a_line_item_between_the_meals_of_its_day(
    client: TestClient, alice_token: dict[str, str], api_factory: UowFactory, alice_account: Account
) -> None:
    """T-API-200: 200 with the new meal; 422 for a meal of another day; 404 for none."""
    product = _product(api_factory, alice_account)
    breakfast, lunch = _day(client, alice_token)
    _, elsewhere = _day(client, alice_token, "2026-03-15")
    item = _item(client, alice_token, breakfast, product)

    moved = client.patch(
        f"/api/v1/line-items/{item['id']}", headers=alice_token, json={"meal_id": lunch}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["meal_id"] == lunch

    other = client.patch(
        f"/api/v1/line-items/{item['id']}", headers=alice_token, json={"meal_id": elsewhere}
    )
    assert other.status_code == 422
    assert other.json()["errors"] == [{"field": "meal_id", "message": "another day"}]
    missing = client.patch(
        f"/api/v1/line-items/{item['id']}", headers=alice_token, json={"meal_id": 99_999}
    )
    assert missing.status_code == 404
    day = client.get(f"/api/v1/days/{DAY}", headers=alice_token).json()
    assert [len(m["line_items"]) for m in day["meals"]] == [0, 1]


@pytest.mark.parametrize(
    ("scopes", "fact", "draft"),
    [
        (["read"], 403, 403),
        (["read", "write"], 403, 200),
        (AGENT, 403, 200),
        (["read", "write", "approve"], 200, 200),
    ],
)
def test_t_api_201_moving_an_item_by_scope_set(
    client: TestClient,
    alice_token: dict[str, str],
    api_factory: UowFactory,
    alice_account: Account,
    scopes: list[str],
    fact: int,
    draft: int,
) -> None:
    """T-API-201: a fact moves only with approve; a draft with write; read moves nothing."""
    product = _product(api_factory, alice_account)
    breakfast, lunch = _day(client, alice_token)
    approved = _item(client, alice_token, breakfast, product)
    agent_headers, _ = _token(api_factory, alice_account, AGENT)
    drafted = _item(client, agent_headers, breakfast, product)
    assert drafted["is_draft"] is True
    headers, _ = _token(api_factory, alice_account, scopes)
    for item, expected in ((approved, fact), (drafted, draft)):
        r = client.patch(
            f"/api/v1/line-items/{item['id']}", headers=headers, json={"meal_id": lunch}
        )
        assert r.status_code == expected, (scopes, item["is_draft"], r.text)


# ── PATCH /proposals/{id} ──────────────────────────────────────────────────


@pytest.mark.covers("PATCH /api/v1/proposals/{proposal_id}")
def test_t_api_202_a_session_amends_and_the_history_keeps_both(
    api_app: FastAPI, api_factory: UowFactory, alice_account: Account
) -> None:
    """T-API-202: the signed-in person amends, then approves; the answer carries both readings."""
    browser, csrf = _browser(api_app, alice_account)
    product = _product(api_factory, alice_account)
    _, token_id = _token(api_factory, alice_account, AGENT)
    filed = prop_uc.ProposeProductChange(
        api_factory, _as_token(alice_account, token_id, AGENT)
    ).execute(product, {"kcal": 70, "protein": 12})

    amended = browser.patch(
        f"/api/v1/proposals/{filed.id}",
        headers=csrf,
        json={"changes": {"kcal": 66, "protein": None}, "rationale": "label re-read"},
    )
    assert amended.status_code == 200, amended.text
    body = amended.json()
    assert body["status"] == "pending"
    assert body["changes"] == {"kcal": 66}
    assert body["proposed"] == {"kcal": 70, "protein": 12}
    assert body["rationale"] == "label re-read"
    assert browser.get(f"/api/v1/products/{product}").json()["kcal"] == 63  # nothing applied

    decided = browser.post(f"/api/v1/proposals/{filed.id}/approve", headers=csrf, json={})
    assert decided.status_code == 200
    assert decided.json()["proposed"] == {"kcal": 70, "protein": 12}
    assert decided.json()["changes"] == {"kcal": 66}
    history = browser.get("/api/v1/proposals", params={"status": "approved"}).json()
    assert [(p["changes"], p["proposed"]) for p in history] == [
        ({"kcal": 66}, {"kcal": 70, "protein": 12})
    ]
    assert browser.get(f"/api/v1/products/{product}").json()["kcal"] == 66


@pytest.mark.parametrize(
    ("scopes", "own", "other"),
    [
        (["read"], 403, 403),
        (["read", "write"], 403, 403),
        (["read", "approve"], 403, 403),
        (AGENT, 200, 403),
        (["read", "write", "approve"], 200, 200),
        (["admin"], 200, 200),
    ],
)
def test_t_api_203_amending_by_scope_set(
    client: TestClient,
    api_factory: UowFactory,
    alice_account: Account,
    scopes: list[str],
    own: int,
    other: int,
) -> None:
    """T-API-203: approve amends any pending proposal, agent:write only one it filed itself."""
    product = _product(api_factory, alice_account)
    headers, token_id = _token(api_factory, alice_account, scopes)
    mine = prop_uc.ProposeProductChange(
        api_factory, _as_token(alice_account, token_id, AGENT)
    ).execute(product, {"kcal": 70})
    theirs = prop_uc.ProposeProductChange(
        api_factory, _as_token(alice_account, "tok_someone_else", AGENT)
    ).execute(product, {"fat": 1})
    for proposal, expected in ((mine, own), (theirs, other)):
        r = client.patch(
            f"/api/v1/proposals/{proposal.id}", headers=headers, json={"changes": {"kcal": 66}}
        )
        assert r.status_code == expected, (scopes, r.text)


def test_t_api_204_only_a_pending_proposal_is_amended(
    client: TestClient, alice_token: dict[str, str], api_factory: UowFactory, alice_account: Account
) -> None:
    """T-API-204: 409 once decided, 404 when missing, 422 for an empty or unknown change."""
    product = _product(api_factory, alice_account)
    ctx = alice_account.ctx
    approved = prop_uc.ProposeProductChange(api_factory, ctx).execute(product, {"kcal": 70})
    rejected = prop_uc.ProposeProductChange(api_factory, ctx).execute(product, {"kcal": 71})
    pending = prop_uc.ProposeProductChange(api_factory, ctx).execute(product, {"kcal": 72})
    assert client.post(f"/api/v1/proposals/{approved.id}/approve", headers=alice_token).is_success
    assert client.post(f"/api/v1/proposals/{rejected.id}/reject", headers=alice_token).is_success

    def patch(proposal_id: str, body: object) -> int:
        return client.patch(
            f"/api/v1/proposals/{proposal_id}", headers=alice_token, json=body
        ).status_code

    assert patch(approved.id, {"changes": {"kcal": 66}}) == 409
    assert patch(rejected.id, {"changes": {"kcal": 66}}) == 409
    assert patch("does-not-exist", {"changes": {"kcal": 66}}) == 404
    assert patch(pending.id, {"changes": {}}) == 422
    assert patch(pending.id, {}) == 422
    assert patch(pending.id, {"changes": {"category_id": 1}}) == 422
    assert patch(pending.id, {"changes": {"kcal": -5}}) == 422
    assert patch(pending.id, {"changes": {"kcal": 66}}) == 200


def test_t_api_205_a_new_product_is_amended_and_found_by_its_one_off(
    client: TestClient, alice_token: dict[str, str], api_factory: UowFactory, alice_account: Account
) -> None:
    """T-API-205: `?consumable_id=` finds the proposal; its values and portions can be corrected."""
    _, token_id = _token(api_factory, alice_account, AGENT)
    filed = prop_uc.ProposeNewProduct(
        api_factory, _as_token(alice_account, token_id, AGENT)
    ).execute(
        products_uc.ProductInput(name="Oat bar", brand="Mill", kcal=400),
        portions=[{"unit_code": "piece", "label": "bar", "amount": 50}],
    )
    found = client.get(
        "/api/v1/proposals", headers=alice_token, params={"consumable_id": filed.consumable_id}
    ).json()
    assert [p["id"] for p in found] == [filed.id]
    assert found[0]["changes"]["portions"][0]["amount"] == 50

    r = client.patch(
        f"/api/v1/proposals/{filed.id}",
        headers=alice_token,
        json={
            "changes": {
                "name": "Oat bar crunchy",
                "brand": "Mill & Co",
                "reference_amount": 100,
                "reference_unit": "g",
                "kcal": 420,
                "portions": [{"op": "add", "unit_code": "piece", "label": "bar", "amount": 45}],
            }
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["product_name"] == "Oat bar crunchy"
    assert r.json()["changes"]["portions"][0]["amount"] == 45
    bad = client.patch(
        f"/api/v1/proposals/{filed.id}",
        headers=alice_token,
        json={"changes": {"portions": [{"op": "update", "portion_id": 1, "amount": 3}]}},
    )
    assert bad.status_code == 422


def test_t_api_206_a_version_moves_its_day(
    client: TestClient, alice_token: dict[str, str], api_factory: UowFactory, alice_account: Account
) -> None:
    """T-API-206: `valid_from` of a version proposal is amendable, and approving uses it."""
    product = _product(api_factory, alice_account)
    filed = prop_uc.version_or_propose_product_version(
        api_factory,
        _as_token(alice_account, "tok_agent", AGENT),
        product,
        date(2026, 3, 1),
        {"kcal": 68},
    )
    r = client.patch(
        f"/api/v1/proposals/{filed.id}",
        headers=alice_token,
        json={"changes": {"valid_from": "2026-03-09", "kcal": 67}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["changes"] == {"kcal": 67, "valid_from": "2026-03-09"}
    ok = client.post(f"/api/v1/proposals/{filed.id}/approve", headers=alice_token, json={})
    assert ok.status_code == 200, ok.text
    versions = client.get(f"/api/v1/products/{product}/versions", headers=alice_token).json()
    assert [(v["valid_from"], v["kcal"]) for v in versions][-1] == ("2026-03-09", 67)
