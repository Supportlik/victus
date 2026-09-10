"""T-MCP-008/009/013/014/015/016: captures_open, product_update, portions, versions, density."""

from __future__ import annotations

import dataclasses
from typing import Any, cast

from victus.application.tenant_context import SCOPE_READ, SCOPE_WRITE, TenantContext
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import products as products_uc
from victus.application.use_cases import proposals as prop_uc
from victus.application.use_cases._base import UowFactory
from victus.infrastructure.storage.memory import InMemoryBlobStorage
from victus.mcp.tools import ToolContext, dispatch


def test_captures_open_scope_and_product_update(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    blobs = InMemoryBlobStorage()
    capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(text="label: 70 kcal, 12 g protein per 100 g", product_id=skyr)
    )
    capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(text="lunch: skyr", target_date=None)
    )
    day_rows = cast(list[Any], dispatch(tool_ctx, "captures_open", {"scope": "day"}))
    prod_rows = cast(list[Any], dispatch(tool_ctx, "captures_open", {"scope": "product"}))
    all_rows = cast(list[Any], dispatch(tool_ctx, "captures_open", {"scope": "all"}))
    assert len(prod_rows) == 1 and prod_rows[0]["product_id"] == skyr
    assert all(r["product_id"] is None for r in day_rows)
    assert len(all_rows) == len(day_rows) + 1

    updated = cast(
        dict[str, Any],
        dispatch(
            tool_ctx,
            "product_update",
            {"product_id": skyr, "kcal": 70, "protein": 12, "source": "label photo, capture x"},
        ),
    )
    assert updated["kcal"] == 70 and updated["verified"] is False
    assert updated["source"] == "label photo, capture x"

    marked = cast(
        dict[str, Any],
        dispatch(tool_ctx, "capture_mark", {"id": prod_rows[0]["id"], "status": "processed"}),
    )
    assert marked["status"] == "processed"


def test_t_mcp_013_portion_update_and_delete_propose_without_approve(
    tool_ctx: ToolContext, skyr: int
) -> None:
    """T-MCP-013: an actor holding only `write` drafts both operations; a person applies them."""
    writer = dataclasses.replace(
        tool_ctx,
        ctx=dataclasses.replace(
            tool_ctx.ctx, token_id="tok_write", scopes=frozenset({SCOPE_READ, SCOPE_WRITE})
        ),
    )
    piece = cast(
        dict[str, Any],
        dispatch(
            tool_ctx,
            "portion_create",
            {"product_id": skyr, "unit_code": "piece", "label": "piece", "amount": 400},
        ),
    )
    tub = cast(dict[str, Any], dispatch(tool_ctx, "product_get", {"id": skyr}))["portions"][0]

    corrected = cast(
        dict[str, Any],
        dispatch(writer, "portion_update", {"portion_id": piece["id"], "amount": 380}),
    )
    assert corrected["pending_review"] is True and corrected["status"] == "pending"
    assert corrected["changes"]["portions"] == [
        {"op": "update", "portion_id": piece["id"], "amount": 380}
    ]
    assert corrected["portion_plan"][0]["current"]["amount"] == 400

    proposed = cast(
        dict[str, Any],
        dispatch(
            writer,
            "portion_delete",
            {"portion_id": piece["id"], "reason": "duplicates the tub of the same size"},
        ),
    )
    assert proposed["pending_review"] is True
    assert proposed["portion_plan"][0]["op"] == "delete"
    assert proposed["portion_plan"][0]["blocked"] is None

    # The same calls with `approve` write straight through, as a person's own edit does.
    applied = cast(
        dict[str, Any],
        dispatch(tool_ctx, "portion_update", {"portion_id": tub["id"], "amount": 450}),
    )
    assert applied["amount"] == 450 and "pending_review" not in applied
    assert dispatch(tool_ctx, "portion_delete", {"portion_id": piece["id"], "reason": "twin"}) == {
        "deleted": piece["id"]
    }


def test_t_mcp_014_product_version_create_proposes_without_approve(
    tool_ctx: ToolContext, skyr: int
) -> None:
    """T-MCP-014: reading a changed label is drafting, so the tool degrades like the rest.

    Correcting the current version instead would rewrite what the days before the change
    already counted, which is why this had no honest form without `approve` at all.
    """
    writer = dataclasses.replace(
        tool_ctx,
        ctx=dataclasses.replace(
            tool_ctx.ctx, token_id="tok_write", scopes=frozenset({SCOPE_READ, SCOPE_WRITE})
        ),
    )
    proposed = cast(
        dict[str, Any],
        dispatch(
            writer,
            "product_version_create",
            {
                "id": skyr,
                "valid_from": "2026-06-01",
                "changes": {"kcal": 66},
                "rationale": "the new label says 66",
            },
        ),
    )
    assert proposed["pending_review"] is True and proposed["status"] == "pending"
    assert proposed["kind"] == "version" and proposed["product_id"] == skyr
    assert proposed["changes"] == {"kcal": 66, "valid_from": "2026-06-01"}
    assert proposed["rationale"] == "the new label says 66"
    assert cast(dict[str, Any], dispatch(tool_ctx, "product_get", {"id": skyr}))["kcal"] == 63

    # The same call with `approve` opens the version, as a person's own edit does.
    opened = cast(
        dict[str, Any],
        dispatch(
            tool_ctx,
            "product_version_create",
            {"id": skyr, "valid_from": "2026-06-01", "changes": {"kcal": 66}},
        ),
    )
    assert "pending_review" not in opened and opened["valid_from"] == "2026-06-01"
    versions = cast(dict[str, Any], dispatch(tool_ctx, "product_versions", {"id": skyr}))
    assert [v["kcal"] for v in versions["versions"]] == [63, 66]


def test_t_mcp_015_a_portion_proposal_for_a_unit_that_is_not_one_says_so(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-MCP-015: the incident of issue #25, at the surface it arrived on.

    Four calls asked for `piece_s`…`piece_xl` — the size of an egg written where the unit
    belongs. They came back pending with nothing wrong, and every approval then failed.
    """
    writer = dataclasses.replace(
        tool_ctx,
        ctx=dataclasses.replace(
            tool_ctx.ctx, token_id="tok_write", scopes=frozenset({SCOPE_READ, SCOPE_WRITE})
        ),
    )
    proposed = cast(
        dict[str, Any],
        dispatch(
            writer,
            "portion_create",
            {"product_id": skyr, "unit_code": "piece_s", "label": "S (48 g)", "amount": 48},
        ),
    )
    assert proposed["pending_review"] is True and proposed["status"] == "pending"
    blocked = proposed["portion_plan"][0]["blocked"]
    assert "there is no unit 'piece_s'" in blocked
    assert "a size belongs in the portion's label" in blocked and "'piece'" in blocked

    # The unit the code was invented for, with the size where it belongs, is applicable.
    ok = cast(
        dict[str, Any],
        dispatch(
            writer,
            "portion_create",
            {"product_id": skyr, "unit_code": "piece", "label": "S (48 g)", "amount": 48},
        ),
    )
    assert ok["portion_plan"][0]["blocked"] is None
    prop_uc.DecideProposal(factory, alice).execute(ok["id"], approve=True)
    portions = cast(dict[str, Any], dispatch(tool_ctx, "product_get", {"id": skyr}))["portions"]
    assert [(p["unit_code"], p["label"]) for p in portions] == [
        ("tub", "tub"),
        ("piece", "S (48 g)"),
    ]


def test_t_mcp_016_a_density_is_visible_to_the_agent(
    tool_ctx: ToolContext, factory: UowFactory, alice: TenantContext, skyr: int
) -> None:
    """T-MCP-016: the agent reads products here, so a density it cannot see does not exist.

    Without it there is no way to tell a product whose grams-to-millilitres conversion is
    safe from one whose is not, and no current value to hold a proposed one against.
    """
    syrup = products_uc.CreateProduct(factory, alice).execute(
        products_uc.ProductInput(
            name="Maple syrup", reference_unit="ml", density_g_per_ml=1.32, kcal=260
        )
    )
    fetched = cast(dict[str, Any], dispatch(tool_ctx, "product_get", {"id": syrup.id}))
    assert fetched["density_g_per_ml"] == 1.32
    assert (
        cast(dict[str, Any], dispatch(tool_ctx, "product_get", {"id": skyr}))["density_g_per_ml"]
        is None
    ), "and a product without one says so, rather than leaving it out"

    found = cast(dict[str, Any], dispatch(tool_ctx, "product_search", {"q": "syrup"}))
    hit = next(p for p in found["products"] if p["id"] == syrup.id)
    assert (hit["reference_unit"], hit["density_g_per_ml"]) == ("ml", 1.32)

    proposed = cast(
        dict[str, Any],
        dispatch(
            tool_ctx,
            "product_propose",
            {
                "product_id": skyr,
                "changes": {"density_g_per_ml": 1.04},
                "source": "label photo",
            },
        ),
    )
    assert proposed["changes"] == {"density_g_per_ml": 1.04}
    assert proposed["current"] == {"density_g_per_ml": None}, "what the reader compares against"
