"""T-API-026/027/073: the proposal endpoints, portion operations and tenant isolation."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.integration.api.conftest import Account
from victus.application.use_cases import products as products_uc
from victus.application.use_cases import proposals as prop_uc
from victus.application.use_cases._base import UowFactory


def _product(client: TestClient, headers: dict[str, str]) -> int:
    r = client.post(
        "/api/v1/products",
        headers=headers,
        json={"name": "Lime chips", "kcal": 535, "protein": 6, "carbs": 53, "fat": 33, "fiber": 4},
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_proposal_flow(
    client: TestClient,
    alice_token: dict[str, str],
    api_factory: UowFactory,
    alice_account: Account,
) -> None:
    pid = _product(client, alice_token)
    up = client.post(
        "/api/v1/captures",
        headers=alice_token,
        data={"text": "label says 520 kcal", "product_id": str(pid)},
    )
    assert up.status_code == 201, up.text
    capture_id = up.json()["id"]
    assert up.json()["product_id"] == pid

    # the proposal itself is the agent's job; here it stands in for a run
    prop_uc.ProposeProductChange(api_factory, alice_account.ctx).execute(
        pid, {"kcal": 520}, source="label photo", capture_id=capture_id
    )

    listed = client.get("/api/v1/proposals", headers=alice_token)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["changes"] == {"kcal": 520} and rows[0]["current"]["kcal"] == 535
    proposal_id = rows[0]["id"]

    ok = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=alice_token, json={})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    product = client.get(f"/api/v1/products/{pid}", headers=alice_token).json()
    assert product["kcal"] == 520 and product["verified"] is True
    capture = client.get(f"/api/v1/captures/{capture_id}", headers=alice_token).json()
    assert capture["status"] == "processed"
    again = client.post(f"/api/v1/proposals/{proposal_id}/reject", headers=alice_token)
    assert again.status_code == 409


def test_proposals_are_tenant_scoped(
    client: TestClient, alice_token: dict[str, str], bob_token: dict[str, str]
) -> None:
    assert client.get("/api/v1/proposals", headers=bob_token).json() == []
    assert client.get("/api/v1/proposals/does-not-exist", headers=alice_token).status_code == 404


def test_t_api_073_a_portion_operation_is_listed_with_its_plan(
    client: TestClient,
    alice_token: dict[str, str],
    api_factory: UowFactory,
    alice_account: Account,
) -> None:
    """T-API-073: the review list carries the row a portion entry would change."""
    pid = _product(client, alice_token)
    portion = products_uc.AddPortion(api_factory, alice_account.ctx).execute(
        pid, products_uc.PortionInput(unit_code="tub", label="tub", amount=400)
    )
    prop_uc.ProposeProductChange(api_factory, alice_account.ctx).execute(
        pid, {"portions": [{"op": "update", "portion_id": portion.id, "amount": 450}]}
    )

    listed = client.get("/api/v1/proposals", headers=alice_token)
    assert listed.status_code == 200, listed.text
    plan = listed.json()[0]["portion_plan"]
    assert [(p["op"], p["current"]["amount"], p["blocked"]) for p in plan] == [
        ("update", 400, None)
    ]

    proposal_id = listed.json()[0]["id"]
    ok = client.post(f"/api/v1/proposals/{proposal_id}/approve", headers=alice_token, json={})
    assert ok.status_code == 200 and ok.json()["portion_plan"] == []  # decided, so nothing pending
    product = client.get(f"/api/v1/products/{pid}", headers=alice_token).json()
    assert [(p["unit_code"], p["amount"]) for p in product["portions"]] == [("tub", 450)]
