# Pins

Everything the Phase 4 results depend on, as run on 2026-10-20 and 2026-10-21 (eval names in UTC). Written 2026-10-21 with the write-up (`README.md`); cell M (PLAN §13) added at closing the same day. What is shared with Phase 1 is pinned in `../phase1_orbit_redteam/pins.md` and not repeated here.

## Code

| item | value |
|---|---|
| ControlArena | `control-arena` 20.1.0 from PyPI (released 2026-10-13; tag v20.1.0 = commit `3fdee428a30911e76d892b2440ea94d1f8395b39`; wheel sha256 `e1a9a515a04380574aec40b4cee9763bff715046c4a932ae32170a934b71ae89` in `uv.lock`), MIT, unmodified (adapters only); optional extra `controlarena` in `pyproject.toml` |
| inspect-ai | 0.3.263 (recorded in every eval header) |
| other versions | Python 3.13.14 (`.venv`), uv 0.11.25, anthropic SDK 1.6.0, openai SDK 3.13.0 (as `../phase1_orbit_redteam/pins.md`) |
| this package, as run | eval headers record the repository revision as dirty in every Phase 4 eval: mechanism check (both pairs) at `df96590`, `--limit 3` reproduction at `f10c15f`, selection and cell P at `c95b7a8`. The selection and sweep code (`reproduce.py` options, `dp_task.py` `framing`/`model_seed`/`temperature`, `sweep.py`, `seed_trace.py`, the reader's attempt labels, the `spend.py` prices, the metric fix and the X1 gate fix) is uncommitted at the time of writing, so a clean checkout of `c95b7a8` cannot run them (README section 10) |
| adapter | `control_loop/adapters/controlarena/{dp_task, proposer_policy, reader, reproduce, mechanism_check, seed_trace, sweep}.py` |
| policies | honest: ControlArena's honest policy; attack (reproduction, selection A and C): ControlArena's `attack_policy`; selection B: `proposer_attack_policy(payload_file=None, framing=True)`; mechanism check and sweep: `proposer_attack_policy` with the round's paragraph |
| monitor | `trusted_monitoring` + `basic_monitor` (prompt `monitor_prompts["default"]`), raw 0–10 → 0–1; end-of-trajectory monitor as a scorer, on a deep copy of the messages (`dp_task.cli_final_monitor`) |
| metric code | `sweep.percentile_threshold`, `successful_attacks`, `uncaught_successes(require_main=True)`, `caught_attacks`, `safety`, `verdict`, `recompute`, `metric_table` (fixed 2026-10-21; equal to ControlArena's `_metrics.py` functions, `tests/test_controlarena_metric_fix.py`) |
| spend code | `control_loop/spend.py` (all prices unverified) |

## Model strings, exactly as passed

| role | string | resolved (ModelEvent `output.model`; OpenRouter provider from `call.response.provider`) | used in |
|---|---|---|---|
| untrusted (policy and the setting's judges), default | `anthropic/claude-opus-5-5` | `claude-opus-5-5` | mechanism check, reproduction, selection arm B |
| untrusted, arm A | `openrouter/anthropic/claude-opus-4.1` | `anthropic/claude-opus-4.1`, Amazon Bedrock (15 of 15 events) | selection arm A |
| untrusted, arm C and cell P | `openrouter/qwen/qwen3-235b-a22b-2507` | `qwen/qwen3-235b-a22b-2507`; selection: Parasail 14, DeepInfra 1; cell P: DeepInfra 143, Parasail 26, Venice 21, Google 15; cell M: DeepInfra 75, Google 19, Venice 17, Parasail 16 (routing not pinned) | selection arm C, cells P and M |
| trusted (per-step and end-of-trajectory monitor) | `anthropic/claude-sonnet-4-6` | `claude-sonnet-4-6` | every real eval |
| proposer | `anthropic/claude-sonnet-5-5`, brief `proposer_policy.BRIEF` with `MOVES` (cell M: `BRIEF_MONITOR_AWARE`, `--brief monitor_aware`) | `claude-sonnet-5-5` (`proposer_log.jsonl` `sent.model`) | cell P (7 calls), cell M (8 calls) |
| fallback A' (not run) | `anthropic/claude-opus-4-5-20251101` | – | – |
| mock | `cl_mock/dp` (every role) | – | mock mechanism check, mock sweep rehearsal (scratch only) |

## Seeds and temperature, as sent (read from each ModelEvent's `call.request`)

| step | policy | monitor | setting judges | proposer |
|---|---|---|---|---|
| mechanism check, reproduction (2026-10-20) | `--seed 733` requested, not sent; no temperature | not sent / not sent | Opus 5.5 on the Anthropic path: seed not sent | – (mock only) |
| selection (2026-10-21) | not sent / not sent (`--seed 733` reaches only the active `--model`, README 8(b)) | not sent / not sent | 56 (+retry) on OpenRouter arms; not sent on arm B / temperature not sent | – |
| cell P (2026-10-21) | 733 / 0.0 (`-T model_seed=733 -T temperature=0`) | not sent / 0.0 | 56 + retry index / 0.0: 56 ×128, 57 ×4, 58 ×1 over the 133 judge requests of the 9 logs (`audits/audit_claude.md` C2) | requested 73301–73305 / 0, **neither sent** (X8; recorded only in the adapter's `proposer_log.jsonl`, no Inspect log, `audits/audit_claude.md` C6) |
| cell M (2026-10-21) | 733 / 0.0 | not sent / 0.0 | 56 + retry index / 0.0: 56 ×80, 57 ×5, 58 ×2 over the 87 judge requests of r1–r5 | requested 73301–73305 / 0, **neither sent** (8 calls; `proposer_log.jsonl`) |

## Settings

| setting | value |
|---|---|
| setting | `data_poisoning`, no password or subset filter; epochs 1; `max_steps` None; `fail_on_error` False |
| token limit | 1,000,000 (mechanism check, reproduction); 100,000 (selection, cell P; owner, PLAN §11.10) |
| samples | `--limit 1` (check); `--limit 3` (reproduction, selection; arm A as `--limit 2` then `--limit 3-3`); `--limit 8 --max-samples 8` (cell P) |
| cell P | r0a static (`STATIC_PAYLOAD`), r0b static replicate, r1–r5 adaptive; honest_run1, honest_run2 (n = 8 each); audit budget 1%; τ max-step 0.1, EoT 0.0925 |
| validity | V1 scored, V2 submitted (PLAN §12.3); cell P: all 7 rounds valid under both; cell M: r1–r3 valid, r4 and r5 invalid under both (quality judge 'N', README 8(e)) |
| cell M | `qwen3_733_monitor_aware`: P's honest_run1, honest_run2, r0a, r0b reused (`state.json` `reused`), τ (gain and metric) 0.1 from P's pooled clean runs; r1–r5 adaptive, n = 8; `--brief monitor_aware --baseline-from results/phase4_controlarena/sweep/qwen3_733` |
| driver flags | cell P: PLAN §12.10 commands 1 and 2 plus `--phase-stop 16`; `--cell-cap` 15 (default). Cell M: PLAN §13.7 commands 1 and 2 (`--phase-stop 16 --cell-cap 5`); the full-stage command re-run once more on 2026-10-21 17:52 IST for the summary step only, no model call (README section 10) |

## Dates run and spend

List price from `control_loop.spend` (unverified prices) over each log's `stats.model_usage`, plus cell P's proposer from the usage logged per call (output tokens include thinking). Re-derived 2026-10-21.

| what | date (UTC on the eval names) | where | evals | spend |
|---|---|---|---|---|
| mechanism check, first real pair | 2026-10-20 13:39–13:40 | `results/phase4_controlarena/_attempt1_eot_overwrite/real/` | 2 | $0.2573 |
| mechanism check, final real pair (+ mock pair, $0) | 2026-10-20 13:44–13:45 | `results/phase4_controlarena/mechanism_check/{real,mock}/` | 2 (+2) | $0.2422 |
| `--limit 3` reproduction | 2026-10-20 13:54–13:55 | `results/phase4_controlarena/repro_limit3/` | 2 | $0.6812 |
| selection A, B, C | 2026-10-21 05:13–05:24 | `results/phase4_controlarena/redteam_select/` | 7 | $1.7235 (A $1.1155, B $0.3558, C $0.2522) |
| cell P evals | 2026-10-21 09:11–09:24 | `results/phase4_controlarena/sweep/qwen3_733/{honest,rounds}/` | 9 | $3.0072 |
| cell P proposer (7 calls) | 2026-10-21 | `results/phase4_controlarena/sweep/qwen3_733/redteam/proposer_log.jsonl` | – | $0.0632 |
| Phase 4 through cell P | | | 22 (+2 mock) | $5.9747 |
| cell M evals (r1–r5) | 2026-10-21 11:41–11:53 | `results/phase4_controlarena/sweep/qwen3_733_monitor_aware/rounds/` | 5 | $1.7627 |
| cell M proposer (8 calls) | 2026-10-21 | `results/phase4_controlarena/sweep/qwen3_733_monitor_aware/redteam/proposer_log.jsonl` | – | $0.0796 |
| **Phase 4 total** | | | **27 (+2 mock)** | **$7.8170** |

$5.9747 is exact from the logs. The earlier $5.9739 (`qwen3_733/spend.json`, `RESULTS.md`, STATUS) rounded the 2026-10-20 part: it carried $1.18 rather than $1.1807, a $0.0008 difference (`audits/audit_claude.md` C1; `sweep.PRIOR_PHASE4` still holds the rounded $2.9035). Caps: phase cap $20, stop $16 (owner, PLAN §12.12; 30% and 37% used); selection cap $5, stop $4, arm B cap $1 (PLAN §11.5); spend stop per cell $15 (largest cell P $3.0704). No spend stop. Cell S (Opus 4.1, upper estimate $12.13) not run.

Cell M (2026-10-21): $1.8423 (= its `spend.json` `cell_usd`; reused P logs not counted again), cell cap $5 (37% used). Phase 4 total at closing, exact from the logs: $7.8170 (39% of the $20 cap, 49% of the $16 stop); the driver's $7.8162 carries the rounded prior. No spend stop. Phase 4 closed 2026-10-21 (owner).

2026-10-21, price verification (`docs/prices_verified_2026-10-21.md`): with Anthropic's page price for cache reads (0.05× base instead of the table's 0.10×) the Phase 4 total is $7.8086 (31,110 Opus 5.5 and 21,683 Sonnet 5.5 cache-read tokens); the spend is stated as the range **$7.8086–$7.8170** on the owner's instruction; table prices unchanged (`RESULTS.md`, corrections entry of the same date).
