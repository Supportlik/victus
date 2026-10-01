"""T-API-314…318: tenant settings, their versions, agent rules and target bands."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.api.conftest import Account, bearer
from tests.integration.api.cov_support import API, assert_problem, put_settings, settings_doc
from victus.application.use_cases._base import UowFactory

pytestmark = pytest.mark.api

BAND = {
    "name": "Rest day spring",
    "training_type": "rest",
    "valid_from": "2026-04-01",
    "protein": {"min": 100, "opt_min": 140, "opt_max": 180, "target": 160, "max": 200},
    "carbs": {"min": 120, "opt_min": 150, "opt_max": 200, "target": 180, "max": 230},
    "fat": {"min": 45, "opt_min": 55, "opt_max": 70, "target": 58, "max": 75},
    "fiber": {"min": 25, "opt_min": 30, "opt_max": 38, "target": 35, "max": 50},
    "salt": {"min": 4, "opt_min": 6, "opt_max": 8, "target": 7, "max": 15},
}


@pytest.mark.covers("GET /api/v1/settings", "PUT /api/v1/settings", "GET /api/v1/settings/versions")
def test_t_api_314_settings_versions(client: TestClient, alice_token: dict[str, str]) -> None:
    """T-API-314: every PUT adds a version; GET answers the newest, versions lists them all."""
    assert client.get(f"{API}/settings/versions", headers=alice_token).json() == []
    assert_problem(client.get(f"{API}/settings", headers=alice_token), 404)
    first = put_settings(client, alice_token)
    doc = settings_doc()
    second = client.put(
        f"{API}/settings", json={"data": doc, "valid_from": "2026-05-01"}, headers=alice_token
    )
    assert second.status_code == 200, second.text
    assert second.json()["version"] == first["version"] + 1
    assert second.json()["valid_from"] == "2026-05-01"
    current = client.get(f"{API}/settings", headers=alice_token).json()
    assert current["version"] == second.json()["version"]
    versions = client.get(f"{API}/settings/versions", headers=alice_token).json()
    assert sorted(v["version"] for v in versions) == [1, 2]
    assert all(v["data"] for v in versions)
    assert_problem(client.put(f"{API}/settings", json={}, headers=alice_token), 422)


@pytest.mark.covers(
    "GET /api/v1/settings/rules",
    "PUT /api/v1/settings/rules",
    "DELETE /api/v1/settings/rules/{name}",
)
def test_t_api_315_rules_roundtrip(client: TestClient, alice_token: dict[str, str]) -> None:
    """T-API-315: a rule is added, replaced by name, listed and deleted; missing name is 404."""
    put_settings(client, alice_token)
    before = client.get(f"{API}/settings/rules", headers=alice_token).json()
    rule = {"name": "skyr-tub", "when": "skyr without amount", "then": "assume one tub"}
    r = client.put(f"{API}/settings/rules", json=rule, headers=alice_token)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "name": "skyr-tub",
        "when": "skyr without amount",
        "then": "assume one tub",
        "scope": "all",
        "enabled": True,
        "priority": 100,
    }
    replaced = client.put(
        f"{API}/settings/rules",
        json={**rule, "then": "assume 400 g", "scope": "days", "priority": 5},
        headers=alice_token,
    )
    assert replaced.json()["then"] == "assume 400 g" and replaced.json()["scope"] == "days"
    rules = client.get(f"{API}/settings/rules", headers=alice_token).json()
    assert len(rules) == len(before) + 1
    assert next(x for x in rules if x["name"] == "skyr-tub")["priority"] == 5

    assert client.delete(f"{API}/settings/rules/skyr-tub", headers=alice_token).status_code == 204
    assert client.get(f"{API}/settings/rules", headers=alice_token).json() == before
    assert_problem(client.delete(f"{API}/settings/rules/skyr-tub", headers=alice_token), 404)


@pytest.mark.covers("PUT /api/v1/settings/rules", "GET /api/v1/settings/rules")
def test_t_api_316_rule_refusals(
    client: TestClient, alice_token: dict[str, str], api_factory: UowFactory, alice_account: Account
) -> None:
    """T-API-316: no settings yet 404, bad body 422, bad name 422, read-only token 403."""
    rule = {"when": "a", "then": "b"}
    body = assert_problem(client.put(f"{API}/settings/rules", json=rule, headers=alice_token), 404)
    assert "settings" in body["detail"]
    put_settings(client, alice_token)
    assert_problem(
        client.put(f"{API}/settings/rules", json={"when": "", "then": "b"}, headers=alice_token),
        422,
    )
    assert_problem(
        client.put(f"{API}/settings/rules", json={**rule, "scope": "x"}, headers=alice_token), 422
    )
    assert_problem(
        client.put(f"{API}/settings/rules", json={**rule, "name": "!!!"}, headers=alice_token), 422
    )
    read_only = bearer(api_factory, alice_account, ["read"])
    assert client.get(f"{API}/settings/rules", headers=read_only).status_code == 200
    assert_problem(client.put(f"{API}/settings/rules", json=rule, headers=read_only), 403)


@pytest.mark.covers("GET /api/v1/target-bands", "POST /api/v1/target-bands")
def test_t_api_317_target_band_upsert(client: TestClient, alice_token: dict[str, str]) -> None:
    """T-API-317: POST adds a band valid from a day; posting it again replaces it."""
    before = client.get(f"{API}/target-bands", headers=alice_token).json()
    r = client.post(f"{API}/target-bands", json=BAND, headers=alice_token)
    assert r.status_code == 200, r.text
    band = r.json()
    assert band["name"] == "Rest day spring" and band["valid_from"] == "2026-04-01"
    assert band["protein"]["target"] == 160 and band["kcal"] is None
    again = client.post(
        f"{API}/target-bands",
        json={**BAND, "protein": {**BAND["protein"], "target": 165}},  # type: ignore[dict-item]
        headers=alice_token,
    )
    assert again.status_code == 200 and again.json()["protein"]["target"] == 165
    after = client.get(f"{API}/target-bands", headers=alice_token).json()
    assert len(after) == len(before) + 1
    missing = {k: v for k, v in BAND.items() if k != "salt"}
    assert (
        assert_problem(client.post(f"{API}/target-bands", json=missing, headers=alice_token), 422)[
            "errors"
        ][0]["field"]
        == "salt"
    )


@pytest.mark.covers(
    "GET /api/v1/settings", "GET /api/v1/target-bands", "GET /api/v1/settings/versions"
)
def test_t_api_318_settings_are_tenant_scoped(
    client: TestClient, alice_token: dict[str, str], bob_token: dict[str, str]
) -> None:
    """T-API-318: Alice's settings, versions and bands are invisible to Bob."""
    put_settings(client, alice_token)
    assert_problem(client.get(f"{API}/settings", headers=bob_token), 404)
    assert client.get(f"{API}/settings/versions", headers=bob_token).json() == []
    assert client.get(f"{API}/target-bands", headers=bob_token).json() == []
