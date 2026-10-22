"""No-API tests for control_loop.spend (offline). ModelUsage objects are built by hand; the regression check
reads the real Phase 3 logs header-only and is skipped when they are absent."""
from __future__ import annotations

from pathlib import Path

import pytest
from inspect_ai.model import ModelUsage

from control_loop.spend import Price, UnknownModelError, log_cost, price_for, usage_cost, usage_map_cost

REPO = Path(__file__).resolve().parents[1]
P3 = REPO / "results" / "phase3_allocation_monitor"
# results/spend_2026-10-20.md: "P3 agents+judge: ... cache@cached-rate $11.44"
# (gpt-4o $11.31 + gpt-4o-mini $0.13; the $11.62 total adds the proposer estimate, which no log records).
RECONCILED_P3_AGENTS_JUDGE = 11.44


def test_cached_tokens_are_priced():
    plain = ModelUsage(input_tokens=1_000_000, output_tokens=0)
    cached = ModelUsage(input_tokens=1_000_000, output_tokens=0, input_tokens_cache_read=1_000_000)
    assert usage_cost("openai/gpt-4o", plain) == pytest.approx(2.50)
    assert usage_cost("openai/gpt-4o", cached) == pytest.approx(2.50 + 1.25)
    written = ModelUsage(input_tokens=0, output_tokens=0, input_tokens_cache_write=1_000_000)
    assert usage_cost("anthropic/claude-sonnet-5-5", written) == pytest.approx(2.50)


def test_unknown_model_raises():
    u = ModelUsage(input_tokens=10, output_tokens=10)
    for name in ("openai/gpt-4.1-mini", "openai/gpt-5", "mockllm/model", "openai/gpt-4oX", "azure/gpt-4o"):
        with pytest.raises(UnknownModelError):
            usage_cost(name, u)


def test_name_matching_exact_or_prefix():
    assert price_for("openai/gpt-4o-mini").input == 0.15          # longest key wins over openai/gpt-4o
    assert price_for("openai/gpt-4o-2024-08-06").input == 2.50     # dated snapshot, prefix at "-"
    assert price_for("openai/gpt-4o-mini-2024-07-18").input == 0.15
    assert price_for("gpt-4o").input == 2.50                       # bare name
    assert price_for("claude-sonnet-5-5").output == 10.00


def test_fixture_total_matches_hand_computation():
    usage = {
        "openai/gpt-4o": ModelUsage(input_tokens=95_685, output_tokens=18_410, input_tokens_cache_read=63_872),
        "openai/gpt-4o-mini": ModelUsage(input_tokens=40_000, output_tokens=1_500),
        "anthropic/claude-sonnet-5-5": ModelUsage(input_tokens=6_600, output_tokens=950,
                                                  input_tokens_cache_read=2_000, input_tokens_cache_write=1_000),
    }
    # by hand, $ per 1M: gpt-4o 95,685*2.50 + 63,872*1.25 + 18,410*10.00 = 239,212.5 + 79,840 + 184,100 = 503,152.5
    # gpt-4o-mini 40,000*0.15 + 1,500*0.60 = 6,000 + 900 = 6,900
    # sonnet-5-5 6,600*2.00 + 2,000*0.10 + 1,000*2.50 + 950*10.00 = 13,200 + 200 + 2,500 + 9,500 = 25,400
    # (cache_read 0.20 -> 0.10 on 2026-10-22, owner's price correction; was 25,600 / 0.5356525)
    hand = (503_152.5 + 6_900 + 25_400) / 1e6  # 0.5354525
    assert usage_map_cost(usage) == pytest.approx(hand, abs=1e-9)


def test_phase3_logs_match_reconciliation():
    files = sorted(P3.rglob("*.eval")) if P3.exists() else []
    if not files:
        pytest.skip("Phase 3 logs not present")
    from inspect_ai.log import read_eval_log

    total = sum(log_cost(read_eval_log(str(p), header_only=True)) for p in files)
    assert len(files) == 68
    assert total == pytest.approx(RECONCILED_P3_AGENTS_JUDGE, abs=0.01), total


def test_verified_covers_every_price():
    """docs/prices_verified_2026-10-21.md: every PRICES key has a VERIFIED entry for each of the four fields."""
    from dataclasses import fields

    from control_loop.spend import PRICES, VERIFIED

    names = {f.name for f in fields(Price)}
    assert set(VERIFIED) == set(PRICES)
    for model, by_field in VERIFIED.items():
        assert set(by_field) == names, model
        for field, status in by_field.items():
            assert status == "unverified" or status.startswith("2026-10-21 https://"), (model, field, status)
