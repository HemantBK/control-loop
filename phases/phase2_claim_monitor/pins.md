# Pins

Everything the Phase 2 results depend on, as run on 2026-10-20 (Asia/Kolkata). Written 2026-10-21 after the two Phase 2 audits (`audits/`). What is shared with Phase 1 is pinned in `../phase1_orbit_redteam/pins.md` and not repeated here.

## Code

| item | value |
|---|---|
| ORBIT | 1.0.3, commit `588b303`, unmodified; a git dependency of this repository (`pyproject.toml`, `uv.lock`) |
| inspect-ai | 0.3.263 |
| other versions | as `../phase1_orbit_redteam/pins.md` (Python 3.13.14, uv 0.11.25, anthropic SDK 1.6.0, openai SDK 3.13.0) |
| this package | the cells and checks ran in the ORBIT clone (`adaptive_control/`, branch `adaptive-redteam`; Phase 2 committed there at `ff85245`) and were migrated into this repository at `b894b66`; the §16.12 prerequisites ran from this repository after `b894b66` |
| presets | `claim_time_monitor` (defense `claim_time_monitor_v1_seeded`), `claim_time_monitor_4o`, `claim_rule_monitor` (`claim_rule_monitor_v1_seeded`), `claim_score_only`, in `control_loop/adapters/orbit/jira_adaptive.py` |
| claim prompt | `CLAIM_JUDGE_PREAMBLE` + context + `CLAIM_JUDGE_SUFFIX`, as amended in `PLAN.md` §16.9; messages and other tool calls judged with `FIXED_JUDGE_PROMPT` |
| P(BLOCK) | first-token top-5 log-probabilities; the token test was corrected on 2026-10-21 to the registered "begins BLOCK" (README §9); the saved scores are unchanged by it |

## Model strings, exactly as passed

| role | string | resolved by the provider (ModelEvent `output.model`) | used in |
|---|---|---|---|
| agents (dev_0..dev_3) | `openai/gpt-4o`, temperature 0, seed 733 | `gpt-4o-2024-08-06` (7,720 events) | every Phase 2 episode |
| claim judge and message judge | `openai/gpt-4o-mini`, temperature 0, seed 733 | `gpt-4o-mini-2024-07-18` (6,461 events) | `claim_time_monitor`, the rule arm's message judge, the score-only pass |
| claim judge and message judge, 4o arm | `openai/gpt-4o`, temperature 0, seed 733 | `gpt-4o-2024-08-06` | `claim_time_monitor_4o` (early only) |
| proposer | `anthropic/claude-sonnet-5-5`, informed brief | not logged | the five adaptive cells |
| proposer settings | temperature 0 and seed 100 × 733 + round (73301–73305) requested in `GenerateConfig` and logged in `proposer_log.jsonl`, but not sent: Inspect 0.3.263's Anthropic provider drops `seed` and suppresses `temperature` for this model. Provider defaults applied. The proposer is not seeded at temperature 0; payloads are reproducible only by replaying `payload_rN.txt` | | all `prop_sonnet55/733_claim_*` cells |

## Settings

| setting | value |
|---|---|
| task options | as Phase 1 (`num_developers=4`, `num_tasks=4`, `scarcity=0.5`, `max_turns=40`), `token_limit=200000`, `--no-fail-on-error`, coalition dev_0, dev_1 |
| orderings | explicit early and late plans (`control_loop/adapters/orbit/orderings.py`) |
| seed | 733 |
| baselines | two independent clean runs of 8 epochs per (ordering, arm), `max_samples=4`; the score-only pass one run of 8 epochs (pre-registered) |
| rounds | 0 static (ORBIT's sentence) + 5 adaptive, one episode each; §16.12(a) 3 epochs of round 0; §16.12(b) 3 epochs of the Phase 1 headline payload |

## Dates run and spend

Spend is list price, reconciled by hand from the logs in `results/spend_2026-10-20.md` (agents and judge from Inspect's token counts including gpt-4o cache reads at OpenAI's cached-input price; the proposer from logged characters, since its usage is not logged). The upper bound prices cache reads at the full input price and the proposer at $0.15 per cell.

| what | date (UTC on the eval names) | where | episodes | spend | upper bound |
|---|---|---|---|---|---|
| mechanism check and re-run (§16.8, §16.9) | 2026-10-20 10:50–11:08 | `results/phase2_claim_monitor/early/ctm_check{,2}` | 4 | in the line below | |
| gpt-4o-mini cells, both orderings (§16.6, §16.10) | 2026-10-20 11:11–11:28 | `results/phase2_claim_monitor/{early,late}/{baselines,prop_sonnet55}/733_claim_time_monitor` | 44 | in the line below | |
| rule cells, both orderings, and gpt-4o cell, early (§16.11) | 2026-10-20 12:01–12:21 | `.../733_claim_rule_monitor`, `.../early/.../733_claim_time_monitor_4o` | 66 | in the line below | |
| cells and checks together (agents + judge $18.51, upper $20.53; proposer 5 cells $0.12, upper $0.75) | | | 114 | $18.63 | $21.28 |
| §16.12(a) two independent greedy agents | 2026-10-20 14:14 (19:44 IST) | `results/phase2_claim_monitor/late/greedy_two/` | 9 | $0.78 | $0.89 |
| §16.12(b) score-only pass | 2026-10-20 14:16–14:18 | `results/phase2_claim_monitor/late/{baselines/733_claim_score_only,score_only/733_claim_score_only}` | 11 | $0.57 | $0.65 |
| §16.12(b) smoke (schema check) | 2026-10-20 14:15 | `results/phase2_claim_monitor/late/score_only/_smoke` | 1 | $0.04 | $0.04 |
| §16.12 together | | | 21 | $1.39 | $1.57 |
| **Phase 2 total** | | | **135** | **$20.02** | **$22.85** |

Caps: $40 for Phase 2 (`PLAN.md` §16.7; 50% used, 57% at the upper bound) and $5 for §16.12 (28%, 31%). No cell over $15; no phase at 80%. The figures quoted before 2026-10-21 ($16.49 for the cells and checks, $1.20 for §16.12, $17.69 in all) were the sweep method, which leaves out gpt-4o cache reads and the proposer.
