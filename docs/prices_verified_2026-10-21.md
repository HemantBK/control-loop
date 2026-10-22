# control_loop/spend.py price table checked against the providers' pricing pages (2026-10-21)

One-off check of every price in `control_loop.spend.PRICES` (8 models x 4 fields = 32 prices) against the
provider's current official page, read from the Mac on 2026-10-21 (no model call, no invoice). Nothing in
`PRICES` was changed by this check; `spend.VERIFIED` records, per price, the date and URL or `unverified`.
The owner decides whether any past spend figure is restated.

Result: 26 equal, 2 differ, 4 unverified (page lists no such price).

## Pages read

| Short name | URL | Note |
| --- | --- | --- |
| OpenAI | https://developers.openai.com/api/docs/pricing | `platform.openai.com/docs/pricing` 301-redirects here; `openai.com/api/pricing/` returned 403 to the fetcher. Standard tier, text. Rows list Input / Cached input / Output only. |
| Anthropic | https://platform.claude.com/docs/en/about-claude/pricing | `docs.anthropic.com/en/docs/about-claude/pricing` 301-redirects here. Prices shown for the 5-minute cache TTL; the page's footnote 2 says cache hits on Opus 5.5 and Sonnet 5.5 are 0.05x base input (others 0.1x). `claude.com/pricing` (redirect of `anthropic.com/pricing`) shows the same numbers. |
| Anthropic deprecations | https://platform.claude.com/docs/en/about-claude/model-deprecations | `claude-opus-4-1-20250805`: Retired (deprecated 2026-06-05, retired 2026-08-05). `claude-opus-4-5-20251101`: Active. |
| OpenRouter Qwen | https://openrouter.ai/qwen/qwen3-235b-a22b-2507 and https://openrouter.ai/api/v1/models/qwen/qwen3-235b-a22b-2507/endpoints | Model page headline: $0.0875/M input, $0.35/M output, cache read $0.0175/M (cheapest endpoint). Endpoints (input / output / cache read, $/M): GMICloud 0.0875 / 0.35 / 0.0175; DeepInfra 0.09 / 0.55 / -; Parasail 0.14 / 0.80 / 0.05; Venice 0.15 / 0.75 / -; Nebius 0.20 / 0.60 / -; Google 0.22 / 0.88 / - (tools); Google 0.25 / 1.00 / - (no tools). No endpoint lists a cache-write price. |
| OpenRouter Opus 4.1 | https://openrouter.ai/anthropic/claude-opus-4.1 and https://openrouter.ai/api/v1/models/anthropic/claude-opus-4.1/endpoints | Single endpoint, Amazon Bedrock: $15.00 / $75.00, cache read $1.50, cache write $18.75 (1h $30.00). |

## Table

Prices in $ per 1M tokens. "Table" is the value in `PRICES`; "Page" is the value read on 2026-10-21.

| Model string | Field | Table | Page | URL | Status |
| --- | --- | --- | --- | --- | --- |
| openai/gpt-4o | input | 2.50 | 2.50 | OpenAI | equal |
| openai/gpt-4o | cache_read | 1.25 | 1.25 (Cached input) | OpenAI | equal |
| openai/gpt-4o | cache_write | 2.50 | not listed | OpenAI | page does not list cache write (OpenAI charges none; table uses full input, never recorded) |
| openai/gpt-4o | output | 10.00 | 10.00 | OpenAI | equal |
| openai/gpt-4o-mini | input | 0.15 | 0.15 | OpenAI | equal |
| openai/gpt-4o-mini | cache_read | 0.075 | 0.075 (Cached input) | OpenAI | equal |
| openai/gpt-4o-mini | cache_write | 0.15 | not listed | OpenAI | page does not list cache write (as above) |
| openai/gpt-4o-mini | output | 0.60 | 0.60 | OpenAI | equal |
| anthropic/claude-sonnet-5-5 | input | 2.00 | 2.00 | Anthropic | equal |
| anthropic/claude-sonnet-5-5 | cache_read | 0.20 | 0.10 (0.05x base input, footnote 2) | Anthropic | differs: table is 0.10 higher (2x) |
| anthropic/claude-sonnet-5-5 | cache_write | 2.50 | 2.50 (5m) | Anthropic | equal |
| anthropic/claude-sonnet-5-5 | output | 10.00 | 10.00 | Anthropic | equal |
| anthropic/claude-opus-5-5 | input | 4.00 | 4.00 | Anthropic | equal |
| anthropic/claude-opus-5-5 | cache_read | 0.40 | 0.20 (0.05x base input, footnote 2) | Anthropic | differs: table is 0.20 higher (2x) |
| anthropic/claude-opus-5-5 | cache_write | 5.00 | 5.00 (5m) | Anthropic | equal |
| anthropic/claude-opus-5-5 | output | 20.00 | 20.00 | Anthropic | equal |
| anthropic/claude-sonnet-4-6 | input | 3.00 | 3.00 | Anthropic | equal |
| anthropic/claude-sonnet-4-6 | cache_read | 0.30 | 0.30 | Anthropic | equal |
| anthropic/claude-sonnet-4-6 | cache_write | 3.75 | 3.75 (5m) | Anthropic | equal |
| anthropic/claude-sonnet-4-6 | output | 15.00 | 15.00 | Anthropic | equal |
| openrouter/qwen/qwen3-235b-a22b-2507 | input | 0.22 | 0.22 (Google tool-capable endpoint; headline 0.0875; range 0.0875-0.25) | OpenRouter Qwen | equal to the endpoint the table was built from (upper bound of the tool-capable endpoints, by design; routing not pinned) |
| openrouter/qwen/qwen3-235b-a22b-2507 | cache_read | 0.22 | Google endpoint lists none; GMICloud 0.0175, Parasail 0.05 | OpenRouter Qwen | unverified: no cache-read price for the priced endpoint; table charges full input (upper bound) |
| openrouter/qwen/qwen3-235b-a22b-2507 | cache_write | 0.22 | not listed by any endpoint | OpenRouter Qwen | unverified: page does not list cache write; table charges full input (never recorded, see Consequences) |
| openrouter/qwen/qwen3-235b-a22b-2507 | output | 0.88 | 0.88 (Google tool-capable endpoint; headline 0.35; range 0.35-1.00) | OpenRouter Qwen | equal to the endpoint the table was built from (as for input) |
| openrouter/anthropic/claude-opus-4.1 | input | 15.00 | 15.00 | OpenRouter Opus 4.1 | equal (Bedrock, the only endpoint; Anthropic's page lists the same for the retired model) |
| openrouter/anthropic/claude-opus-4.1 | cache_read | 1.50 | 1.50 | OpenRouter Opus 4.1 | equal |
| openrouter/anthropic/claude-opus-4.1 | cache_write | 18.75 | 18.75 | OpenRouter Opus 4.1 | equal |
| openrouter/anthropic/claude-opus-4.1 | output | 75.00 | 75.00 | OpenRouter Opus 4.1 | equal |
| anthropic/claude-opus-4-5-20251101 | input | 5.00 | 5.00 | Anthropic | equal (model Active on the deprecations page) |
| anthropic/claude-opus-4-5-20251101 | cache_read | 0.50 | 0.50 | Anthropic | equal |
| anthropic/claude-opus-4-5-20251101 | cache_write | 6.25 | 6.25 (5m) | Anthropic | equal |
| anthropic/claude-opus-4-5-20251101 | output | 25.00 | 25.00 | Anthropic | equal |

Not covered by the table but on the pages: Anthropic's 1-hour cache write is 2x base input (Sonnet 5.5 $4, Opus 5.5 $8,
Sonnet 4.6 $6, Opus 4.5 $10); the table prices every cache write at the 5-minute rate (1.25x). Anthropic's
`inference_geo` US-only option is a 1.1x multiplier on every token category for Claude 4.6 and later (the default,
global routing, is standard pricing); OpenRouter likewise lists 1.1x Bedrock/Google/Azure variants for Sonnet 4.6,
Opus 5.5, Sonnet 5.5 and Opus 4.5. The table assumes the standard (global) rate.

## Consequences

Which spend figures would move if the two differing prices (Sonnet 5.5 and Opus 5.5 cache read, both 2x the page)
were applied. Direction only; no total is restated here. The affected component is cache-read tokens of those two
models in Inspect logs priced through `control_loop.spend`; all other components are unchanged.

- Phase 4 (ControlArena, `results/phase4_controlarena`): moves DOWN by a small amount. The logs record
  31,110 cache-read tokens for `anthropic/claude-opus-5-5` (7 .eval files) priced at 0.40 instead of 0.20;
  `anthropic/claude-sonnet-5-5` does not appear in any Phase 4 .eval header (the proposer is priced outside the
  logs). `anthropic/claude-sonnet-4-6` (the monitor, 870,197 cache-write tokens, 0 cache reads) and the two
  OpenRouter models are unaffected. The driver's printed and exact Phase 4 figures both come from this table.
- Phases 1, 2, 3 (`results/prop_sonnet55`, `results/prop_qwen3`, `results/phase2_claim_monitor`,
  `results/phase3_allocation_monitor`): no change. Their Inspect logs hold only `openai/gpt-4o` and
  `openai/gpt-4o-mini` (all four prices equal); the Sonnet 5.5 proposer there is a character-based estimate with
  no cache split. The Phase 3 reconciliation test (`tests/test_spend.py::test_phase3_logs_match_reconciliation`)
  is therefore unaffected.
- Phases 5, 8 (running or about to run; proposer `anthropic/claude-sonnet-5-5`): no past figure to move
  (`results/phase5_claim_protocol` did not exist at the time of this check); if their logs record Sonnet 5.5
  cache reads, the table overstates that component by 2x until the owner changes the price.
- Phases 6, 7 (pre-registration only): no figure yet; the same applies to any Sonnet 5.5 / Opus 5.5 cache reads.

Remaining unverified prices (4): `openai/gpt-4o` and `openai/gpt-4o-mini` cache_write (OpenAI lists no cache
write and Inspect never records one for OpenAI, so the value is never applied), and
`openrouter/qwen/qwen3-235b-a22b-2507` cache_read and cache_write (the Google endpoint lists neither; the table
charges full input as an upper bound; Phase 4 logs record 11,175 Qwen cache-read tokens and 0 cache writes, so the
Phase 4 figure can only be high, not low, on this component).

## Decision 2026-10-22

Owner: option (a). The two cache-read prices are corrected in `control_loop/spend.py` to the page values (Sonnet 5.5 0.10, Opus 5.5 0.20 per 1M) from Phase 5 on; figures recorded before 2026-10-22 stay as stated (Phase 4 as the range $7.8086–$7.8170); Phases 1–3 are unaffected.

