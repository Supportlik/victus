"""T-MCP-241…244: barcode lookup (``product_lookup_ean``, ``agent.lookup.ean``, #78).

The tool runs against a fake lookup port; the Open Food Facts adapter itself is tested in
``tests/unit/infrastructure/test_openfoodfacts.py`` without network.
"""

from __future__ import annotations

import dataclasses

import pytest

from victus.application.ports.product_lookup import LookedUpProduct, ProductLookupError
from victus.config.server import ServerConfig
from victus.infrastructure.lookup.openfoodfacts import OpenFoodFactsLookup
from victus.mcp.server import product_lookup
from victus.mcp.tools import ToolContext, ToolError, dispatch

FROZEN_MEAL = LookedUpProduct(
    ean="4000000000017",
    name="Pasta bake",
    brand="Brand W",
    reference_unit="g",
    kcal=142.0,
    protein=6.1,
    carbs=17.0,
    fat=5.2,
    fiber=1.4,
    salt=0.9,
    quantity="400 g",
    pack_amount=400.0,
    serving_size=None,
    source="Open Food Facts, EAN 4000000000017",
    source_url="https://world.openfoodfacts.org/product/4000000000017",
)


class FakeLookup:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.asked: list[str] = []

    def by_ean(self, ean: str) -> LookedUpProduct | None:
        self.asked.append(ean)
        if self.fail:
            raise ProductLookupError("timed out")
        return FROZEN_MEAL if ean == FROZEN_MEAL.ean else None


@pytest.mark.covers("mcp:product_lookup_ean")
def test_t_mcp_241_lookup_returns_label_values_and_source(tool_ctx: ToolContext) -> None:
    """T-MCP-241: with a lookup configured, a barcode (spaces allowed) comes back with values
    per 100 g, the pack size and a source the agent can hand to product_create."""
    fake = FakeLookup()
    tc = dataclasses.replace(tool_ctx, product_lookup=fake)
    found = dispatch(tc, "product_lookup_ean", {"ean": "4 000000 000017"})
    assert isinstance(found, dict)
    assert found["name"] == "Pasta bake" and found["kcal"] == 142.0
    assert found["pack_amount"] == 400.0
    assert found["source"].startswith("Open Food Facts")
    assert fake.asked == ["4000000000017"]


@pytest.mark.covers("mcp:product_lookup_ean")
def test_t_mcp_242_lookup_errors_are_typed(tool_ctx: ToolContext) -> None:
    """T-MCP-242: an unknown barcode is NotFound, a malformed one ValidationFailed, a failing
    service ExternalServiceError — never a crash, and the model can read each."""
    tc = dataclasses.replace(tool_ctx, product_lookup=FakeLookup())
    with pytest.raises(ToolError) as unknown:
        dispatch(tc, "product_lookup_ean", {"ean": "4000000000024"})
    assert unknown.value.code == "NotFound"
    with pytest.raises(ToolError) as malformed:
        dispatch(tc, "product_lookup_ean", {"ean": "12ab"})
    assert malformed.value.code == "ValidationFailed"
    failing = dataclasses.replace(tool_ctx, product_lookup=FakeLookup(fail=True))
    with pytest.raises(ToolError) as down:
        dispatch(failing, "product_lookup_ean", {"ean": FROZEN_MEAL.ean})
    assert down.value.code == "ExternalServiceError" and "timed out" in down.value.message


@pytest.mark.covers("mcp:product_lookup_ean")
def test_t_mcp_243_lookup_switched_off_says_so(tool_ctx: ToolContext) -> None:
    """T-MCP-243: with ``agent.lookup.ean`` off (the default) the tool answers LookupDisabled
    and tells the agent to raise an open question instead of estimating silently."""
    assert tool_ctx.product_lookup is None
    with pytest.raises(ToolError) as off:
        dispatch(tool_ctx, "product_lookup_ean", {"ean": FROZEN_MEAL.ean})
    assert off.value.code == "LookupDisabled" and "open_questions" in off.value.message


def test_t_mcp_244_config_switches_the_adapter_on(config: ServerConfig) -> None:
    """T-MCP-244: the tool context gets the Open Food Facts adapter only when the flag is on."""
    assert product_lookup(config) is None
    on = config.model_copy(
        update={
            "agent": config.agent.model_copy(
                update={"lookup": config.agent.lookup.model_copy(update={"ean": True})}
            )
        }
    )
    assert isinstance(product_lookup(on), OpenFoodFactsLookup)
