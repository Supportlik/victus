"""T-API-300…309: the reports router — definitions, rendering, periods and snapshots."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.api.conftest import Account, bearer
from tests.integration.api.cov_support import API, assert_problem
from victus.api.routers import reports as reports_router
from victus.application.use_cases._base import UowFactory
from victus.reports.definition import PeriodSpec

pytestmark = pytest.mark.api


@pytest.mark.covers("GET /api/v1/reports")
def test_t_api_300_list_reports(
    client: TestClient, api_factory: UowFactory, alice_account: Account
) -> None:
    """T-API-300: the built-in check-up is listed with its period options; no read scope, 403."""
    r = client.get(f"{API}/reports", headers=bearer(api_factory, alice_account, ["read"]))
    assert r.status_code == 200, r.text
    checkup = next(d for d in r.json() if d["name"] == "checkup")
    assert checkup["builtin"] is True and checkup["title"]
    assert checkup["period"]["default"] == "14d"
    assert "custom" in checkup["period"]["options"]

    no_read = bearer(api_factory, alice_account, ["capture:write"])
    body = assert_problem(client.get(f"{API}/reports", headers=no_read), 403)
    assert "read" in body["detail"]


@pytest.mark.covers("POST /api/v1/reports/{name}/render")
def test_t_api_301_render_json_default_and_explicit_period(
    client: TestClient, alice_token: dict[str, str]
) -> None:
    """T-API-301: JSON render carries a flat from/to/today for the default and explicit periods."""
    r = client.post(
        f"{API}/reports/checkup/render", params={"as_of": "2026-03-14"}, headers=alice_token
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["from"], body["to"], body["today"]) == ("2026-03-01", "2026-03-14", "2026-03-14")

    r = client.post(
        f"{API}/reports/checkup/render",
        params={"from": "2026-02-01", "to": "2026-02-07", "as_of": "2026-03-14"},
        headers=alice_token,
    )
    assert r.status_code == 200, r.text
    assert (r.json()["from"], r.json()["to"]) == ("2026-02-01", "2026-02-07")

    # without as_of the server uses today in the tenant's time zone
    today = client.post(f"{API}/reports/checkup/render", headers=alice_token)
    assert today.status_code == 200 and today.json()["to"] == today.json()["today"]


@pytest.mark.covers("POST /api/v1/reports/{name}/render")
def test_t_api_302_render_markdown(client: TestClient, alice_token: dict[str, str]) -> None:
    """T-API-302: `format=markdown` answers text/markdown, not JSON."""
    r = client.post(
        f"{API}/reports/checkup/render",
        params={"format": "markdown", "as_of": "2026-03-14"},
        headers=alice_token,
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.text.lstrip().startswith("#")


@pytest.mark.covers("POST /api/v1/reports/{name}/render")
def test_t_api_303_render_refusals(client: TestClient, alice_token: dict[str, str]) -> None:
    """T-API-303: unknown report 404, reversed or half period 422, bad format 422."""
    body = assert_problem(client.post(f"{API}/reports/nope/render", headers=alice_token), 404)
    assert "nope" in body["detail"]
    body = assert_problem(
        client.post(
            f"{API}/reports/checkup/render",
            params={"from": "2026-03-10", "to": "2026-03-01"},
            headers=alice_token,
        ),
        422,
    )
    assert "before" in body["detail"]
    body = assert_problem(
        client.post(
            f"{API}/reports/checkup/render", params={"from": "2026-03-10"}, headers=alice_token
        ),
        422,
    )
    assert "both" in body["detail"]
    body = assert_problem(
        client.post(
            f"{API}/reports/checkup/render", params={"to": "2026-03-10"}, headers=alice_token
        ),
        422,
    )
    assert "both" in body["detail"]
    assert_problem(
        client.post(f"{API}/reports/checkup/render", params={"format": "pdf"}, headers=alice_token),
        422,
    )


@pytest.mark.covers("POST /api/v1/reports/{name}/render", "POST /api/v1/reports/{name}/snapshots")
def test_t_api_304_custom_default_period_needs_dates(
    client: TestClient, alice_token: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-API-304: a definition whose default period is `custom` refuses a render without dates."""
    real = reports_router._registry.get("checkup")
    custom = real.model_copy(update={"period": PeriodSpec(default="custom", options=["custom"])})
    monkeypatch.setattr(reports_router._registry, "get", lambda name: custom)
    body = assert_problem(client.post(f"{API}/reports/checkup/render", headers=alice_token), 422)
    assert "explicit dates" in body["detail"]
    assert_problem(client.post(f"{API}/reports/checkup/snapshots", headers=alice_token), 422)
    ok = client.post(
        f"{API}/reports/checkup/render",
        params={"from": "2026-03-01", "to": "2026-03-02"},
        headers=alice_token,
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.covers("GET /api/v1/reports/checkup")
def test_t_api_305_checkup_shortcut(client: TestClient, alice_token: dict[str, str]) -> None:
    """T-API-305: the check-up shortcut renders JSON and Markdown and checks the period."""
    r = client.get(f"{API}/reports/checkup", params={"as_of": "2026-03-14"}, headers=alice_token)
    assert r.status_code == 200, r.text
    assert r.json()["from"] == "2026-03-01"
    md = client.get(
        f"{API}/reports/checkup",
        params={"format": "markdown", "from": "2026-03-01", "to": "2026-03-07"},
        headers=alice_token,
    )
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert_problem(
        client.get(f"{API}/reports/checkup", params={"from": "2026-03-01"}, headers=alice_token),
        422,
    )
    assert_problem(client.get(f"{API}/reports/checkup"), 401)


@pytest.mark.covers(
    "POST /api/v1/reports/{name}/snapshots",
    "GET /api/v1/reports/snapshots",
    "GET /api/v1/reports/snapshots/{snapshot_id}",
    "POST /api/v1/reports/snapshots/{snapshot_id}/assess",
    "DELETE /api/v1/reports/snapshots/{snapshot_id}",
)
def test_t_api_306_snapshot_lifecycle(client: TestClient, alice_token: dict[str, str]) -> None:
    """T-API-306: freeze, list, read, assess once, delete — then the snapshot is gone."""
    r = client.post(
        f"{API}/reports/checkup/snapshots",
        params={"from": "2026-03-01", "to": "2026-03-14", "label": "March check"},
        headers=alice_token,
    )
    assert r.status_code == 201, r.text
    snap = r.json()
    assert snap["report_name"] == "checkup" and snap["label"] == "March check"
    assert (snap["period_start"], snap["period_end"]) == ("2026-03-01", "2026-03-14")
    assert snap["result"] is None and snap["assessment_md"] is None, "the list shape"

    default = client.post(
        f"{API}/reports/checkup/snapshots", params={"as_of": "2026-04-14"}, headers=alice_token
    )
    assert default.status_code == 201 and default.json()["period_end"] == "2026-04-14"
    assert default.json()["today"] == "2026-04-14"

    listed = client.get(f"{API}/reports/snapshots", headers=alice_token).json()
    assert {s["id"] for s in listed} == {snap["id"], default.json()["id"]}
    only_one = client.get(f"{API}/reports/snapshots", params={"limit": 1}, headers=alice_token)
    assert len(only_one.json()) == 1
    assert (
        client.get(
            f"{API}/reports/snapshots", params={"report": "other"}, headers=alice_token
        ).json()
        == []
    )
    assert_problem(
        client.get(f"{API}/reports/snapshots", params={"limit": 0}, headers=alice_token), 422
    )

    got = client.get(f"{API}/reports/snapshots/{snap['id']}", headers=alice_token)
    assert got.status_code == 200 and got.json()["id"] == snap["id"]
    assert got.json()["result"]["from"] == "2026-03-01", "the detail carries the frozen render"

    assessed = client.post(
        f"{API}/reports/snapshots/{snap['id']}/assess",
        json={"markdown": "Trend is flat.", "model": "manual-test"},
        headers=alice_token,
    )
    assert assessed.status_code == 200, assessed.text
    a = assessed.json()
    assert a["assessment_md"] == "Trend is flat." and a["model"] == "manual-test"
    assert a["prompt_version"] == "manual" and a["assessed_at"]

    again = client.post(
        f"{API}/reports/snapshots/{snap['id']}/assess", json={"markdown": "x"}, headers=alice_token
    )
    assert_problem(again, 409)
    blank = client.post(
        f"{API}/reports/snapshots/{default.json()['id']}/assess",
        json={"markdown": "   "},
        headers=alice_token,
    )
    assert_problem(blank, 422)

    deleted = client.delete(f"{API}/reports/snapshots/{snap['id']}", headers=alice_token)
    assert deleted.status_code == 204 and deleted.content == b""
    assert_problem(client.get(f"{API}/reports/snapshots/{snap['id']}", headers=alice_token), 404)
    assert_problem(client.delete(f"{API}/reports/snapshots/{snap['id']}", headers=alice_token), 404)


@pytest.mark.covers(
    "POST /api/v1/reports/{name}/snapshots",
    "GET /api/v1/reports/snapshots",
    "GET /api/v1/reports/snapshots/{snapshot_id}",
    "POST /api/v1/reports/snapshots/{snapshot_id}/assess",
    "DELETE /api/v1/reports/snapshots/{snapshot_id}",
)
def test_t_api_307_snapshots_are_tenant_scoped(
    client: TestClient, alice_token: dict[str, str], bob_token: dict[str, str]
) -> None:
    """T-API-307: Bob neither lists, reads, assesses nor deletes Alice's snapshot (404)."""
    snap = client.post(
        f"{API}/reports/checkup/snapshots", params={"as_of": "2026-03-14"}, headers=alice_token
    ).json()
    assert client.get(f"{API}/reports/snapshots", headers=bob_token).json() == []
    sid = snap["id"]
    assert_problem(client.get(f"{API}/reports/snapshots/{sid}", headers=bob_token), 404)
    assert_problem(
        client.post(
            f"{API}/reports/snapshots/{sid}/assess", json={"markdown": "x"}, headers=bob_token
        ),
        404,
    )
    assert_problem(client.delete(f"{API}/reports/snapshots/{sid}", headers=bob_token), 404)
    assert client.get(f"{API}/reports/snapshots/{sid}", headers=alice_token).status_code == 200


@pytest.mark.covers("POST /api/v1/reports/{name}/snapshots")
def test_t_api_308_snapshot_refusals(
    client: TestClient, alice_token: dict[str, str], api_factory: UowFactory, alice_account: Account
) -> None:
    """T-API-308: unknown report 404, reversed period 422, over-long label 422, no read 403."""
    assert_problem(client.post(f"{API}/reports/nope/snapshots", headers=alice_token), 404)
    assert_problem(
        client.post(
            f"{API}/reports/checkup/snapshots",
            params={"from": "2026-03-10", "to": "2026-03-01"},
            headers=alice_token,
        ),
        422,
    )
    assert_problem(
        client.post(
            f"{API}/reports/checkup/snapshots", params={"label": "x" * 201}, headers=alice_token
        ),
        422,
    )
    no_read = bearer(api_factory, alice_account, ["capture:write"])
    assert_problem(client.post(f"{API}/reports/checkup/snapshots", headers=no_read), 403)


@pytest.mark.covers("POST /api/v1/reports/snapshots/{snapshot_id}/assess")
def test_t_api_309_assess_needs_a_write_scope(
    client: TestClient, alice_token: dict[str, str], api_factory: UowFactory, alice_account: Account
) -> None:
    """T-API-309: a read-only token cannot attach an assessment (403); agent:write can."""
    sid = client.post(
        f"{API}/reports/checkup/snapshots", params={"as_of": "2026-03-14"}, headers=alice_token
    ).json()["id"]
    read_only = bearer(api_factory, alice_account, ["read"])
    assert_problem(
        client.post(
            f"{API}/reports/snapshots/{sid}/assess", json={"markdown": "x"}, headers=read_only
        ),
        403,
    )
    agent = bearer(api_factory, alice_account, ["read", "agent:write"])
    r = client.post(f"{API}/reports/snapshots/{sid}/assess", json={"markdown": "ok"}, headers=agent)
    assert r.status_code == 200 and r.json()["status"] != "pending"
