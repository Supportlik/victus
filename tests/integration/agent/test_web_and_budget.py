"""T-AGT-129…132, T-AGT-134: what a day session can reach, what one day may spend, and a
scripted replay of the case in #78.

The replay is scripted: no model is called. It shows that the harness hands a session what it
needs — the intended products on top of one search per item, the one-off named after the food,
an open question where a rule or a barcode cannot be followed — not how a real model decides.
Every name is synthetic ("Bakery Valdrik", "Brand Y", "Brand Z", "Brand W").
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from victus.agent import runner as runner_mod
from victus.agent.model import ScriptedModelClient, ScriptedTurn
from victus.agent.worker import Worker
from victus.application.tenant_context import TenantContext
from victus.application.use_cases import agent as agent_uc
from victus.application.use_cases import captures as capture_uc
from victus.application.use_cases import day_logs as day_uc
from victus.application.use_cases import products as products_uc
from victus.application.use_cases import rules as rules_uc
from victus.application.use_cases import settings as settings_uc
from victus.application.use_cases._base import UowFactory
from victus.config.server import AgentWeb, ServerConfig
from victus.infrastructure.storage.memory import InMemoryBlobStorage
from victus.mcp.tools import ToolContext

from .conftest import DAY
from .test_cov_runner import SETTINGS


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


def _with_web(config: ServerConfig, **web: Any) -> ServerConfig:
    agent = config.agent.model_copy(update={"web": AgentWeb(**web)})
    return config.model_copy(update={"agent": agent})


def _capture(factory: UowFactory, ctx: TenantContext, blobs: InMemoryBlobStorage, text: str) -> str:
    return (
        capture_uc.UploadCapture(factory, ctx, blobs)
        .execute(capture_uc.UploadInput(text=text, target_date=DAY))
        .id
    )


def _item(capture_id: str, raw: str, chosen: int | None, **over: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "raw_text": raw,
        "candidates": [],
        "chosen_consumable_id": chosen,
        "quantity": 100,
        "unit_code": "g",
        "estimated": chosen is None,
        "quantity_estimated": False,
        "confidence": 0.8,
        "rationale": "from the capture",
        "source_kind": "text",
        "source_capture_id": capture_id,
    }
    item.update(over)
    return item


def _run_id(model: ScriptedModelClient) -> str:
    """The run id as the task prompt names it, read the way a model would."""
    task = model.calls[0]["messages"][0]["content"][0]["text"]
    return str(task.split(" for run ", 1)[1].split("\n", 1)[0]).strip()


def test_t_agt_129_a_website_rule_without_web_becomes_an_open_question(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-129: with `agent.web` off (the default) the session is told it has no web and that
    a rule naming a website goes into `open_questions`; the system prompt says the same; no web
    tool is offered; the draft's open question reaches the day thread."""
    settings_uc.PutSettings(factory, alice).execute(SETTINGS)
    rules_uc.UpsertRule(factory, alice).execute(
        rules_uc.RuleInput(
            when="bread rolls", then="take the values from the bakery's website", scope="days"
        )
    )
    cap = _capture(factory, alice, blobs, "lunch: two bread rolls from Bakery X")
    agent_uc.QueueAgentRun(factory, alice).execute("historical")

    def draft(memo: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": memo["run_id"],
            "date": DAY.isoformat(),
            "source_captures": [cap],
            "meals": [
                {
                    "name": "Lunch",
                    "line_items": [
                        _item(
                            cap,
                            "two bread rolls from Bakery X",
                            None,
                            one_off_name="Bread roll (Bakery X)",
                            one_off_nutrition_per_100={"kcal": 270, "source": "estimate"},
                        )
                    ],
                }
            ],
            "open_questions": [
                "Your rule says to take bread rolls from the bakery's website; this session has "
                "no web access, so the values are an estimate."
            ],
        }

    model = ScriptedModelClient(
        turns=[ScriptedTurn(tool_calls=[("draft_create", draft)]), ScriptedTurn(text="Done.")]
    )

    def first_call(memo: dict[str, Any]) -> dict[str, Any]:
        memo["run_id"] = _run_id(model)
        return draft(memo)

    model.turns[0] = ScriptedTurn(tool_calls=[("draft_create", first_call)])
    outcome = _worker(config, session_factory, blobs, model, tmp_path).run_once()[0]

    task = model.calls[0]["messages"][0]["content"][0]["text"]
    assert "- Web: none. A user rule that names a website" in task
    assert "`open_questions`" in task and "- Barcodes: no lookup." in task
    assert "When a rule needs something you cannot do here" in model.calls[0]["system"]
    names = {t["name"] for t in model.calls[0]["tools"]}
    assert not names & {"web_search", "web_fetch"}
    day = outcome.days[0]
    assert day.outcome == "drafted" and day.draft is not None and day.draft["questions"] == 1
    assert "no web access" in day.questions[0]


def test_t_agt_130_web_tools_only_with_a_domain_list(
    alice: TenantContext, config: ServerConfig, make_tool_ctx: Any
) -> None:
    """T-AGT-130: `agent.web` on with allowed domains offers `web_search` and `web_fetch`,
    both confined to those domains and capped; on without a domain, or off, offers neither;
    a URL instead of a hostname is refused; the task names the domains and that only
    product names, brands and barcodes may be searched."""
    tc: ToolContext = make_tool_ctx(alice)
    on = _with_web(config, enabled=True, allowed_domains=["Bakery.Victus.Example.com"])
    tc.config = on
    tools = runner_mod.session_tools(tc)
    web = {t["name"]: t for t in tools if t.get("type", "").startswith("web_")}
    assert web["web_search"] == {
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": 5,
        "allowed_domains": ["bakery.victus.example.com"],
    }
    assert web["web_fetch"]["type"] == "web_fetch_20260209"
    assert web["web_fetch"]["allowed_domains"] == ["bakery.victus.example.com"]
    assert web["web_fetch"]["max_content_tokens"] == runner_mod.WEB_FETCH_MAX_CONTENT_TOKENS
    text = runner_mod.capabilities(tc)
    assert "limited to bakery.victus.example.com" in text
    assert "product names, brands and barcodes only" in text

    tc.config = _with_web(config, enabled=True, allowed_domains=[])
    assert runner_mod.web_tools(tc.config.agent.web) == []
    assert "- Web: none." in runner_mod.capabilities(tc)
    tc.config = config
    assert runner_mod.web_tools(config.agent.web) == []

    class Lookup:
        def by_ean(self, ean: str) -> None:
            return None

    tc.product_lookup = Lookup()
    assert "- Barcodes: `product_lookup_ean` looks an EAN up." in runner_mod.capabilities(tc)

    with pytest.raises(ValidationError, match="plain hostname"):
        AgentWeb(enabled=True, allowed_domains=["https://bakery.victus.example.com"])


def test_t_agt_131_a_paused_server_turn_is_continued_and_searches_are_booked(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-131: a turn that stops with `pause_turn` is sent back as it stands — the server's
    blocks echoed, no extra user message — and the session goes on; each web search the
    server ran is booked at `agent.web.usd_per_search` on top of the tokens."""
    _capture(factory, alice, blobs, "lunch: a bread roll from Bakery X")
    run = agent_uc.QueueAgentRun(factory, alice).execute("historical")
    blocks = [
        {
            "type": "server_tool_use",
            "id": "srvtoolu_1",
            "name": "web_search",
            "input": {"query": "Bakery X bread roll nutrition"},
        },
        {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": []},
    ]
    model = ScriptedModelClient(
        turns=[
            ScriptedTurn(
                server_blocks=blocks,
                stop_reason="pause_turn",
                web_search_requests=3,
                input_tokens=0,
                output_tokens=0,
            ),
            ScriptedTurn(text="Nothing to draft.", input_tokens=0, output_tokens=0),
        ]
    )
    web = _with_web(config, enabled=True, allowed_domains=["bakery.victus.example.com"])

    outcome = _worker(web, session_factory, blobs, model, tmp_path).run_once()[0]

    assert len(model.calls) == 2 and outcome.days[0].turns == 2
    resent = model.calls[1]["messages"]
    assert resent[-1] == {"role": "assistant", "content": blocks}, "no user message after it"
    view = agent_uc.GetAgentRun(factory, alice).execute(run.id)
    assert view.cost_usd == pytest.approx(0.03)


def test_t_agt_132_one_day_cannot_spend_the_whole_run(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-132: a day session that reaches `agent.budget.max_usd_per_day` stops with
    `budget_exceeded` and the next day of the same run is still drafted; with the cap unset
    only the run's budget applies."""
    for day in (DAY, DAY + timedelta(days=1)):
        capture_uc.UploadCapture(factory, alice, blobs).execute(
            capture_uc.UploadInput(text=f"lunch on {day.isoformat()}: skyr", target_date=day)
        )

    def turns() -> list[ScriptedTurn]:
        return [
            # 240k input tokens at 5 USD/M: 1.20 USD, over the day's 1.00, under the run's 2.00
            ScriptedTurn(tool_calls=[("product_search", {"q": "skyr"})], input_tokens=240_000),
            ScriptedTurn(text="Nothing to draft.", input_tokens=100),
            ScriptedTurn(text="Nothing to draft.", input_tokens=100),
        ]

    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    model = ScriptedModelClient(turns=turns())
    outcome = _worker(config, session_factory, blobs, model, tmp_path).run_once()[0]
    assert [(d.date, d.outcome) for d in outcome.days] == [
        (DAY, "budget_exceeded"),
        (DAY + timedelta(days=1), "no_draft"),
    ]
    assert outcome.days[0].error is not None and "per day" in outcome.days[0].error

    uncapped = config.model_copy(
        update={
            "agent": config.agent.model_copy(
                update={"budget": config.agent.budget.model_copy(update={"max_usd_per_day": None})}
            )
        }
    )
    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    model = ScriptedModelClient(turns=turns())
    again = _worker(uncapped, session_factory, blobs, model, tmp_path).run_once()[0]
    assert again.days[0].outcome == "no_draft" and again.days[0].turns == 2


# ── the case of #78, replayed with a synthetic catalogue ───────────────────────

BREAD = "Bakery Valdrik Fitnessbrötchen (wheat 95 % / rye 5 %, with quark)"
SPOKEN = (
    "110 g Fitnessbrötchen from Bakery Waldrik, 6 slices of Brand Y cheese (thin slices), "
    "1 pack Brand Z butter chicken, a Brand W frozen meal"
)
PHRASES = {
    "bread": "110 g Fitnessbrötchen from Bakery Waldrik",
    "cheese": "6 slices of Brand Y cheese (thin slices)",
    "chicken": "1 pack Brand Z butter chicken",
    "meal": "a Brand W frozen meal",
}


def test_t_agt_134_scripted_replay_of_the_issue_case(
    factory: UowFactory,
    alice: TenantContext,
    blobs: InMemoryBlobStorage,
    config: ServerConfig,
    session_factory: sessionmaker[Session],
    tmp_path: Any,
) -> None:
    """T-AGT-134: the anonymised case of #78 — a long bread name with a misheard bakery, a
    cheese logged days before, a one-off and a frozen meal with a legible barcode, a rule
    naming the bakery's website — replayed with a scripted model that searches each item
    once, verbatim, and takes the first product returned. Before, the field search found
    neither the bread nor the cheese by those phrases; now both are the first answer, the
    one-off is named after the food, and the barcode and the rule become open questions
    because lookup and web are off."""
    for name, brand, kcal in (
        (BREAD, None, 290),
        ("Bakery Valdrik rye bread", None, 230),
        ("Brötchen (plain wheat roll)", None, 270),
        ("Cheese slices (light)", "Brand Y", 270),
        ("Cheese slices (medium)", "Brand Q", 300),
        ("Cheddar block", "Brand Y", 400),
    ):
        products_uc.CreateProduct(factory, alice).execute(
            products_uc.ProductInput(name=name, brand=brand, kcal=kcal)
        )
    by_name = {p.name: p.id for p in products_uc.SearchProducts(factory, alice).execute("")}
    cheese = by_name["Cheese slices (light)"]
    earlier = DAY - timedelta(days=3)
    day_uc.CreateDay(factory, alice).execute(earlier, reliable=True)
    day_uc.AddLineItemOnDate(factory, alice).execute(
        earlier, "Lunch", day_uc.LineItemInput(consumable_id=cheese, amount=60, unit_code="g")
    )
    settings_uc.PutSettings(factory, alice).execute(SETTINGS)
    rules_uc.UpsertRule(factory, alice).execute(
        rules_uc.RuleInput(when="bread rolls", then="take the bakery's own website", scope="days")
    )
    cap = _capture(factory, alice, blobs, SPOKEN + ". Barcode on the meal: 2001234500018")

    # before: the field search the worker had to rely on finds nothing for these phrases
    for key in ("bread", "cheese"):
        assert products_uc.SearchProducts(factory, alice).execute(PHRASES[key]) == [], key

    agent_uc.QueueAgentRun(factory, alice).execute("historical")
    found: dict[str, list[dict[str, Any]]] = {}

    def search(key: str, previous: str | None) -> Any:
        def call(memo: dict[str, Any]) -> dict[str, Any]:
            if previous is not None:
                found[previous] = json.loads(memo["results"]["product_search"])["products"]
            return {"q": PHRASES[key], "on": DAY.isoformat()}

        return call

    def draft(memo: dict[str, Any]) -> dict[str, Any]:
        found["meal"] = json.loads(memo["results"]["product_search"])["products"]
        bread = found["bread"][0]
        top_cheese = found["cheese"][0]
        return {
            "run_id": _run_id(model),
            "date": DAY.isoformat(),
            "source_captures": [cap],
            "meals": [
                {
                    "name": "Lunch",
                    "line_items": [
                        _item(cap, PHRASES["bread"], bread["id"], quantity=110),
                        _item(cap, PHRASES["cheese"], top_cheese["id"], quantity=60),
                        _item(
                            cap,
                            PHRASES["chicken"],
                            None,
                            quantity=350,
                            one_off_nutrition_per_100={"kcal": 140, "source": "estimate"},
                        ),
                        _item(
                            cap,
                            PHRASES["meal"],
                            None,
                            quantity=400,
                            one_off_name="Frozen meal (Brand W)",
                            one_off_nutrition_per_100={"kcal": 150, "source": "estimate"},
                        ),
                    ],
                }
            ],
            "open_questions": [
                "The frozen meal shows barcode 2001234500018; it could be looked up, which "
                "this session cannot do.",
                "Your rule asks for the bakery's own website for bread rolls; this session "
                "has no web access, so the catalogue entry was used as it is.",
            ],
        }

    model = ScriptedModelClient(
        turns=[
            ScriptedTurn(tool_calls=[("product_search", search("bread", None))]),
            ScriptedTurn(tool_calls=[("product_search", search("cheese", "bread"))]),
            ScriptedTurn(tool_calls=[("product_search", search("meal", "cheese"))]),
            ScriptedTurn(tool_calls=[("draft_create", draft)]),
            ScriptedTurn(text="Drafted lunch."),
        ]
    )
    outcome = _worker(config, session_factory, blobs, model, tmp_path).run_once()[0]

    assert outcome.days[0].outcome == "drafted"
    assert found["bread"][0]["name"] == BREAD and found["bread"][0]["kind"] == "product"
    assert found["cheese"][0]["id"] == cheese, "the cheese logged three days before"
    task = model.calls[0]["messages"][0]["content"]
    assert any(f"[{cheese}] Cheese slices (light)" in b.get("text", "") for b in task)
    items = [li for m in day_uc.GetDay(factory, alice).execute(DAY).meals for li in m.line_items]
    assert [li.consumable_id for li in items[:2]] == [by_name[BREAD], cheese]
    names = [li.consumable_name for li in items[2:]]
    assert names == ["Brand Z butter chicken", "Frozen meal (Brand W)"]
    assert outcome.days[0].draft is not None and outcome.days[0].draft["questions"] == 2
