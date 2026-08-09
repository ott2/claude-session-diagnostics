"""Model pricing and token-cost arithmetic.

Prices are USD per million tokens, first-party Anthropic API rates.
Cache multipliers are applied to the *input* rate:

    5-minute cache write   1.25x
    1-hour cache write     2.00x
    cache read             0.10x

Those multipliers are what make session-restart cost analysis possible: a token
served from a warm cache costs 0.1x, and the same token re-written into a cold
1-hour cache costs 2.0x -- a 20x swing on identical context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

# Multipliers applied to the base input rate.
CACHE_WRITE_5M = 1.25
CACHE_WRITE_1H = 2.00
CACHE_READ = 0.10

# The premium paid for re-writing context that a warm cache would have served.
# Used to price the cost of letting a session go cold.
COLD_PREMIUM_1H = CACHE_WRITE_1H - CACHE_READ  # 1.90
COLD_PREMIUM_5M = CACHE_WRITE_5M - CACHE_READ  # 1.15


@dataclass(frozen=True)
class Price:
    """USD per million tokens.

    Rates are not constant over time: a model can launch on an introductory
    price that later steps up. Costing a historical request at today's rate is
    wrong in both directions, so an intro rate carries the date it runs through
    and is selected by the request's own timestamp.
    """

    input: float
    output: float
    # Fast mode runs the same model at premium rates (Opus 5 / 4.8 only).
    fast_input: float | None = None
    fast_output: float | None = None
    # Promotional launch pricing, applied for requests dated on or before
    # `intro_until` (inclusive).
    intro_input: float | None = None
    intro_output: float | None = None
    intro_until: date | None = None

    def rates(self, at: datetime | date | None = None, fast: bool = False) -> tuple[float, float]:
        """(input, output) USD per million tokens for a request at time `at`."""
        if fast and self.fast_input and self.fast_output:
            return self.fast_input, self.fast_output
        if self.intro_input and self.intro_output and self.intro_until and at is not None:
            when = at.date() if isinstance(at, datetime) else at
            if when <= self.intro_until:
                return self.intro_input, self.intro_output
        return self.input, self.output


# Keyed by normalised model id. See `normalise_model`.
PRICES: dict[str, Price] = {
    "claude-fable-5": Price(10.0, 50.0),
    "claude-mythos-5": Price(10.0, 50.0),
    "claude-mythos-preview": Price(10.0, 50.0),
    "claude-opus-5": Price(5.0, 25.0, fast_input=10.0, fast_output=50.0),
    "claude-opus-4-8": Price(5.0, 25.0, fast_input=10.0, fast_output=50.0),
    "claude-opus-4-7": Price(5.0, 25.0),
    "claude-opus-4-6": Price(5.0, 25.0),
    "claude-opus-4-5": Price(5.0, 25.0),
    "claude-opus-4-1": Price(15.0, 75.0),
    "claude-opus-4-0": Price(15.0, 75.0),
    # Launch promotion: $2/$10 through 2026-08-31, $3/$15 thereafter.
    "claude-sonnet-5": Price(
        3.0, 15.0, intro_input=2.0, intro_output=10.0,
        intro_until=date(2026, 8, 31),
    ),
    "claude-sonnet-4-6": Price(3.0, 15.0),
    "claude-sonnet-4-5": Price(3.0, 15.0),
    "claude-sonnet-4-0": Price(3.0, 15.0),
    "claude-haiku-4-5": Price(1.0, 5.0),
    "claude-3-5-haiku": Price(0.80, 4.0),
    "claude-3-haiku": Price(0.25, 1.25),
}

# Trailing date snapshots (`-20251001`) and context-window / deployment suffixes
# (`[1m]`, `-fast`) are stripped before lookup.
_DATE_SUFFIX = re.compile(r"-\d{8}$")
_BRACKET_SUFFIX = re.compile(r"\[[^\]]*\]$")


def normalise_model(model: str | None) -> str | None:
    """Reduce a raw log model string to a pricing-table key.

    Returns None for synthetic entries (`<synthetic>`), which represent
    client-side error messages rather than billed API calls.
    """
    if not model:
        return None
    m = model.strip()
    if m.startswith("<"):  # "<synthetic>"
        return None
    m = m.removeprefix("anthropic.")  # Amazon Bedrock provider prefix
    m = _BRACKET_SUFFIX.sub("", m)  # "claude-opus-5[1m]"
    m = m.removesuffix("-fast")
    m = _DATE_SUFFIX.sub("", m)
    return m


def price_for(model: str | None) -> Price | None:
    key = normalise_model(model)
    if key is None:
        return None
    if key in PRICES:
        return PRICES[key]
    # Unknown but plausibly a new snapshot of a known family: fall back to the
    # longest known key that prefixes it, so a new dated release still prices.
    candidates = [k for k in PRICES if key.startswith(k)]
    if candidates:
        return PRICES[max(candidates, key=len)]
    return None


def cost(
    model: str | None,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_write_5m: int = 0,
    cache_write_1h: int = 0,
    cache_read: int = 0,
    fast: bool = False,
    at: datetime | date | None = None,
) -> float:
    """USD cost of a single API request's token usage.

    `at` is the request's timestamp, used to pick promotional rates that were in
    force when it ran. Omitting it falls back to standard rates.

    Unknown or synthetic models cost 0.0 -- they are surfaced separately by the
    parser rather than silently guessed at.
    """
    p = price_for(model)
    if p is None:
        return 0.0
    rate_in, rate_out = p.rates(at, fast)
    per_token_in = rate_in / 1_000_000
    per_token_out = rate_out / 1_000_000
    return (
        input_tokens * per_token_in
        + output_tokens * per_token_out
        + cache_write_5m * per_token_in * CACHE_WRITE_5M
        + cache_write_1h * per_token_in * CACHE_WRITE_1H
        + cache_read * per_token_in * CACHE_READ
    )


def cold_start_premium(
    model: str | None,
    cache_write_1h: int,
    cache_write_5m: int = 0,
    at: datetime | date | None = None,
) -> float:
    """USD paid above what a warm cache read would have cost for the same tokens.

    This is the marginal price of having let the cache expire: those tokens were
    already known to the model once, and are being re-written at 2.0x (1h) or
    1.25x (5m) instead of being read back at 0.1x.
    """
    p = price_for(model)
    if p is None:
        return 0.0
    rate_in, _ = p.rates(at)
    per_token_in = rate_in / 1_000_000
    return (
        cache_write_1h * per_token_in * COLD_PREMIUM_1H
        + cache_write_5m * per_token_in * COLD_PREMIUM_5M
    )
