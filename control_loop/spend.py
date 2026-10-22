"""Dollar cost of Inspect model usage. Framework-agnostic: takes an Inspect ModelUsage (or a whole
EvalLog, header-only is enough) and prices it from the table below. No API calls.

Inspect 0.3.263 reports cached prompt tokens apart from `input_tokens`: `input_tokens_cache_read`
and `input_tokens_cache_write` are NOT included in `input_tokens` (OpenAI: Inspect records
prompt_tokens - cached_tokens; Anthropic: the API's own input_tokens already excludes them). So the
cost is the sum of the four parts, each at its own price. Reasoning tokens are part of
`output_tokens` and are not added again.

Model names match a table key exactly, or by prefix at a "-" boundary (dated snapshots such as
openai/gpt-4o-2024-08-06), longest key first. A bare name without provider ("gpt-4o") is matched
against the part of each key after "provider/". An unknown model raises UnknownModelError.

Verification: every price was checked once against the provider's pricing page on 2026-10-21; the
per-price result (date and URL, or "unverified") is in VERIFIED and docs/prices_verified_2026-10-21.md.
Two prices differ from the page and were NOT changed (owner's decision pending): Sonnet 5.5 and Opus 5.5
cache_read are 0.1x base input here, 0.05x on Anthropic's page. Nothing has been checked against an invoice.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class UnknownModelError(KeyError):
    pass


@dataclass(frozen=True)
class Price:
    """$ per 1M tokens."""
    input: float
    cache_read: float
    cache_write: float
    output: float


# The per-price comments below record where each value came from when the table was written (2026-10-21,
# before any page check; "UNVERIFIED" there means unverified at that time). The page check of the same day is
# recorded per price in VERIFIED below and in docs/prices_verified_2026-10-21.md; no value was changed by it.
PRICES: dict[str, Price] = {
    # input 2.50 / output 10.00: phases/phase3_allocation_monitor/sweep.py PRICE (OpenAI list).
    # cached input 1.25 (50% of input): results/spend_2026-10-20.md, OpenAI list, unverified there too.
    # OpenAI charges no cache write; none is ever recorded, priced at full input to stay conservative.
    "openai/gpt-4o": Price(input=2.50, cache_read=1.25, cache_write=2.50, output=10.00),
    # input 0.15 / output 0.60: sweep.py PRICE; cached 0.075: results/spend_2026-10-20.md. Unverified.
    "openai/gpt-4o-mini": Price(input=0.15, cache_read=0.075, cache_write=0.15, output=0.60),
    # input 2.00 / output 10.00: results/spend_2026-10-20.md (Anthropic claude-api skill model table,
    # cached 2026-10-06). Unverified. Cache read 0.1x / write 1.25x input (5-minute TTL): Anthropic
    # prompt-caching multipliers as recorded in control_loop/adapters/controlarena/reader.py.
    "anthropic/claude-sonnet-5-5": Price(input=2.00, cache_read=0.10, cache_write=2.50, output=10.00),  # cache_read 0.20 -> 0.10 on 2026-10-22 (owner; Anthropic page 0.05x base, docs/prices_verified_2026-10-21.md); figures recorded before that date used 0.20
    # Phase 4 models, kept so the ControlArena reader prices through here. input/output from
    # phases/phase4_controlarena/PLAN.md §5; cache multipliers as above. Unverified.
    "anthropic/claude-opus-5-5": Price(input=4.00, cache_read=0.20, cache_write=5.00, output=20.00),  # cache_read 0.40 -> 0.20 on 2026-10-22 (owner; Anthropic page 0.05x base); Phase 4 stated as a range
    "anthropic/claude-sonnet-4-6": Price(input=3.00, cache_read=0.30, cache_write=3.75, output=15.00),
    # Phase 4 red-team selection (PLAN §11, 2026-10-21).
    # Open-weight arm. Read from OpenRouter's public catalog (GET /api/v1/models/qwen/qwen3-235b-a22b-2507/
    # endpoints, no key, 2026-10-21): tool-capable endpoints charge 0.0875-0.22 input / 0.35-0.88 output
    # (default listing 0.09 / 0.55). Routing is not pinned, so the most expensive tool-capable endpoint
    # (Google, 0.22 / 0.88) is used as an upper bound. No cache price is listed for this model; cached
    # tokens are priced at full input. Not checked against an OpenRouter invoice: UNVERIFIED.
    "openrouter/qwen/qwen3-235b-a22b-2507": Price(input=0.22, cache_read=0.22, cache_write=0.22, output=0.88),
    # Arm A (PLAN §11, revised 2026-10-21): the Async Control paper's untrusted model (arXiv 2512.13526,
    # App. A: claude-opus-4-1-20250805) through OpenRouter, whose only endpoint is Amazon Bedrock
    # (`anthropic/claude-4.1-opus-20250805`). 15.00 in / 75.00 out / 18.75 cache write / 1.50 cache read:
    # GET https://openrouter.ai/api/v1/models/anthropic/claude-opus-4.1/endpoints, read 2026-10-21, no key.
    # Not checked against an invoice: UNVERIFIED.
    "openrouter/anthropic/claude-opus-4.1": Price(input=15.00, cache_read=1.50, cache_write=18.75, output=75.00),
    # Arm A fallback if that endpoint fails (§11.1): Claude Opus 4.5 on Anthropic's API. 5.00 / 25.00 from
    # OpenRouter's catalog entry anthropic/claude-opus-4.5 (read 2026-10-21); cache multipliers as above.
    # UNVERIFIED against Anthropic's pricing page.
    "anthropic/claude-opus-4-5-20251101": Price(input=5.00, cache_read=0.50, cache_write=6.25, output=25.00),
}

# Page check of 2026-10-21 (docs/prices_verified_2026-10-21.md): model -> field -> "<date> <url>" when the page
# showed a price for that field, "unverified" when it showed none. "<date> <url>" says the page was read, not that
# the table equals it: the two cache_read entries marked "DIFFERS" are 0.1x base input here and 0.05x on the page.
_OPENAI = "https://developers.openai.com/api/docs/pricing"
_ANTHROPIC = "https://platform.claude.com/docs/en/about-claude/pricing"
_OR_QWEN = "https://openrouter.ai/qwen/qwen3-235b-a22b-2507"
_OR_OPUS41 = "https://openrouter.ai/anthropic/claude-opus-4.1"
_D = "2026-10-21 "
VERIFIED: dict[str, dict[str, str]] = {
    # OpenAI lists Input / Cached input / Output; no cache-write price exists, so cache_write stays unverified.
    "openai/gpt-4o": {"input": _D + _OPENAI, "cache_read": _D + _OPENAI, "cache_write": "unverified",
                      "output": _D + _OPENAI},
    "openai/gpt-4o-mini": {"input": _D + _OPENAI, "cache_read": _D + _OPENAI, "cache_write": "unverified",
                           "output": _D + _OPENAI},
    # Page: 2.00 / 0.10 (DIFFERS: table 0.20) / 2.50 (5m) / 10.00.
    "anthropic/claude-sonnet-5-5": {"input": _D + _ANTHROPIC, "cache_read": _D + _ANTHROPIC + " DIFFERS page=0.10",
                                    "cache_write": _D + _ANTHROPIC, "output": _D + _ANTHROPIC},
    # Page: 4.00 / 0.20 (DIFFERS: table 0.40) / 5.00 (5m) / 20.00.
    "anthropic/claude-opus-5-5": {"input": _D + _ANTHROPIC, "cache_read": _D + _ANTHROPIC + " DIFFERS page=0.20",
                                  "cache_write": _D + _ANTHROPIC, "output": _D + _ANTHROPIC},
    # Page: 3.00 / 0.30 / 3.75 (5m) / 15.00, all equal.
    "anthropic/claude-sonnet-4-6": {"input": _D + _ANTHROPIC, "cache_read": _D + _ANTHROPIC,
                                    "cache_write": _D + _ANTHROPIC, "output": _D + _ANTHROPIC},
    # Model page headline 0.0875 / 0.35 (cheapest endpoint); the Google tool-capable endpoint the table uses is
    # listed at 0.22 / 0.88 (equal). That endpoint lists no cache price; no endpoint lists a cache write.
    "openrouter/qwen/qwen3-235b-a22b-2507": {"input": _D + _OR_QWEN, "cache_read": "unverified",
                                             "cache_write": "unverified", "output": _D + _OR_QWEN},
    # Single endpoint (Amazon Bedrock): 15.00 / 1.50 / 18.75 / 75.00, all equal. Retired on Anthropic's own API
    # (deprecations page: retired 2026-08-05); Anthropic's pricing page lists the same four prices for it.
    "openrouter/anthropic/claude-opus-4.1": {"input": _D + _OR_OPUS41, "cache_read": _D + _OR_OPUS41,
                                             "cache_write": _D + _OR_OPUS41, "output": _D + _OR_OPUS41},
    # Page: 5.00 / 0.50 / 6.25 (5m) / 25.00, all equal; model Active on the deprecations page.
    "anthropic/claude-opus-4-5-20251101": {"input": _D + _ANTHROPIC, "cache_read": _D + _ANTHROPIC,
                                           "cache_write": _D + _ANTHROPIC, "output": _D + _ANTHROPIC},
}


def price_for(model: str, prices: Mapping[str, Price] = PRICES) -> Price:
    def matches(name: str, key: str) -> bool:
        return name == key or name.startswith(key + "-")

    bare = "/" not in model
    hits = [k for k in prices if matches(model, k.split("/", 1)[-1] if bare else k)]
    if not hits:
        raise UnknownModelError(f"no price for model {model!r}; add it to control_loop.spend.PRICES")
    return prices[max(hits, key=len)]


def usage_cost(model: str, usage: Any, prices: Mapping[str, Price] = PRICES) -> float:
    """Dollars for one Inspect ModelUsage of `model`."""
    p = price_for(model, prices)
    return (usage.input_tokens * p.input
            + (usage.input_tokens_cache_read or 0) * p.cache_read
            + (usage.input_tokens_cache_write or 0) * p.cache_write
            + usage.output_tokens * p.output) / 1e6


def usage_map_cost(model_usage: Mapping[str, Any] | None, prices: Mapping[str, Price] = PRICES) -> float:
    """Dollars for a {model: ModelUsage} map (EvalLog.stats.model_usage or EvalSample.model_usage)."""
    return sum(usage_cost(m, u, prices) for m, u in (model_usage or {}).items())


def log_cost(log: Any, prices: Mapping[str, Price] = PRICES) -> float:
    """Dollars for an Inspect EvalLog (a header-only read is enough)."""
    return usage_map_cost(log.stats.model_usage if log.stats else None, prices)
