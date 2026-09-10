"""T-MCP-008/009/013: captures_open scope, product_update and portion tools via the registry."""

from __future__ import annotations

import dataclasses
from typing import Any, cast

from victus.application.tenant_context import SCOPE_READ, SCOPE_WRITE, TenantContext
from victus.application.use_cases import captures as capture_uc
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
