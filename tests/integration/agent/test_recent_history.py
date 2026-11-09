"""T-AGT-122…125: what a day session knows about the person's habits, and what it costs (#78).

A drafting session gets a compact "recently logged" block (products and one-offs logged around
the day), the tools to look further (`product_usage`), the barcode lookup only when the server
offers it, and prompt caching that books cache reads and writes at their own price.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from victus.agent import runner as runner_mod
from victus.agent.model import ScriptedModelClient, ScriptedTurn
from victus.agent.pricing import turn_cost_usd
from victus.agent.worker import Worker
from victus.application.errors import NotFound
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import agent as agent_uc
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases import rules as rules_uc
from victus.application.use_cases._base import UowFactory
from victus.config.server import AgentConfig, ModelPricing, ServerConfig
from victus.infrastructure.storage.memory import InMemoryBlobStorage
from victus.mcp.tools import WORKER_TOOLS, ToolContext, dispatch

from .conftest import DAY
from .test_cov_runner import SETTINGS


def _log(tc: ToolContext, factory: UowFactory, ctx: TenantContext, day: Any, **item: Any) -> None:
    try:
        day_uc.GetDay(factory, ctx).execute(day)
    except NotFound:
        day_uc.CreateDay(factory, ctx).execute(day, reliable=True)
    dispatch(tc, "line_item_create", {"date": day.isoformat(), "meal": "Lunch", **item})


def _one_off(factory: UowFactory, ctx: TenantContext, name: str) -> int:
    with factory(ctx) as uow:
        item = uow.products.add_ad_hoc_item(
            name, reference_amount=100.0, reference_unit="g", kcal=320.0, protein=24.0
        )
        uow.commit()
        return int(item.id)


@pytest.fixture
def history(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    make_tool_ctx: Any,
) -> dict[str, int]:
    tc = make_tool_ctx(alice)
    cheese = _one_off(factory, alice, "six thin slices of cheese")
    for back in (1, 3):
        _log(
            tc,
            factory,
            alice,
            DAY - timedelta(days=back),
            consumable_id=skyr,
            amount=1,
            unit_code="tub",
        )
    _log(tc, factory, alice, DAY - timedelta(days=5), consumable_id=skyr, amount=150)
    _log(tc, factory, alice, DAY - timedelta(days=2), consumable_id=cheese, amount=80)
    # the day itself and a day outside the window are not "recent"
    _log(tc, factory, alice, DAY, consumable_id=cheese, amount=10)
    _log(tc, factory, alice, DAY - timedelta(days=40), consumable_id=cheese, amount=10)
    return {"skyr": skyr, "cheese": cheese}


def test_t_agt_122_recently_logged_groups_products_and_one_offs(
    factory: UowFactory, alice: TenantContext, history: dict[str, int]
) -> None:
    """T-AGT-122: every consumable logged within the window around the day — catalogue products
    and one-offs alike — once, most frequent first, with its usual amount; the day itself and
    days outside the window are left out; the Markdown block names id, kind and amount."""
    view = agent_uc.GetRecentlyLogged(factory, alice).execute(DAY, days=14)
    assert [(i.consumable_id, i.kind, i.times, i.days) for i in view.items] == [
        (history["skyr"], "product", 3, 3),
        (history["cheese"], "ad_hoc", 1, 1),
    ]
    skyr = view.items[0]
    assert (skyr.usual_amount, skyr.usual_unit_code, skyr.usual_base_amount) == (1, "tub", 400)
    assert skyr.last_date == DAY - timedelta(days=1)

    text = agent_uc.recently_logged_markdown(view)
    assert text.startswith("## Recently logged")
    assert f"[{history['skyr']}] Skyr natural (product) — 3× on 3 day(s)" in text
    assert "usually 1 tub (400 g)" in text
    assert f"[{history['cheese']}] six thin slices of cheese (ad_hoc)" in text
    assert "usually 80 g" in text
    assert agent_uc.recently_logged_markdown(agent_uc.dto.RecentlyLogged(DAY, DAY, [])) == ""


def _worker(
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    blobs: InMemoryBlobStorage,
    model: ScriptedModelClient,
    tmp_path: Any,
) -> Worker:
    return Worker(
        config,
        session_factory,
        model_factory=lambda _cfg: model,
        blobs=blobs,
        heartbeat_path=tmp_path / "alive",
    )


def _texts(content: list[dict[str, Any]]) -> list[str]:
    return [str(b.get("text", "")) for b in content if b.get("type") == "text"]


def test_t_agt_123_first_message_carries_rules_then_history_then_the_day(
    factory: UowFactory,
    alice: TenantContext,
    history: dict[str, int],
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-123: the day session's first message holds the task, the user's rules, the
    recently-logged block and then the day context, in that order; the tools offered include
    `product_usage` but not the barcode lookup while it is switched off."""
    from victus.application.use_cases import settings as settings_uc

    settings_uc.PutSettings(factory, alice).execute(SETTINGS)
    rules_uc.UpsertRule(factory, alice).execute(
        rules_uc.RuleInput(when="bread rolls", then="take the bakery's site", scope="days")
    )
    capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(text="lunch: skyr", target_date=DAY)
    )
    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    model = ScriptedModelClient(turns=[ScriptedTurn(text="Nothing to draft.")])

    _worker(config, session_factory, blobs, model, tmp_path).run_once()

    texts = _texts(model.calls[0]["messages"][0]["content"])
    assert texts[0].startswith("# Task: draft")
    assert "bread rolls" in texts[1]
    assert texts[2].startswith("## Recently logged")
    assert texts[3].startswith("## Day context (JSON)")
    names = {t["name"] for t in model.calls[0]["tools"]}
    assert "product_usage" in names and "product_usage" in WORKER_TOOLS
    assert "product_lookup_ean" not in names and "product_lookup_ean" in WORKER_TOOLS


def test_t_agt_124_history_can_be_switched_off_or_fail_quietly(
    alice: TenantContext,
    history: dict[str, int],
    make_tool_ctx: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-AGT-124: `agent.recent_days: 0` leaves the block out; a history that cannot be read
    leaves it out instead of failing the session; with a lookup configured the session offers
    `product_lookup_ean`."""
    tc = make_tool_ctx(alice)
    assert runner_mod.recently_logged(tc, DAY, 0) == ""
    assert "Skyr natural" in runner_mod.recently_logged(tc, DAY, 14)

    def unreadable(*_a: Any, **_k: Any) -> Any:
        raise NotFound("gone")

    monkeypatch.setattr(agent_uc.GetRecentlyLogged, "execute", unreadable)
    assert runner_mod.recently_logged(tc, DAY, 14) == ""

    class Lookup:
        def by_ean(self, ean: str) -> None:
            return None

    tc.product_lookup = Lookup()
    assert "product_lookup_ean" in {t["name"] for t in runner_mod.session_tools(tc)}


def test_t_agt_125_cache_reads_and_writes_are_booked_at_their_price(
    factory: UowFactory,
    alice: TenantContext,
    skyr: int,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-125: a turn's cost adds cache writes at 1.25× and cache reads at 0.1× the input
    price (or the configured cache prices); the run's input tokens count cached input too,
    so the token budget still measures the context the model processed."""
    capture_uc.UploadCapture(factory, alice, blobs).execute(
        capture_uc.UploadInput(text="lunch: skyr", target_date=DAY)
    )
    run = agent_uc.QueueAgentRun(factory, alice).execute("historical")
    model = ScriptedModelClient(
        turns=[
            ScriptedTurn(
                text="Nothing to draft.",
                input_tokens=1_000,
                output_tokens=200,
                cache_creation_input_tokens=2_000,
                cache_read_input_tokens=10_000,
            )
        ]
    )
    _worker(config, session_factory, blobs, model, tmp_path).run_once()

    view = agent_uc.GetAgentRun(factory, alice).execute(run.id)
    assert view.input_tokens == 13_000 and view.output_tokens == 200
    assert view.cost_usd == pytest.approx(
        (1_000 * 5 + 200 * 25 + 2_000 * 6.25 + 10_000 * 0.5) / 1e6
    )

    priced = AgentConfig(
        pricing={
            "m": ModelPricing(input_per_mtok=4, cache_write_per_mtok=5, cache_read_per_mtok=0.2)
        }
    )
    cost = turn_cost_usd(
        priced, "m", 0, 0, cache_write_tokens=1_000_000, cache_read_tokens=1_000_000
    )
    assert cost == pytest.approx(5.2)
