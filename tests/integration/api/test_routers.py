"""T-API-011…015 and router smoke tests over HTTP with bearer tokens."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.api

DAY = "2026-03-10"


def _seed_alice(client: TestClient, alice_token: dict[str, str]) -> dict[str, int]:
    p = client.post(
        "/api/v1/products",
        json={
            "name": "Skyr natural",
            "kcal": 63,
            "protein": 11,
            "carbs": 4,
            "fat": 0.2,
            "fiber": 0,
            "salt": 0.1,
            "category": "Dairy",
        },
        headers=alice_token,
    )
    assert p.status_code == 201, p.text
    product_id = p.json()["id"]
    portion = client.post(
        f"/api/v1/products/{product_id}/portions",
        json={"unit_code": "tub", "label": "tub", "amount": 400, "is_default": True},
        headers=alice_token,
    )
    assert portion.status_code == 201
    day = client.post(
        f"/api/v1/days/{DAY}", json={"reliable": True, "training_type": "rest"}, headers=alice_token
    )
    assert day.status_code == 201
    meal = client.post(
        f"/api/v1/days/{DAY}/meals",
        json={"name": "Breakfast", "time": "07:30"},
        headers=alice_token,
    )
    assert meal.status_code == 201
    meal_id = meal.json()["id"]
    item = client.post(
        f"/api/v1/meals/{meal_id}/line-items",
        json={"consumable_id": product_id, "amount": 1, "unit_code": "tub"},
        headers=alice_token,
    )
    assert item.status_code == 201, item.text
    recipe = client.post(
        "/api/v1/recipes", json={"name": "Skyr bowl", "default_servings": 2}, headers=alice_token
    )
    assert recipe.status_code == 201
    weight = client.post(
        "/api/v1/weight",
        json={"measured_at": "2026-03-10T07:00:00Z", "kg": 84.2},
        headers=alice_token,
    )
    assert weight.status_code == 201
    return {
        "product": product_id,
        "portion": portion.json()["id"],
        "meal": meal_id,
        "item": item.json()["id"],
        "recipe": recipe.json()["id"],
        "weight": weight.json()["id"],
    }


def test_t_api_013_day_detail(client: TestClient, alice_token: dict[str, str]) -> None:
    """T-API-013: day detail carries computed macros, meals with items, zones and findings."""
    _seed_alice(client, alice_token)
    r = client.get(f"/api/v1/days/{DAY}", headers=alice_token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["macros"]["kcal"] == 252 and body["macros"]["protein"] == 44.0
    item = body["meals"][0]["line_items"][0]
    assert (
        item["consumable_name"] == "Skyr natural"
        and item["base_amount"] == 400
        and item["kcal"] == 252
    )
    assert body["meals"][0]["time"] == "07:30"
    assert body["weight_kg"] == 84.2
    assert isinstance(body["findings"], list) and "zones" in body
    days = client.get(
        "/api/v1/days", params={"from": "2026-03-01", "to": "2026-03-31"}, headers=alice_token
    ).json()
    assert [d["date"] for d in days] == [DAY] and days[0]["macros"]["kcal"] == 252


def test_t_api_012_search_and_match(client: TestClient, alice_token: dict[str, str]) -> None:
    """T-API-012: substring search and match candidates with tier and score."""
    _seed_alice(client, alice_token)
    r = client.get("/api/v1/products", params={"q": "skyr"}, headers=alice_token)
    assert r.status_code == 200 and r.json()[0]["name"] == "Skyr natural"
    assert r.json()[0]["portions"][0]["label"] == "tub" and r.json()[0]["category"] == "Dairy"
    m = client.post(
        "/api/v1/products/match", json={"text": "Skyr natural 400 g"}, headers=alice_token
    )
    assert (
        m.status_code == 200 and m.json()[0]["tier"] in (1, 2, 3) and 0 < m.json()[0]["score"] <= 1
    )
    assert client.get("/api/v1/products", params={"q": "zzz"}, headers=alice_token).json() == []
    assert client.get("/api/v1/units", headers=alice_token).json()[0]["code"]
    assert client.get("/api/v1/categories", headers=alice_token).json()[0]["name"] == "Dairy"


@pytest.mark.parametrize(
    "method,path_template,body",
    [
        ("GET", "/api/v1/products/{product}", None),
        ("PATCH", "/api/v1/products/{product}", {"kcal": 1}),
        ("DELETE", "/api/v1/products/{product}", None),
        ("PATCH", "/api/v1/portions/{portion}", {"amount": 1}),
        ("GET", "/api/v1/days/" + DAY, None),
        ("PUT", "/api/v1/days/" + DAY, {"reliable": False}),
        ("POST", "/api/v1/days/" + DAY + "/meals", {"name": "Lunch"}),
        (
            "POST",
            "/api/v1/meals/{meal}/line-items",
            {"consumable_id": 1, "amount": 1, "unit_code": "g"},
        ),
        ("PATCH", "/api/v1/line-items/{item}", {"amount": 2}),
        ("DELETE", "/api/v1/line-items/{item}", None),
        ("GET", "/api/v1/recipes/{recipe}", None),
        ("DELETE", "/api/v1/weight/{weight}", None),
        ("GET", "/api/v1/drafts/" + DAY + "/summary", None),
    ],
)
def test_t_api_011_foreign_tenant_is_404(
    client: TestClient,
    alice_token: dict[str, str],
    bob_token: dict[str, str],
    method: str,
    path_template: str,
    body: dict | None,  # type: ignore[type-arg]
) -> None:
    """T-API-011: Bob gets 404 for every Alice resource and never a body that leaks it."""
    ids = _seed_alice(client, alice_token)
    path = path_template.format(**ids)
    r = client.request(method, path, json=body, headers=bob_token)
    assert r.status_code == 404, f"{method} {path}: {r.status_code} {r.text}"
    assert "Skyr" not in r.text
    assert r.headers["content-type"].startswith("application/problem+json")


def test_t_api_014_problem_json(client: TestClient, alice_token: dict[str, str]) -> None:
    """T-API-014: validation and application errors come as problem+json with field paths."""
    r = client.post("/api/v1/products", json={"name": ""}, headers=alice_token)
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 422 and body["errors"][0]["field"] == "name"
    r = client.get("/api/v1/products/999999", headers=alice_token)
    assert r.status_code == 404 and r.json()["title"] == "Not found"
    r = client.get("/api/v1/days/" + DAY)
    assert r.status_code == 401 and r.json()["status"] == 401


def test_t_api_015_health_and_openapi(client: TestClient) -> None:
    """T-API-015: health lists db, migrations, storage and backup; OpenAPI covers the routers."""
    h = client.get("/api/v1/health")
    assert h.status_code == 200
    body = h.json()
    assert body["status"] == "ok"
    assert body["checks"]["db"] == "ok" and body["checks"]["migrations"] == "ok"
    assert body["checks"]["storage"] == "ok" and body["checks"]["backup"] == "none"
    assert body["backup_age_hours"] is None
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    for p in (
        "/api/v1/auth/webauthn/login/options",
        "/api/v1/products",
        "/api/v1/days/{day}",
        "/api/v1/drafts",
        "/api/v1/weight",
        "/api/v1/settings",
        "/api/v1/target-bands",
        "/api/v1/recipes",
    ):
        assert p in paths, p


def test_planned_routes_answer_501(client: TestClient, alice_token: dict[str, str]) -> None:
    r = client.get("/api/v1/backup/jobs", headers=alice_token)
    assert r.status_code == 501 and "backup" in r.json()["detail"]


def test_day_thread_and_drafts_over_http(client: TestClient, alice_token: dict[str, str]) -> None:
    ids = _seed_alice(client, alice_token)
    # a draft item, a message → follow-up queued, approval closes the day
    r = client.post(
        f"/api/v1/meals/{ids['meal']}/line-items",
        json={"consumable_id": ids["product"], "amount": 100, "unit_code": "g", "estimated": True},
        headers=alice_token,
    )
    item_id = r.json()["id"]
    # mark it as a draft through the repository (the agent does this in Stage 3)
    from victus.infrastructure.db import orm

    engine = client.app.state.engine  # type: ignore[attr-defined]
    with client.app.state.session_factory() as s:  # type: ignore[attr-defined]
        li = s.get(orm.LineItem, item_id)
        assert li is not None
        li.is_draft = True
        s.commit()
    assert engine is not None
    drafts = client.get("/api/v1/drafts", headers=alice_token).json()
    assert drafts and drafts[0]["date"] == DAY and drafts[0]["draft_items"] == 1
    m = client.post(
        f"/api/v1/days/{DAY}/messages", json={"text": "it was 150 g"}, headers=alice_token
    )
    assert m.status_code == 201 and m.json()["processing_state"] == "new"
    thread = client.get(f"/api/v1/days/{DAY}/messages", headers=alice_token).json()
    assert thread[-1]["content"] == "it was 150 g"
    summary = client.get(f"/api/v1/drafts/{DAY}/summary", headers=alice_token).json()
    assert "Skyr natural" in summary["markdown"] and summary["day"]["date"] == DAY
    approved = client.post(
        f"/api/v1/drafts/{DAY}/approve",
        json={"corrections": [{"line_item_id": item_id, "amount": 150}], "close": True},
        headers=alice_token,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "closed"
    assert all(not li["is_draft"] for li in approved.json()["meals"][0]["line_items"])
    assert client.get("/api/v1/drafts", headers=alice_token).json() == []


def test_settings_roundtrip_over_http(client: TestClient, alice_token: dict[str, str]) -> None:
    """PUT /settings validates against the schema, versions the document and syncs target bands."""
    import yaml

    doc = yaml.safe_load(
        (Path(__file__).parents[3] / "examples" / "tenant-settings.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert client.get("/api/v1/settings", headers=alice_token).status_code == 404
    r = client.put("/api/v1/settings", json={"data": doc}, headers=alice_token)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1
    bands = client.get("/api/v1/target-bands", headers=alice_token).json()
    assert len(bands) == len(doc["target_bands"])
    rest = next(b for b in bands if b["training_type"] == "rest")
    assert rest["salt"]["opt_max"] == 8
    bad = client.put("/api/v1/settings", json={"data": {"kcal_per_kg": "x"}}, headers=alice_token)
    assert bad.status_code == 422 and bad.json()["errors"]
