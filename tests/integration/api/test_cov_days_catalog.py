"""T-API-322…329: day, meal, draft, recipe and catalogue routes the router smoke tests leave out."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.integration.api.cov_support import (
    API,
    assert_problem,
    day_with_meal,
    line_item,
    product,
)
from victus.infrastructure.db import orm

pytestmark = pytest.mark.api

DAY = "2026-04-06"


def _mark_draft(client: TestClient, item_id: int) -> None:
    """Make an item a draft the way the agent's write path does (no route sets the flag)."""
    with client.app.state.session_factory() as s:  # type: ignore[attr-defined]
        li = s.get(orm.LineItem, item_id)
        assert li is not None
        li.is_draft = True
        s.commit()


@pytest.mark.covers(
    "PATCH /api/v1/meals/{meal_id}",
    "DELETE /api/v1/meals/{meal_id}",
    "POST /api/v1/days/{day}/close",
    "POST /api/v1/days/{day}/reopen",
)
def test_t_api_322_meal_edit_and_day_close_reopen(
    client: TestClient, alice_token: dict[str, str]
) -> None:
    """T-API-322: a meal is renamed and removed; a day is closed and reopened; unknown ids
    are 404 and an empty name is 422."""
    meal_id = day_with_meal(client, alice_token, DAY)

    r = client.patch(
        f"{API}/meals/{meal_id}",
        json={"name": "Late breakfast", "time": "09:15"},
        headers=alice_token,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Late breakfast" and r.json()["time"].startswith("09:15")
    assert_problem(
        client.patch(f"{API}/meals/{meal_id}", json={"name": ""}, headers=alice_token), 422
    )
    assert_problem(
        client.patch(f"{API}/meals/999999", json={"name": "x"}, headers=alice_token), 404
    )

    closed = client.post(f"{API}/days/{DAY}/close", headers=alice_token)
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    reopened = client.post(f"{API}/days/{DAY}/reopen", headers=alice_token)
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "open"
    assert_problem(client.post(f"{API}/days/2026-01-01/close", headers=alice_token), 404)

    assert client.delete(f"{API}/meals/{meal_id}", headers=alice_token).status_code == 204
    assert client.get(f"{API}/days/{DAY}", headers=alice_token).json()["meals"] == []
    assert_problem(client.delete(f"{API}/meals/{meal_id}", headers=alice_token), 404)


@pytest.mark.covers(
    "POST /api/v1/line-items/{item_id}/approve", "POST /api/v1/drafts/{day}/discard"
)
def test_t_api_323_single_item_approval_and_discard(
    client: TestClient, alice_token: dict[str, str]
) -> None:
    """T-API-323: one drafted item is accepted with and without corrections; discarding the
    draft removes the drafted rest and reports how many went."""
    meal_id = day_with_meal(client, alice_token, DAY)
    oats = product(client, alice_token)
    plain = line_item(client, alice_token, meal_id, oats, 40)["id"]
    corrected = line_item(client, alice_token, meal_id, oats, 50)["id"]
    moved = line_item(client, alice_token, meal_id, oats, 60)["id"]
    dropped = line_item(client, alice_token, meal_id, oats, 70)["id"]
    for item in (plain, corrected, moved, dropped):
        _mark_draft(client, item)

    r = client.post(f"{API}/line-items/{plain}/approve", headers=alice_token)
    assert r.status_code == 200, r.text
    assert r.json()["is_draft"] is False and r.json()["amount"] == 40

    r = client.post(
        f"{API}/line-items/{corrected}/approve", json={"amount": 55}, headers=alice_token
    )
    assert r.status_code == 200, r.text
    assert r.json()["amount"] == 55 and r.json()["is_draft"] is False

    r = client.post(
        f"{API}/line-items/{moved}/approve", json={"meal_name": "Snack"}, headers=alice_token
    )
    assert r.status_code == 200, r.text
    meals = client.get(f"{API}/days/{DAY}", headers=alice_token).json()["meals"]
    assert {m["name"] for m in meals} == {"Breakfast", "Snack"}

    assert_problem(client.post(f"{API}/line-items/999999/approve", headers=alice_token), 404)

    discarded = client.post(f"{API}/drafts/{DAY}/discard", headers=alice_token)
    assert discarded.status_code == 200, discarded.text
    assert discarded.json() == {"removed": 1}
    items = [
        li["id"]
        for m in client.get(f"{API}/days/{DAY}", headers=alice_token).json()["meals"]
        for li in m["line_items"]
    ]
    assert dropped not in items and {plain, corrected, moved} <= set(items)


@pytest.mark.covers(
    "GET /api/v1/recipes",
    "POST /api/v1/recipes",
    "PATCH /api/v1/recipes/{recipe_id}",
    "PUT /api/v1/recipes/{recipe_id}/ingredients",
    "POST /api/v1/recipes/{recipe_id}/batches",
    "GET /api/v1/batches/{batch_id}",
)
def test_t_api_324_recipe_ingredients_and_batches(
    client: TestClient, alice_token: dict[str, str]
) -> None:
    """T-API-324: a recipe is renamed, gets ingredients (a product and free text), is cooked
    into a batch whose totals are computed, and the batch is read back; unknown ids are 404."""
    oats = product(client, alice_token)
    r = client.post(f"{API}/recipes", json={"name": "Porridge"}, headers=alice_token)
    assert r.status_code == 201, r.text
    recipe_id = r.json()["id"]

    r = client.patch(
        f"{API}/recipes/{recipe_id}",
        json={"name": "Oat porridge", "default_servings": 2},
        headers=alice_token,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Oat porridge" and r.json()["default_servings"] == 2

    r = client.put(
        f"{API}/recipes/{recipe_id}/ingredients",
        json={
            "ingredients": [
                {"product_id": oats, "amount": 100, "unit_code": "g"},
                {"free_text": "a pinch of salt"},
            ]
        },
        headers=alice_token,
    )
    assert r.status_code == 200, r.text
    ingredients = r.json()["ingredients"]
    assert [i["product_name"] for i in ingredients] == ["Oat flakes", None]
    assert ingredients[1]["free_text"] == "a pinch of salt"

    listed = client.get(f"{API}/recipes", headers=alice_token).json()
    assert [x["name"] for x in listed] == ["Oat porridge"]

    b = client.post(
        f"{API}/recipes/{recipe_id}/batches",
        json={"cooked_at": "2026-04-06", "total_weight_g": 400, "servings": 2},
        headers=alice_token,
    )
    assert b.status_code == 201, b.text
    batch = b.json()
    assert batch["recipe_id"] == recipe_id and batch["total_weight_g"] == 400
    assert batch["kcal"] == pytest.approx(370)  # 100 g oat flakes at 370 kcal/100 g

    again = client.get(f"{API}/batches/{batch['id']}", headers=alice_token)
    assert again.status_code == 200 and again.json()["id"] == batch["id"]

    assert_problem(client.get(f"{API}/batches/999999", headers=alice_token), 404)
    assert_problem(
        client.patch(f"{API}/recipes/999999", json={"name": "x"}, headers=alice_token), 404
    )
    assert_problem(
        client.put(
            f"{API}/recipes/999999/ingredients", json={"ingredients": []}, headers=alice_token
        ),
        404,
    )
    assert_problem(client.post(f"{API}/recipes/999999/batches", json={}, headers=alice_token), 404)


@pytest.mark.covers(
    "GET /api/v1/products/{product_id}/portions",
    "DELETE /api/v1/portions/{portion_id}",
    "GET /api/v1/products/{product_id}/usage",
    "POST /api/v1/categories",
)
def test_t_api_325_portions_usage_and_categories(
    client: TestClient, alice_token: dict[str, str]
) -> None:
    """T-API-325: a product's portions are listed and one removed; usage lists the days it
    was logged on; a category is created and listed; unknown ids are 404."""
    oats = product(client, alice_token)
    r = client.post(
        f"{API}/products/{oats}/portions",
        json={"unit_code": "cup", "label": "cup", "amount": 80, "is_default": False},
        headers=alice_token,
    )
    assert r.status_code == 201, r.text
    portion_id = r.json()["id"]
    portions = client.get(f"{API}/products/{oats}/portions", headers=alice_token)
    assert portions.status_code == 200
    assert [p["id"] for p in portions.json()] == [portion_id]
    assert client.delete(f"{API}/portions/{portion_id}", headers=alice_token).status_code == 204
    assert client.get(f"{API}/products/{oats}/portions", headers=alice_token).json() == []
    assert_problem(client.delete(f"{API}/portions/{portion_id}", headers=alice_token), 404)
    assert_problem(client.get(f"{API}/products/999999/portions", headers=alice_token), 404)

    meal_id = day_with_meal(client, alice_token, DAY)
    line_item(client, alice_token, meal_id, oats, 40)
    usage = client.get(f"{API}/products/{oats}/usage", params={"limit": 5}, headers=alice_token)
    assert usage.status_code == 200, usage.text
    assert usage.json()["item_count"] == 1
    assert_problem(
        client.get(f"{API}/products/{oats}/usage", params={"limit": 0}, headers=alice_token), 422
    )

    c = client.post(f"{API}/categories", json={"name": "Cereals"}, headers=alice_token)
    assert c.status_code == 201, c.text
    names = [x["name"] for x in client.get(f"{API}/categories", headers=alice_token).json()]
    assert "Cereals" in names
    assert_problem(client.post(f"{API}/categories", json={"name": ""}, headers=alice_token), 422)


@pytest.mark.covers("POST /api/v1/captures", "DELETE /api/v1/captures/{capture_id}")
def test_t_api_326_capture_delete(client: TestClient, alice_token: dict[str, str]) -> None:
    """T-API-326: an open capture is deleted with its files; a second delete is 404."""
    r = client.post(
        f"{API}/captures",
        data={"text": "two eggs and toast", "target_date": DAY},
        headers=alice_token,
    )
    assert r.status_code == 201, r.text
    capture_id = r.json()["id"]
    assert client.delete(f"{API}/captures/{capture_id}", headers=alice_token).status_code == 204
    assert_problem(client.get(f"{API}/captures/{capture_id}", headers=alice_token), 404)
    assert_problem(client.delete(f"{API}/captures/{capture_id}", headers=alice_token), 404)
