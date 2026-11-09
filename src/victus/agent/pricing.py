"""Book the cost of a model turn from the configured per-model price table."""

from __future__ import annotations

from victus.config.server import AgentConfig

#: Anthropic's prompt-caching multipliers on the input price (5-minute cache).
CACHE_WRITE_FACTOR = 1.25
CACHE_READ_FACTOR = 0.1


def turn_cost_usd(
    cfg: AgentConfig,
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    price = cfg.pricing_for(model)
    write = (
        price.cache_write_per_mtok
        if price.cache_write_per_mtok is not None
        else price.input_per_mtok * CACHE_WRITE_FACTOR
    )
    read = (
        price.cache_read_per_mtok
        if price.cache_read_per_mtok is not None
        else price.input_per_mtok * CACHE_READ_FACTOR
    )
    return (
        input_tokens * price.input_per_mtok
        + output_tokens * price.output_per_mtok
        + cache_write_tokens * write
        + cache_read_tokens * read
    ) / 1_000_000.0
