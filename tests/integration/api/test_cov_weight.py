"""T-API-310…313: manual weight entries and body measurements over HTTP."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.api.conftest import Account, bearer
from tests.integration.api.cov_support import API, assert_problem
from victus.application.use_cases._base import UowFactory

pytestmark = pytest.mark.api


@pytest.mark.covers("GET /api/v1/weight", "POST /api/v1/weight", "DELETE /api/v1/weight/{entry_id}")
def test_t_api_310_weight_add_list_delete(client: TestClient, alice_token: dict[str, str]) -> None:
    """T-API-310: entries are listed by range, a duplicate is 409, delete removes one."""
    for ts, kg in (("2026-03-01T07:00:00Z", 80.4), ("2026-03-05T07:00:00Z", 80.0)):
        r = client.post(f"{API}/weight", json={"measured_at": ts, "kg": kg}, headers=alice_token)
        assert r.status_code == 201, r.text
        assert r.json()["kg"] == kg and r.json()["source"] == "manual"
    first_id = client.get(f"{API}/weight", headers=alice_token).json()[0]["id"]

    everything = client.get(f"{API}/weight", headers=alice_token).json()
    assert [e["kg"] for e in everything] == [80.4, 80.0]
    ranged = client.get(
        f"{API}/weight", params={"from": "2026-03-03", "to": "2026-03-31"}, headers=alice_token
    ).json()
    assert [e["kg"] for e in ranged] == [80.0]

    dup = client.post(
        f"{API}/weight", json={"measured_at": "2026-03-01T07:00:00Z", "kg": 81}, headers=alice_token
    )
    assert_problem(dup, 409)
    assert_problem(
        client.post(
            f"{API}/weight",
            json={"measured_at": "2026-03-02T07:00:00Z", "kg": 0},
            headers=alice_token,
        ),
        422,
    )
    implausible = client.post(
        f"{API}/weight",
        json={"measured_at": "2026-03-02T07:00:00Z", "kg": 5000},
        headers=alice_token,
    )
    assert "plausible" in assert_problem(implausible, 422)["detail"]

    assert client.delete(f"{API}/weight/{first_id}", headers=alice_token).status_code == 204
    assert [e["kg"] for e in client.get(f"{API}/weight", headers=alice_token).json()] == [80.0]
    assert_problem(client.delete(f"{API}/weight/{first_id}", headers=alice_token), 404)


@pytest.mark.covers("GET /api/v1/weight", "POST /api/v1/weight", "DELETE /api/v1/weight/{entry_id}")
def test_t_api_311_weight_isolation_and_scope(
    client: TestClient,
    alice_token: dict[str, str],
    bob_token: dict[str, str],
    api_factory: UowFactory,
    alice_account: Account,
) -> None:
    """T-API-311: Bob sees none of Alice's entries and cannot delete one; read-only cannot add."""
    entry = client.post(
        f"{API}/weight", json={"measured_at": "2026-03-01T07:00:00Z", "kg": 80}, headers=alice_token
    ).json()
    assert client.get(f"{API}/weight", headers=bob_token).json() == []
    assert_problem(client.delete(f"{API}/weight/{entry['id']}", headers=bob_token), 404)
    read_only = bearer(api_factory, alice_account, ["read"])
    assert_problem(
        client.post(
            f"{API}/weight",
            json={"measured_at": "2026-03-02T07:00:00Z", "kg": 80},
            headers=read_only,
        ),
        403,
    )


@pytest.mark.covers(
    "GET /api/v1/body-measurements",
    "POST /api/v1/body-measurements",
    "DELETE /api/v1/body-measurements/{row_id}",
)
def test_t_api_312_body_measurements(client: TestClient, alice_token: dict[str, str]) -> None:
    """T-API-312: sessions are added, listed oldest first with limit/range, and deleted."""
    for ts, waist in (("2026-03-01T07:00:00Z", 90.0), ("2026-03-08T07:00:00Z", 89.0)):
        r = client.post(
            f"{API}/body-measurements",
            json={"measured_at": ts, "waist_cm": waist, "note": "morning"},
            headers=alice_token,
        )
        assert r.status_code == 201, r.text
        assert r.json()["waist_cm"] == waist and r.json()["hip_cm"] is None
    listed = client.get(f"{API}/body-measurements", headers=alice_token).json()
    assert [m["waist_cm"] for m in listed] == [90.0, 89.0]
    ranged = client.get(
        f"{API}/body-measurements",
        params={"from": "2026-03-05", "to": "2026-03-31"},
        headers=alice_token,
    ).json()
    assert [m["waist_cm"] for m in ranged] == [89.0]
    limited = client.get(f"{API}/body-measurements", params={"limit": 1}, headers=alice_token)
    assert len(limited.json()) == 1
    assert_problem(
        client.get(f"{API}/body-measurements", params={"limit": 0}, headers=alice_token), 422
    )

    empty = client.post(
        f"{API}/body-measurements",
        json={"measured_at": "2026-03-02T07:00:00Z"},
        headers=alice_token,
    )
    assert "at least one" in assert_problem(empty, 422)["detail"]
    out_of_range = client.post(
        f"{API}/body-measurements",
        json={"measured_at": "2026-03-02T07:00:00Z", "waist_cm": 300},
        headers=alice_token,
    )
    assert out_of_range.json()["errors"][0]["field"] == "waist_cm"
    dup = client.post(
        f"{API}/body-measurements",
        json={"measured_at": "2026-03-01T07:00:00Z", "hip_cm": 100},
        headers=alice_token,
    )
    assert_problem(dup, 409)

    row_id = listed[0]["id"]
    assert (
        client.delete(f"{API}/body-measurements/{row_id}", headers=alice_token).status_code == 204
    )
    assert_problem(client.delete(f"{API}/body-measurements/{row_id}", headers=alice_token), 404)


@pytest.mark.covers("GET /api/v1/body-measurements", "DELETE /api/v1/body-measurements/{row_id}")
def test_t_api_313_body_measurements_isolation(
    client: TestClient, alice_token: dict[str, str], bob_token: dict[str, str]
) -> None:
    """T-API-313: Bob neither lists nor deletes Alice's measurement."""
    row = client.post(
        f"{API}/body-measurements",
        json={"measured_at": "2026-03-01T07:00:00Z", "waist_cm": 90},
        headers=alice_token,
    ).json()
    assert client.get(f"{API}/body-measurements", headers=bob_token).json() == []
    assert_problem(client.delete(f"{API}/body-measurements/{row['id']}", headers=bob_token), 404)
