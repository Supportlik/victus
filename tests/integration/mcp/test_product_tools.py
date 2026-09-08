"""T-MCP-008/009: captures_open scope and product_update via the tool registry."""

from __future__ import annotations

from typing import Any, cast

from victus.application.tenant_context import TenantContext
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
