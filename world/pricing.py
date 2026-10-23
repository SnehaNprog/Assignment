"""Model prices in US dollars per million tokens (October 2026).

Check https://www.anthropic.com/pricing before you rely on these. The fake
model's token counts are estimates (characters / 4), clearly not real usage.
"""
from __future__ import annotations

PRICES = {
    #                     input   output  cache read
    "claude-haiku-5-5":  (0.10,   0.50,   0.01),
    "claude-sonnet-5-5": (2.00,  10.00,   0.20),
    "claude-opus-5-5":   (4.00,  20.00,   0.20),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0) -> float:
    price_in, price_out, price_cache = PRICES.get(model, PRICES["claude-haiku-5-5"])
    return (input_tokens * price_in + output_tokens * price_out + cache_read_tokens * price_cache) / 1_000_000
