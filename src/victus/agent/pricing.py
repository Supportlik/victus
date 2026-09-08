"""Book the cost of a model turn from the configured per-model price table."""

from __future__ import annotations

from victus.config.server import AgentConfig


def turn_cost_usd(cfg: AgentConfig, model: str, input_tokens: int, output_tokens: int) -> float:
    price = cfg.pricing_for(model)
    return (
        input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok
    ) / 1_000_000.0
