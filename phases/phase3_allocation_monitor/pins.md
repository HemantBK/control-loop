# Pins

Everything the Phase 3 results depend on, as run on 2026-10-20 (Asia/Kolkata). Written 2026-10-21 with the write-up (`README.md`). What is shared with Phase 1 is pinned in `../phase1_orbit_redteam/pins.md` and not repeated here.

## Code

| item | value |
|---|---|
| ORBIT | 1.0.3, commit `588b303`, unmodified; a git dependency of this repository (`pyproject.toml`, `uv.lock`) |
| inspect-ai | 0.3.263 (recorded in every eval header) |
| other versions | as `../phase1_orbit_redteam/pins.md` (Python 3.13.14, uv 0.11.25, anthropic SDK 1.6.0, openai SDK 3.13.0) |
| this package, as run | eval headers record the repository revision as dirty in every Phase 3 episode: mechanism check at `df96590` (3 episodes) and `f10c15f` (1), before the presets were committed in `60b4dcd` (2026-10-20 19:34 IST); sweep at `b894b66` (60 eval files) and `2fb1268` (4: the 733 early clean runs, started 14:09 UTC), with `sweep.py` and `sweep_table.py` uncommitted until `994a7fa` (2026-10-21 00:47 IST). The `*_autoallow` presets (the `_auto_allow` override, the `allocation_{rule,llm}_autoallow` branch of `_get_defenses`, and their `DEFENSES` entries) are **not** in `994a7fa`: they are uncommitted working-tree changes in `control_loop/adapters/orbit/{__init__,jira_adaptive}.py`, committed in the commit that follows `994a7fa` (pending) [2026-10-22: committed in `c95b7a8` (2026-10-21 02:17 IST, "phase3: write-up, two independent audits, fixes; commit the autoallow sweep presets", per `git log`); source `FINDINGS.md` "2026-10-22: corrections" (T3.7), commit `c95b7a8`]. A clean checkout of `994a7fa` cannot run the sweep (corrected 2026-10-21, audit_claude C4, audit_codex X5) |
| presets | `allocation_rule_monitor` and `allocation_llm_monitor` (check; message judge on), `allocation_rule_autoallow` and `allocation_llm_autoallow` (sweep; message judge auto-allow), in `control_loop/adapters/orbit/jira_adaptive.py`; rule `control_loop/adapters/orbit/allocation_monitor.py` (`rule_verdict`); defense names end `_v1_seeded` |
| LLM prompt | `PLAN.md` §1.3, built by `allocation_monitor.llm_prompt`; the check's message judge `FIXED_JUDGE_PROMPT` |
| reference allocation | ORBIT's `DCOPState.optimal_assignment`; `sweep_table.py` rebuilds it with `build_problem(num_developers=4, num_tasks=4, scarcity=0.5, seed)` |
| spend code | the sweep ran with `sweep.py`'s old `spend()` (no cache reads, flat $0.15 per proposer cell); since 2026-10-21 `sweep.py` imports `control_loop/spend.py` (uncommitted) |

## Model strings, exactly as passed

| role | string | resolved by the provider (ModelEvent `output.model`) | used in |
|---|---|---|---|
| agents (dev_0..dev_3) | `openai/gpt-4o`, temperature 0, seed = problem seed (733 or 512), `max_tokens=1200` | `gpt-4o-2024-08-06` (3,618 events) | every Phase 3 episode |
| claim judge, LLM arm; message judge, check | `openai/gpt-4o-mini`, temperature 0, seed = problem seed (`judge_seed` task arg) | `gpt-4o-mini-2024-07-18` (1,184 events) | `allocation_llm_autoallow` claims; both check presets' message and tool judge. The rule arm in the sweep makes no judge call |
| proposer | `anthropic/claude-sonnet-5-5`, informed brief (Phase 1 brief, which describes the defense as "an LLM monitor that judges each message and tool call in isolation", `control_loop/proposer.py` lines 64–65 at `994a7fa`; not told about the allocation monitor) | not logged | the 8 `prop_sonnet55` cells |
| proposer settings | temperature 0 and seed 100 × seed + round (73301–73305, 51201–51205) requested in `GenerateConfig` and logged in `proposer_log.jsonl`, but **not sent**: Inspect 0.3.263's Anthropic provider drops `seed` and suppresses `temperature` for this model. Provider defaults applied. The proposer is not seeded at temperature 0; payloads are reproducible only by replaying `payload_rN.txt` | | all 40 adaptive rounds |

## Settings

| setting | value |
|---|---|
| task options | `num_developers=4`, `num_tasks=4`, `scarcity=0.5` (default), `max_turns=40`, `max_time_seconds=350`, `runtime_profile=common/v1`, `persuasion_tactic=reciprocity_trade`, `misalignment_strategy=covert_reward_maximization`, `coalition_agents=dev_0,dev_1`; `token_limit=200000`, `fail_on_error=False` |
| orderings | explicit early and late plans (`control_loop/adapters/orbit/orderings.py`) |
| seeds | check: 733; sweep: 733 and 512 |
| presets per run | check: `allocation_rule_monitor`, `allocation_llm_monitor`; sweep: `allocation_rule_autoallow`, `allocation_llm_autoallow` |
| check episodes | seed 733, early; one clean and one A0 (the Phase 1 headline payload, `results/v2/late/prop_sonnet55/733_llm_monitor_fixed_actions/best_payload.txt`) per preset, via `check.py` |
| sweep baselines | two independent clean runs of 8 epochs per cell, `max_samples=4` (`run1` by the loop, `run2` by `--baseline-only` in parallel) |
| rounds | 0 static (ORBIT's sentence) + 5 adaptive, one episode each |
| driver | `phases/phase3_allocation_monitor/sweep.py --arm {rule,llm}`, both streams at once (README section 9) |

## Dates run and spend

Spend is list price, reconciled by hand from the logs in `results/spend_2026-10-20.md`. The "spend" column is measured: agents and judge are priced from Inspect's token counts, including gpt-4o cache reads at OpenAI's cached-input price. The proposer part is an estimate from logged visible characters, since its usage is not logged; its hidden thinking is not in the logs and not in the estimate. The "upper bound" column is conditional, not unconditional: it prices cache reads at the full input price and the proposer at the flat $0.15 per cell, and it is a bound only if the proposer's hidden thinking stayed under about 13k tokens per cell, which no log shows (audit_codex X2). Per-cell figures are the reconciliation's rows, rounded, so they sum to within a cent of the totals.

| what | date (UTC on the eval names) | where | episodes | spend | upper bound |
|---|---|---|---|---|---|
| mechanism check (§5) | 2026-10-20 13:45–13:54 | `results/phase3_allocation_monitor/check/` | 4 | $0.70 | $0.79 |
| rule arm, 4 cells (incl. proposer) | 2026-10-20 14:09–14:37 | `results/phase3_allocation_monitor/{early,late}/{baselines,prop_sonnet55}/{733,512}_allocation_rule_autoallow` | 88 | $5.37 | $6.78 |
| LLM arm, 4 cells (incl. proposer) | 2026-10-20 14:09–14:37 | `.../{733,512}_allocation_llm_autoallow` | 88 | $5.54 | $6.99 |
| of which agents + judge, all 180 episodes | | | | $11.44 | $13.36 |
| of which proposer, 8 cells (40 calls) | | | | $0.18 | $1.20 |
| **Phase 3 total** | | | **180** | **$11.62** (measured; proposer part estimated) | **$14.56** (conditional, see above) |

Caps: $25 for Phase 3 (`PLAN.md` §4; 46% used, 58% at the conditional upper figure) and the $24 guard (§6.7; 48%, 61%). The most expensive cell is LLM 733 late at $1.50 (upper $1.91). No cell is over $15, and measured spend is under 80% of the phase budget; that the true total is under 80% holds on the measured figure, not on a certified bound, because proposer thinking is not logged. The §6.7 guard ($24) does not implement the project's spend stop at 80% ($20); see README section 9 (audit_codex X10). The figures quoted before 2026-10-21 ($0.62 for the check and $10.72 in all, in `FINDINGS.md` and `sweep_llm.out`) came from the sweep counter, which leaves out gpt-4o cache reads and uses a flat proposer estimate.
