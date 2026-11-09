"""T-MCP-245…246: `product_search` as the agent reads it, and one-offs through `draft_create`
(#78). Names are synthetic."""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Any, cast

import pytest

from victus.application.tenant_context import TenantContext
from victus.application.use_cases import products as products_uc
from victus.application.use_cases._base import UowFactory
from victus.mcp.tools import ToolContext, dispatch

BREAD = "Bakery Valdrik Fitnessbrötchen (wheat 95 % / rye 5 %)"


@pytest.mark.covers("mcp:product_search")
def test_t_mcp_245_product_search_returns_scored_products_and_one_offs(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-MCP-245: a verbatim phrase returns the variants tried and the intended product first,
    with `kind`, `score` and `matched_by`; a one-off comes back as `ad_hoc` with its values per
    100 g and its source; a barcode finds the product carrying it; `matches` still lists the
    matcher's candidates for the phrase without its quantity."""
    bread = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(name=BREAD, kcal=290, ean="2001234500018")
    )
    with factory(alice) as uow:
        one_off = uow.products.add_ad_hoc_item(
            "Butter chicken (Brand Z)",
            reference_amount=200.0,
            kcal=280.0,
            protein=24.0,
            origin_text="estimate from a similar dish",
        )
        uow.commit()
        one_off_id = one_off.id

    out = cast(
        dict[str, Any],
        dispatch(tool_ctx, "product_search", {"q": "110 g Fitnessbrötchen from Bakery Waldrik"}),
    )
    assert out["variants"][1] == "fitnessbroetchen bakery waldrik"
    first = out["products"][0]
    assert (first["id"], first["kind"]) == (bread.id, "product")
    assert 0 < first["score"] <= 1 and first["matched_by"][0] == "fitnessbroetchen"
    assert "portions" in first and first["kcal_per_100"] == 290

    chicken = cast(dict[str, Any], dispatch(tool_ctx, "product_search", {"q": "butter chicken"}))
    assert chicken["products"][0] == {
        "id": one_off_id,
        "name": "Butter chicken (Brand Z)",
        "brand": None,
        "kcal_per_100": 140.0,
        "protein_per_100": 12.0,
        "reference_unit": "g",
        "density_g_per_ml": None,
        "portions": [],
        "source": "estimate from a similar dish",
        "kind": "ad_hoc",
        "score": chicken["products"][0]["score"],
        "matched_by": ["butter", "chicken"],
    }

    by_code = cast(dict[str, Any], dispatch(tool_ctx, "product_search", {"q": "2001234500018"}))
    assert by_code["products"][0]["id"] == bread.id
    assert by_code["products"][0]["matched_by"] == ["ean"]

    porridge = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(name="Oat porridge", kcal=70)
    )
    cup = cast(dict[str, Any], dispatch(tool_ctx, "product_search", {"q": "1 cup oat porridge"}))
    assert (cup["matches"][0]["consumable_id"], cup["matches"][0]["tier"]) == (porridge.id, 1)
    # said exactly as named: the whole phrase is the better match than the shortened one
    honey = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(name="Skyr with honey", kcal=90)
    )
    said = cast(dict[str, Any], dispatch(tool_ctx, "product_search", {"q": "Skyr with honey"}))
    assert (said["matches"][0]["consumable_id"], said["matches"][0]["tier"]) == (honey.id, 1)
    assert dispatch(tool_ctx, "product_search", {"q": "skyr"})["products"][0]["id"] == skyr  # type: ignore[index]


@pytest.mark.covers("mcp:draft_create", "mcp:agent_run_start")
def test_t_mcp_246_draft_create_names_one_offs_and_files_the_returning_one(
    tool_ctx: ToolContext,
) -> None:
    """T-MCP-246: `draft_create` accepts `one_off_name`; the one-off carries that name, the
    same food on a second day is logged against it, and the second draft reports the
    product proposal it filed."""

    def draft(day: date, raw: str, name: str) -> dict[str, Any]:
        run = cast(
            dict[str, Any],
            dispatch(tool_ctx, "agent_run_start", {"mode": "manual", "dates": [day.isoformat()]}),
        )
        ctx = dataclasses.replace(tool_ctx, run_id=run["run_id"])
        written = cast(
            dict[str, Any],
            dispatch(
                ctx,
                "draft_create",
                {
                    "run_id": run["run_id"],
                    "date": day.isoformat(),
                    "source_captures": [],
                    "meals": [
                        {
                            "name": "Dinner",
                            "line_items": [
                                {
                                    "raw_text": raw,
                                    "candidates": [],
                                    "chosen_consumable_id": None,
                                    "one_off_name": name,
                                    "one_off_nutrition_per_100": {"kcal": 140, "source": "est."},
                                    "quantity": 350,
                                    "unit_code": "g",
                                    "estimated": True,
                                    "quantity_estimated": False,
                                    "confidence": 0.6,
                                    "rationale": "no catalogue entry",
                                    "source_kind": "text",
                                    "source_capture_id": "cap_test",
                                }
                            ],
                        }
                    ],
                },
            ),
        )
        dispatch(ctx, "agent_run_finish", {"run_id": run["run_id"], "summary": "one item"})
        return written

    first = draft(date(2026, 3, 10), "1 pack of the butter chicken", "Butter chicken (Brand Z)")
    item = first["day"]["meals"][0]["line_items"][0]
    assert item["consumable_name"] == "Butter chicken (Brand Z)"
    assert first["proposed_products"] == []

    second = draft(date(2026, 3, 12), "butter chicken again", "butter chicken (brand z)")
    again = second["day"]["meals"][0]["line_items"][0]
    assert again["consumable_id"] == item["consumable_id"]
    assert second["proposed_products"] == ["Butter chicken (Brand Z)"]
