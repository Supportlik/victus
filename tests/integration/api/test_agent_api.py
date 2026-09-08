"""Agent runs and locks over HTTP (SPEC R50: on-demand runs are queued, not executed)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from tests.integration.api.conftest import Account, bearer
from victus.application.use_cases import agent as agent_uc
from victus.application.use_cases._base import UowFactory

pytestmark = pytest.mark.api

DAY = "2026-03-10"


def _capture(client: TestClient, headers: dict[str, str], text: str, day: str) -> str:
    r = client.post("/api/v1/captures", data={"text": text, "target_date": day}, headers=headers)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def test_queue_get_list_cancel(client: TestClient, alice_token: dict[str, str]) -> None:
    cid = _capture(client, alice_token, "skyr", DAY)
    r = client.post("/api/v1/agent/runs", json={}, headers=alice_token)
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "queued" and run["mode"] == "historical" and run["runner"] == "worker"
    assert run["days"] == [] and run["sessions"] == [] and run["cost_usd"] == 0.0
    ranged = client.post(
        "/api/v1/agent/runs",
        json={"mode": "manual", "captures": [cid], "from": DAY, "to": "2026-03-12"},
        headers=alice_token,
    )
    assert ranged.status_code == 202
    assert ranged.json()["days"] == [DAY, "2026-03-11", "2026-03-12"]
    assert ranged.json()["captures"] == [cid]
    got = client.get(f"/api/v1/agent/runs/{run['id']}", headers=alice_token)
    assert got.status_code == 200 and got.json()["id"] == run["id"]
    listed = client.get("/api/v1/agent/runs", headers=alice_token).json()
    assert [x["id"] for x in listed] == [ranged.json()["id"], run["id"]]  # newest first
    queued = client.get("/api/v1/agent/runs?status=queued", headers=alice_token).json()
    assert len(queued) == 2
    cancelled = client.post(f"/api/v1/agent/runs/{run['id']}/cancel", headers=alice_token)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    again = client.post(f"/api/v1/agent/runs/{run['id']}/cancel", headers=alice_token)
    assert again.status_code == 409
    bad = client.post("/api/v1/agent/runs", json={"mode": "magic"}, headers=alice_token)
    assert bad.status_code == 422
    reversed_range = client.post(
        "/api/v1/agent/runs", json={"from": "2026-03-12", "to": DAY}, headers=alice_token
    )
    assert reversed_range.status_code == 422
    unknown = client.post(
        "/api/v1/agent/runs", json={"captures": ["cap_missing"]}, headers=alice_token
    )
    assert unknown.status_code == 404


def test_locks_are_listed_and_force_released(
    client: TestClient,
    alice_token: dict[str, str],
    bob_token: dict[str, str],
    api_factory: UowFactory,
    alice_account: Account,
) -> None:
    _capture(client, alice_token, "skyr", DAY)
    # the worker (or an external runner) begins a run through the use case
    started = agent_uc.BeginAgentRun(api_factory, alice_account.ctx).execute(
        runner="external", mode="manual", dates=[date(2026, 3, 10)]
    )
    assert started.locked_days == [date(2026, 3, 10)]
    locks = client.get("/api/v1/agent/locks", headers=alice_token).json()
    assert len(locks) == 1 and locks[0]["date"] == DAY and locks[0]["runner"] == "external"
    assert locks[0]["run_id"] == started.run.id and "locked_until" in locks[0]
    # bob sees nothing of alice's runs and locks
    assert client.get("/api/v1/agent/locks", headers=bob_token).json() == []
    assert client.get(f"/api/v1/agent/runs/{started.run.id}", headers=bob_token).status_code == 404
    assert (
        client.post(f"/api/v1/agent/runs/{started.run.id}/cancel", headers=bob_token).status_code
        == 404
    )
    assert client.get("/api/v1/agent/runs", headers=bob_token).json() == []
    running = client.get(f"/api/v1/agent/runs/{started.run.id}", headers=alice_token).json()
    assert running["status"] == "running" and running["days"] == [DAY]
    # force unlock (operator), then a plain user with only read scope may not
    released = client.delete(f"/api/v1/agent/locks/{DAY}", headers=alice_token)
    assert released.status_code == 200 and released.json() == {"date": DAY, "released": True}
    assert client.get("/api/v1/agent/locks", headers=alice_token).json() == []
    read_only = bearer(api_factory, alice_account, ["read"])
    assert client.delete(f"/api/v1/agent/locks/{DAY}", headers=read_only).status_code == 403
    assert client.post("/api/v1/agent/runs", json={}, headers=read_only).status_code == 403
    assert client.get("/api/v1/agent/runs", headers=read_only).status_code == 200
    assert client.get("/api/v1/agent/runs", headers={}).status_code == 401
