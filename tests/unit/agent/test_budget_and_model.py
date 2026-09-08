"""T-AGT-007: budget arithmetic, pricing and the scripted model client."""

from __future__ import annotations

from victus.agent.budget import Budget
from victus.agent.model import ScriptedModelClient, ScriptedTurn
from victus.agent.pricing import turn_cost_usd
from victus.agent.runner import load_prompts
from victus.config.server import AgentBudget, AgentConfig


def test_budget_charges_and_reports_the_first_limit_crossed() -> None:
    b = Budget.from_config(
        AgentBudget(max_input_tokens=1000, max_output_tokens=100, max_usd_per_run=1.0)
    )
    assert b.exceeded is None
    b.charge(input_tokens=999, output_tokens=50, usd=0.5)
    assert b.exceeded is None
    b.charge(input_tokens=1)
    assert b.exceeded is not None and "input tokens" in b.exceeded
    assert b.snapshot()["input_tokens"] == 1000


def test_budget_image_reservation() -> None:
    b = Budget.from_config(AgentBudget(max_images_per_run=3))
    assert b.take_images(2) == 2
    assert b.take_images(5) == 1
    assert b.take_images(1) == 0


def test_pricing_uses_the_configured_table_and_a_default() -> None:
    cfg = AgentConfig()
    assert turn_cost_usd(cfg, "claude-opus-5", 1_000_000, 0) == 5.0
    assert turn_cost_usd(cfg, "claude-sonnet-5", 0, 1_000_000) == 10.0
    assert turn_cost_usd(cfg, "unknown-model", 1_000_000, 1_000_000) == 30.0


def test_scripted_client_replays_turns_and_exposes_tool_results() -> None:
    client = ScriptedModelClient(
        turns=[
            ScriptedTurn(tool_calls=[("product_search", {"q": "skyr"})]),
            ScriptedTurn(
                tool_calls=[("day_get", lambda memo: {"date": memo["results"]["product_search"]})]
            ),
            ScriptedTurn(text="done"),
        ]
    )
    first = client.create(system="s", messages=[{"role": "user", "content": "x"}], tools=[])
    assert first.stop_reason == "tool_use" and first.tool_uses[0].name == "product_search"
    history = [
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": first.content_params},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": first.tool_uses[0].id,
                    "content": "2026-03-10",
                }
            ],
        },
    ]
    second = client.create(system="s", messages=history, tools=[])
    assert second.tool_uses[0].input == {"date": "2026-03-10"}
    third = client.create(system="s", messages=history, tools=[])
    assert third.stop_reason == "end_turn" and third.text == "done"
    assert client.create(system="s", messages=history, tools=[]).text == "(script exhausted)"


def test_prompts_load_with_a_stable_version() -> None:
    p = load_prompts()
    assert "never approve" in p.system.lower() or "never approves" in p.system.lower()
    assert "{run_id}" in p.capture_to_draft and "{date}" in p.capture_to_draft
    assert len(p.version) == 12
