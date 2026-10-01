"""Small helpers shared by the ``test_cov_*`` API tests (no fixtures, no conftest)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient

API = "/api/v1"
PROBLEM = "application/problem+json"
SETTINGS_EXAMPLE = Path(__file__).parents[3] / "examples" / "tenant-settings.yaml"


def settings_doc() -> dict[str, Any]:
    """The example tenant settings (synthetic values, shipped with the repository)."""
    doc: dict[str, Any] = yaml.safe_load(SETTINGS_EXAMPLE.read_text(encoding="utf-8"))
    return doc


def put_settings(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    r = client.put(f"{API}/settings", json={"data": settings_doc()}, headers=headers)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def assert_problem(r: Any, status: int) -> dict[str, Any]:
    """The response is an RFC 9457 problem with this status; returns its body."""
    assert r.status_code == status, f"{r.status_code} {r.text}"
    assert r.headers["content-type"].startswith(PROBLEM), r.headers["content-type"]
    body: dict[str, Any] = r.json()
    assert body["status"] == status and body["title"]
    return body


def product(client: TestClient, headers: dict[str, str], name: str = "Oat flakes") -> int:
    r = client.post(
        f"{API}/products",
        json={
            "name": name,
            "kcal": 370,
            "protein": 13,
            "carbs": 59,
            "fat": 7,
            "fiber": 10,
            "salt": 0.02,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def day_with_meal(client: TestClient, headers: dict[str, str], day: str) -> int:
    """Create the day and one meal; returns the meal id."""
    r = client.post(f"{API}/days/{day}", json={"reliable": True}, headers=headers)
    assert r.status_code == 201, r.text
    m = client.post(f"{API}/days/{day}/meals", json={"name": "Breakfast"}, headers=headers)
    assert m.status_code == 201, m.text
    return int(m.json()["id"])


def line_item(
    client: TestClient, headers: dict[str, str], meal_id: int, product_id: int, grams: float
) -> dict[str, Any]:
    r = client.post(
        f"{API}/meals/{meal_id}/line-items",
        json={"consumable_id": product_id, "amount": grams, "unit_code": "g"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body
