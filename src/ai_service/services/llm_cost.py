"""Turning token counts into money, from a price table that lives in the settings."""

from decimal import Decimal

from ai_service.core.config import ModelPrice
from ai_service.services.llm_types import Usage

_MILLION = Decimal(1_000_000)
_EIGHT_PLACES = Decimal("0.00000001")


def compute_cost(usage: Usage | None, price: ModelPrice | None) -> Decimal | None:
    """USD for one call. None when the usage or the price is unknown: never a made-up 0.

    cost = (new input x input price + output x output price
            + cache-read x cache-read price + cache-write x cache-write price) / 1,000,000
    """
    if usage is None or price is None:
        return None
    total = (
        usage.input_tokens * Decimal(str(price.input))
        + usage.output_tokens * Decimal(str(price.output))
        + usage.cache_read_tokens * Decimal(str(price.cache_read))
        + usage.cache_write_tokens * Decimal(str(price.cache_write))
    )
    return (total / _MILLION).quantize(_EIGHT_PLACES)
