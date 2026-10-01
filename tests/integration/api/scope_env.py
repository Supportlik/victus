"""A seeded tenant and one request per REST route, for the scope tests.

Every route of ``victus.api.scopes.ROUTE_SCOPES`` that needs a scope has an entry in
:data:`REQUESTS`: a function that builds a *valid* request — creating whatever it changes
or removes first, with the owner's token — so a refusal can only come from the scopes and
an acceptance shows the use case asks for nothing more than the route declares.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from victus.application.tenant_context import ALL_SCOPES, TenantContext
from victus.application.use_cases import auth as auth_uc
from victus.application.use_cases import tenants as tenants_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.db.uow import SqlAlchemyUnitOfWork

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478"
    "9c6360000002000154a24f5d0000000049454e44ae426082"
)
ROOT = Path(__file__).resolve().parents[3]
API = "/api/v1"


@dataclass
class Req:
    method: str
    path: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    #: Statuses that count as "the scopes were enough" besides 2xx.
    also_ok: tuple[int, ...] = ()


class Env:
    """One tenant (alice) with an owner, a token per scope set and helpers that seed rows."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.client = TestClient(app)
        self.factory: UowFactory = lambda ctx: SqlAlchemyUnitOfWork(app.state.session_factory, ctx)
        tenant = tenants_uc.CreateTenant(self.factory, TenantContext(tenant_id="-")).execute(
            "alice", "Alice"
        )
        system = TenantContext(tenant_id=tenant.id, scopes=ALL_SCOPES)
        owner = tenants_uc.CreateUser(self.factory, system).execute(
            "Alice", "alice@example.com", "owner"
        )
        self.tenant_id = tenant.id
        self.owner_ctx = TenantContext(tenant_id=tenant.id, user_id=owner.user.id)
        self._tokens: dict[frozenset[str], dict[str, str]] = {}
        self._days = itertools.count(1)
        self.owner = self.headers(ALL_SCOPES)
        self.seed()

    # ── principals ──────────────────────────────────────────────────────────

    def headers(self, scopes: frozenset[str] | set[str]) -> dict[str, str]:
        key = frozenset(scopes)
        if key not in self._tokens:
            created = auth_uc.CreateToken(self.factory, self.owner_ctx).execute(
                "scope-test", sorted(key), None
            )
            self._tokens[key] = {"Authorization": f"Bearer {created.token}"}
        return self._tokens[key]

    # ── seeding, always as the owner ────────────────────────────────────────

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        r = self.client.request(method, API + path, headers=self.owner, **kwargs)
        assert r.status_code < 300, f"{method} {path}: {r.status_code} {r.text}"
        return r.json() if r.content else None

    def fresh_date(self) -> str:
        return (date(2025, 1, 1) + timedelta(days=next(self._days))).isoformat()

    def stamp(self) -> str:
        return f"{self.fresh_date()}T07:00:00Z"

    def product(self) -> dict[str, Any]:
        n = next(self._days)
        return self.call("POST", "/products", json={"name": f"Skyr {n}", "kcal": 63})

    def portion(self, product_id: int) -> dict[str, Any]:
        n = next(self._days)
        return self.call(
            "POST",
            f"/products/{product_id}/portions",
            json={"unit_code": "piece", "label": f"piece {n}", "amount": 50},
        )

    def day(self) -> str:
        day = self.fresh_date()
        self.call("POST", f"/days/{day}", json={"reliable": True})
        return day

    def meal(self, day: str | None = None) -> tuple[str, int]:
        day = day or self.day()
        meal = self.call("POST", f"/days/{day}/meals", json={"name": "Breakfast"})
        return day, int(meal["id"])

    def draft_item(self) -> tuple[str, int]:
        """A drafted line item: logged by a token without ``approve`` (R81)."""
        day, meal_id = self.meal()
        r = self.client.post(
            f"{API}/meals/{meal_id}/line-items",
            json={"consumable_id": self.ids["product"], "amount": 100, "unit_code": "g"},
            headers=self.headers({"write"}),
        )
        assert r.status_code == 201 and r.json()["is_draft"], r.text
        return day, int(r.json()["id"])

    def proposal(self) -> str:
        r = self.client.post(
            f"{API}/products",
            json={"name": f"Pending {next(self._days)}", "kcal": 10},
            headers=self.headers({"agent:write"}),
        )
        assert r.status_code == 202, r.text
        return str(r.json()["id"])

    def capture(self, **files: Any) -> dict[str, Any]:
        return self.call("POST", "/captures", data={"text": "two slices of bread"}, **files)

    def snapshot(self) -> str:
        return str(self.call("POST", "/reports/checkup/snapshots")["id"])

    def run(self) -> str:
        return str(self.call("POST", "/agent/runs", json={})["id"])

    def seed(self) -> None:
        product = self.product()
        portion = self.portion(product["id"])
        day, meal_id = self.meal()
        recipe = self.call("POST", "/recipes", json={"name": "Skyr bowl", "default_servings": 2})
        batch = self.call("POST", f"/recipes/{recipe['id']}/batches", json={"servings": 2})
        photo = self.call("POST", "/captures", files={"file": ("label.png", PNG, "image/png")})
        settings = yaml.safe_load(
            (ROOT / "examples" / "tenant-settings.yaml").read_text(encoding="utf-8")
        )
        self.call("PUT", "/settings", json={"data": settings})
        self.settings = settings
        self.ids: dict[str, Any] = {
            "product": product["id"],
            "portion": portion["id"],
            "day": day,
            "meal": meal_id,
            "recipe": recipe["id"],
            "batch": batch["id"],
            "capture": photo["id"],
            "attachment": photo["attachment_id"],
        }
        self.ids["proposal"] = self.proposal()
        self.ids["snapshot"] = self.snapshot()
        self.ids["run"] = self.run()


Builder = Callable[[Env], Req]


def _get(path: str, **kwargs: Any) -> Builder:
    return lambda env: Req("GET", path.format(**env.ids), kwargs)


def _weight(env: Env) -> Req:
    row = env.call("POST", "/weight", json={"measured_at": env.stamp(), "kg": 80.5})
    return Req("DELETE", f"/weight/{row['id']}")


def _body(env: Env) -> Req:
    row = env.call("POST", "/body-measurements", json={"measured_at": env.stamp(), "waist_cm": 80})
    return Req("DELETE", f"/body-measurements/{row['id']}")


def _rule(env: Env) -> Req:
    name = f"rule-{next(env._days)}"
    env.call("PUT", "/settings/rules", json={"when": "bread", "then": "one slice", "name": name})
    return Req("DELETE", f"/settings/rules/{name}")


def _band(env: Env) -> Req:
    band = {"min": 1, "opt_min": 2, "opt_max": 3, "max": 4}
    return Req(
        "POST",
        "/target-bands",
        {
            "json": {
                "name": f"band {next(env._days)}",
                "valid_from": env.fresh_date(),
                **{k: band for k in ("protein", "carbs", "fat", "fiber", "salt")},
            }
        },
    )


def _close(env: Env) -> Req:
    return Req("POST", f"/days/{env.day()}/close")


def _reopen(env: Env) -> Req:
    day = env.day()
    env.call("POST", f"/days/{day}/close")
    return Req("POST", f"/days/{day}/reopen")


def _approve_day(env: Env) -> Req:
    day, _ = env.draft_item()
    return Req("POST", f"/drafts/{day}/approve", {"json": {"close": False}})


def _discard(env: Env) -> Req:
    day, _ = env.draft_item()
    return Req("POST", f"/drafts/{day}/discard")


def _approve_item(env: Env) -> Req:
    _, item = env.draft_item()
    return Req("POST", f"/line-items/{item}/approve", {"json": {}})


def _patch_item(env: Env) -> Req:
    _, item = env.draft_item()
    return Req("PATCH", f"/line-items/{item}", {"json": {"amount": 120}})


def _delete_item(env: Env) -> Req:
    _, item = env.draft_item()
    return Req("DELETE", f"/line-items/{item}")


def _add_item(env: Env) -> Req:
    _, meal = env.meal()
    return Req(
        "POST",
        f"/meals/{meal}/line-items",
        {"json": {"consumable_id": env.ids["product"], "amount": 100, "unit_code": "g"}},
    )


def _delete_meal(env: Env) -> Req:
    _, meal = env.meal()
    return Req("DELETE", f"/meals/{meal}")


def _delete_product(env: Env) -> Req:
    return Req("DELETE", f"/products/{env.product()['id']}")


def _delete_portion(env: Env) -> Req:
    return Req("DELETE", f"/portions/{env.portion(env.ids['product'])['id']}")


def _patch_portion(env: Env) -> Req:
    portion = env.portion(env.ids["product"])
    return Req("PATCH", f"/portions/{portion['id']}", {"json": {"amount": 55}})


def _add_portion(env: Env) -> Req:
    return Req(
        "POST",
        f"/products/{env.product()['id']}/portions",
        {"json": {"unit_code": "slice", "label": "slice", "amount": 30}},
    )


def _version(env: Env) -> Req:
    return Req(
        "POST",
        f"/products/{env.product()['id']}/versions",
        {"json": {"valid_from": "2026-06-01", "changes": {"kcal": 70}}},
    )


def _decide(verdict: str) -> Builder:
    def build(env: Env) -> Req:
        kwargs = {"json": {}} if verdict == "approve" else {}
        return Req("POST", f"/proposals/{env.proposal()}/{verdict}", kwargs)

    return build


def _capture_delete(env: Env) -> Req:
    return Req("DELETE", f"/captures/{env.capture()['id']}")


def _capture_patch(env: Env) -> Req:
    return Req("PATCH", f"/captures/{env.capture()['id']}", {"json": {"status": "processed"}})


def _transcribe(env: Env) -> Req:
    cap = env.call(
        "POST",
        "/captures",
        files={"file": ("note.oga", b"OggS-fake", "application/octet-stream")},
    )
    return Req("POST", f"/captures/{cap['id']}/transcribe", {"params": {"force": True}})


def _assess(env: Env) -> Req:
    return Req(
        "POST", f"/reports/snapshots/{env.snapshot()}/assess", {"json": {"markdown": "Fine."}}
    )


def _delete_snapshot(env: Env) -> Req:
    return Req("DELETE", f"/reports/snapshots/{env.snapshot()}")


def _cancel_run(env: Env) -> Req:
    return Req("POST", f"/agent/runs/{env.run()}/cancel")


def _new_user(env: Env) -> Req:
    n = next(env._days)
    return Req(
        "POST", "/tenant/users", {"json": {"display_name": f"M{n}", "email": f"m{n}@example.com"}}
    )


REQUESTS: dict[str, Builder] = {
    # agent
    "GET /agent/status": _get("/agent/status"),
    "POST /agent/runs": lambda env: Req("POST", "/agent/runs", {"json": {}}),
    "GET /agent/runs": _get("/agent/runs"),
    "GET /agent/runs/{run_id}": _get("/agent/runs/{run}"),
    "POST /agent/runs/{run_id}/cancel": _cancel_run,
    "GET /agent/locks": _get("/agent/locks"),
    "DELETE /agent/locks/{day}": lambda env: Req("DELETE", f"/agent/locks/{env.fresh_date()}"),
    # captures
    "POST /captures": lambda env: Req("POST", "/captures", {"data": {"text": "an apple"}}),
    "GET /captures": _get("/captures"),
    "DELETE /captures/{capture_id}": _capture_delete,
    "GET /captures/{capture_id}": _get("/captures/{capture}"),
    "PATCH /captures/{capture_id}": _capture_patch,
    "POST /captures/{capture_id}/transcribe": _transcribe,
    "GET /attachments/{attachment_id}": _get("/attachments/{attachment}"),
    # days
    "GET /days": _get("/days", params={"from": "2025-01-01", "to": "2025-12-31"}),
    "GET /days/{day}": _get("/days/{day}"),
    "POST /days/{day}": lambda env: Req(
        "POST", f"/days/{env.fresh_date()}", {"json": {"reliable": True}}
    ),
    "PUT /days/{day}": lambda env: Req(
        "PUT", f"/days/{env.day()}", {"json": {"training_type": "rest"}}
    ),
    "POST /days/{day}/meals": lambda env: Req(
        "POST", f"/days/{env.day()}/meals", {"json": {"name": "Lunch"}}
    ),
    "PATCH /meals/{meal_id}": lambda env: Req(
        "PATCH", f"/meals/{env.meal()[1]}", {"json": {"name": "Brunch"}}
    ),
    "DELETE /meals/{meal_id}": _delete_meal,
    "POST /meals/{meal_id}/line-items": _add_item,
    "PATCH /line-items/{item_id}": _patch_item,
    "DELETE /line-items/{item_id}": _delete_item,
    "POST /days/{day}/close": _close,
    "POST /days/{day}/reopen": _reopen,
    "GET /days/{day}/messages": _get("/days/{day}/messages"),
    "POST /days/{day}/messages": lambda env: Req(
        "POST", f"/days/{env.day()}/messages", {"json": {"text": "it was 150 g"}}
    ),
    # drafts
    "GET /drafts": _get("/drafts"),
    "GET /drafts/{day}/summary": lambda env: Req("GET", f"/drafts/{env.draft_item()[0]}/summary"),
    "POST /drafts/{day}/approve": _approve_day,
    "POST /line-items/{item_id}/approve": _approve_item,
    "POST /drafts/{day}/discard": _discard,
    # events (switched off in this app: an accepted request answers 503)
    "GET /events": lambda env: Req("GET", "/events", also_ok=(503,)),
    # master data
    "GET /units": _get("/units"),
    "GET /categories": _get("/categories"),
    "POST /categories": lambda env: Req(
        "POST", "/categories", {"json": {"name": f"Category {next(env._days)}"}}
    ),
    # products
    "GET /products": _get("/products"),
    "POST /products": lambda env: Req(
        "POST", "/products", {"json": {"name": f"Oat milk {next(env._days)}", "kcal": 45}}
    ),
    "POST /products/match": lambda env: Req("POST", "/products/match", {"json": {"text": "skyr"}}),
    "GET /products/{product_id}": _get("/products/{product}"),
    "GET /products/{product_id}/versions": _get("/products/{product}/versions"),
    "POST /products/{product_id}/versions": _version,
    "GET /products/{product_id}/usage": _get("/products/{product}/usage"),
    "PATCH /products/{product_id}": lambda env: Req(
        "PATCH", f"/products/{env.product()['id']}", {"json": {"kcal": 64}}
    ),
    "DELETE /products/{product_id}": _delete_product,
    "GET /products/{product_id}/portions": _get("/products/{product}/portions"),
    "POST /products/{product_id}/portions": _add_portion,
    "PATCH /portions/{portion_id}": _patch_portion,
    "DELETE /portions/{portion_id}": _delete_portion,
    # proposals
    "GET /proposals": _get("/proposals"),
    "GET /proposals/{proposal_id}": _get("/proposals/{proposal}"),
    "POST /proposals/{proposal_id}/approve": _decide("approve"),
    "POST /proposals/{proposal_id}/reject": _decide("reject"),
    "PATCH /proposals/{proposal_id}": lambda env: Req(
        "PATCH", f"/proposals/{env.proposal()}", {"json": {"changes": {"kcal": 11}}}
    ),
    # recipes
    "GET /recipes": _get("/recipes"),
    "POST /recipes": lambda env: Req("POST", "/recipes", {"json": {"name": "Porridge"}}),
    "GET /recipes/{recipe_id}": _get("/recipes/{recipe}"),
    "PATCH /recipes/{recipe_id}": lambda env: Req(
        "PATCH", f"/recipes/{env.ids['recipe']}", {"json": {"default_servings": 3}}
    ),
    "PUT /recipes/{recipe_id}/ingredients": lambda env: Req(
        "PUT",
        f"/recipes/{env.ids['recipe']}/ingredients",
        {
            "json": {
                "ingredients": [{"product_id": env.ids["product"], "amount": 150, "unit_code": "g"}]
            }
        },
    ),
    "POST /recipes/{recipe_id}/batches": lambda env: Req(
        "POST", f"/recipes/{env.ids['recipe']}/batches", {"json": {"servings": 2}}
    ),
    "GET /batches/{batch_id}": _get("/batches/{batch}"),
    # reports
    "POST /reports/{name}/snapshots": lambda env: Req("POST", "/reports/checkup/snapshots"),
    "GET /reports/snapshots": _get("/reports/snapshots"),
    "GET /reports/snapshots/{snapshot_id}": _get("/reports/snapshots/{snapshot}"),
    "POST /reports/snapshots/{snapshot_id}/assess": _assess,
    "DELETE /reports/snapshots/{snapshot_id}": _delete_snapshot,
    "GET /reports": _get("/reports"),
    "POST /reports/{name}/render": lambda env: Req("POST", "/reports/checkup/render"),
    "GET /reports/checkup": _get("/reports/checkup"),
    # settings
    "GET /settings": _get("/settings"),
    "PUT /settings": lambda env: Req("PUT", "/settings", {"json": {"data": env.settings}}),
    "GET /settings/rules": _get("/settings/rules"),
    "PUT /settings/rules": lambda env: Req(
        "PUT", "/settings/rules", {"json": {"when": "rolls", "then": "two"}}
    ),
    "DELETE /settings/rules/{name}": _rule,
    "GET /settings/versions": _get("/settings/versions"),
    "GET /target-bands": _get("/target-bands"),
    "POST /target-bands": _band,
    # tenant
    "GET /backup/jobs": _get("/backup/jobs"),
    "GET /tenant": _get("/tenant"),
    "GET /tenant/users": _get("/tenant/users"),
    "POST /tenant/users": _new_user,
    # weight and body
    "GET /weight": _get("/weight"),
    "POST /weight": lambda env: Req(
        "POST", "/weight", {"json": {"measured_at": env.stamp(), "kg": 80.1}}
    ),
    "DELETE /weight/{entry_id}": _weight,
    "GET /body-measurements": _get("/body-measurements"),
    "POST /body-measurements": lambda env: Req(
        "POST",
        "/body-measurements",
        {"json": {"measured_at": env.stamp(), "waist_cm": 81}},
    ),
    "DELETE /body-measurements/{row_id}": _body,
}


def send(env: Env, req: Req, headers: dict[str, str]) -> Any:
    return env.client.request(req.method, API + req.path, headers=headers, **req.kwargs)
