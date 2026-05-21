"""Model pricing helpers.

Pricing is intentionally user-configured. The application records token usage
for every model call, then applies the price snapshot from the model config if
the user provided one.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


PRICING_FIELDS = {
    "input_price_per_million",
    "cached_input_price_per_million",
    "output_price_per_million",
    "currency",
    "pricing_note",
}


def parse_optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pricing_snapshot_from_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    config = config or {}
    input_price = parse_optional_float(config.get("input_price_per_million"))
    cached_input_price = parse_optional_float(config.get("cached_input_price_per_million"))
    output_price = parse_optional_float(config.get("output_price_per_million"))
    currency = str(config.get("currency") or "CNY").strip() or "CNY"
    note = str(config.get("pricing_note") or "").strip()
    return {
        "input_price_per_million": input_price,
        "cached_input_price_per_million": cached_input_price,
        "output_price_per_million": output_price,
        "currency": currency,
        "pricing_note": note,
        "configured": input_price is not None and output_price is not None,
    }


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    pricing_snapshot: Optional[Dict[str, Any]],
    cached_input_tokens: int = 0,
) -> Optional[float]:
    pricing = pricing_snapshot or {}
    input_price = parse_optional_float(pricing.get("input_price_per_million"))
    cached_input_price = parse_optional_float(pricing.get("cached_input_price_per_million"))
    output_price = parse_optional_float(pricing.get("output_price_per_million"))
    if input_price is None or output_price is None:
        return None
    cached_tokens = max(0, min(int(cached_input_tokens or 0), int(input_tokens or 0)))
    uncached_tokens = max(0, int(input_tokens or 0) - cached_tokens)
    if cached_input_price is None:
        cached_input_price = input_price
    return (uncached_tokens / 1_000_000 * input_price) + (
        cached_tokens / 1_000_000 * cached_input_price
    ) + (
        int(output_tokens or 0) / 1_000_000 * output_price
    )
