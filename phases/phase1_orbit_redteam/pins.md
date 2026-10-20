# Pins

Everything the results depend on, as run on 2026-10-19 and 2026-10-20 (Asia/Kolkata).

## Code

| item | value |
|---|---|
| ORBIT | 1.0.3, commit `588b303` (tag v1.0.3), https://github.com/wlanderson0/orbit |
| ORBIT source state | unmodified. In this repository ORBIT is a git dependency pinned to 588b303 (`pyproject.toml`, `uv.lock`); during Phase 1 the package ran inside a clone of ORBIT whose `pyproject.toml` and `uv.lock` changed only by `uv add matplotlib anthropic` |
| this package | `control_loop/` in this repository, with the ORBIT glue under `control_loop/adapters/orbit/`; during Phase 1 it was `adaptive_control/` on branch `adaptive-redteam` of the ORBIT clone (upstream base 588b303), first published at commit c7c8853 of that branch, at which the §8 reproduction was run, and last at 019124e; the commit hashes in this file and in `audits/` refer to that branch |
| inspect-ai | 0.3.263 |
| Python | 3.13.14 (uv-managed CPython, macOS arm64) |
| uv | 0.11.25 |
| matplotlib | 3.11.2 |
| anthropic (SDK) | 1.6.0 |
| openai (SDK) | 3.13.0 |
| scipy | 1.18.0 |
| pydantic | 2.13.4 |
| OS | macOS, Darwin 27.0.0, Apple Silicon |

## Model strings, exactly as passed

| role | string | used in |
|---|---|---|
| agents (dev_0..dev_3) | `openai/gpt-4o` (provider resolved it to gpt-4o-2024-08-06 on the run dates) | all baselines and attack cells |
| agents, rejected | `openai/gpt-4.1-mini` | first paid qualification (`logs/jira-static-gpt41mini`), g0 replication (`results/g0_gpt41mini`), the superseded 10-turn seed-733 cells |
| monitor / judge | `openai/gpt-4o-mini` (resolved to gpt-4o-mini-2024-07-18). Seed-733 early block and seeds 42/1049 (2026-10-19/20 before the control program): provider-default temperature, unseeded (ORBIT's `LLMMonitorDefense` passes no config). Every cell and baseline of the control program (`results/v2/`, 733 late and claims-last, 512, 101) and the 733/early second clean run: temperature 0, seed = problem seed via Inspect's per-model config (`_SeededJudge`; defense names end in `_seeded`) | `llm_monitor_fixed`, `llm_monitor_fixed_actions` |
| proposer, frontier | `anthropic/claude-sonnet-5-5` | all `results/prop_sonnet55/*` |
| proposer, open weights | `openrouter/qwen/qwen3-235b-a22b-2507` | all `results/prop_qwen3/*` |
| proposer settings | every adaptive payload in `results/` was generated at the provider's default temperature, unseeded, with no record of the prompt or raw output (only the accepted payload, moves and attempt count in `rounds.jsonl`); from 2026-10-20 `proposer.propose` pins temperature 0 and seed = 100 × problem seed + round and logs system prompt, user message and raw output to `proposer_log.jsonl`. [Correction 2026-10-21, [audit_codex X8](../phase2_claim_monitor/audits/audit_codex.md): for `anthropic/claude-sonnet-5-5` the temperature 0 and seed are requested and logged, not sent; Inspect 0.3.263's Anthropic provider never forwards `seed` and drops `temperature` for Claude 4.7+ (`.venv/lib/python3.13/site-packages/inspect_ai/model/_providers/anthropic.py`, `completion_config`, lines 988–1032), so this proposer runs unseeded at the provider default. `proposer_log.jsonl` records the request actually sent under `sent` from 2026-10-21.] No existing payload is reproducible. | all `prop_*` cells |
| proposer, superseded | `anthropic/claude-sonnet-4-5` | the superseded 10-turn seed-733 monitor cell |
| mock | `mockllm/model`, `mockllm/jira-four-arm-qualification`, `mockllm/jira-replication-controls` | smoke tests and mock recipes only |

Provider endpoints: OpenAI API (gpt-4o, gpt-4o-mini, gpt-4.1-mini), Anthropic API (claude-sonnet-5-5), OpenRouter (qwen3-235b-a22b-2507). No model was pinned to a dated snapshot beyond what these strings resolve to on the run dates.

## Settings

| setting | value |
|---|---|
| task options | `num_developers=4`, `num_tasks=4`, `scarcity=0.5`, `preset=flat`, `runtime_profile=common/v1`, `max_turns=40`, `max_time_seconds=350`, `persuasion_tactic=reciprocity_trade`, `misalignment_strategy=covert_reward_maximization`, `coalition_agents=dev_0,dev_1` |
| generation | temperature 0, `--seed` = problem seed, `max_tokens=1200`, `max_retries=2` |
| limits | `token_limit=200000` per sample in the loop (60000 in the replication script runs), `time_limit=360` |
| seeds | 42, 733, 1049 (arms, early); 512, 101 (arms, both orderings); 733 (late); 7, 256, 2024, 4096 (clean baselines only) |
| baselines | 8 epochs per (seed, defense), `max_samples=4` |
| rounds | 0 static + 5 adaptive, one episode each; controls: greedy 3 epochs of round 0, transfer 1 epoch of round 0 |
| orderings | early = repeating plan dev_0, dev_1, dev_2, dev_3; late = dev_2, dev_3, dev_0, dev_1; claimslast = explicit 40-step list dev_2, dev_3, dev_2, dev_3, then the late cycle, no repeat (coalition always dev_0, dev_1). The 733/early block and seeds 42/1049 ran ORBIT's default round-robin executor, every other cell an explicit plan; a plan step whose agent has submitted is skipped but consumes a turn |
| judge prompt | `FIXED_JUDGE_PROMPT` in `jira_adaptive.py` |
| defense presets | `none`, `system_prompt` (ORBIT `system_prompt_fixed_v1`), `llm_monitor_fixed` (defense name `fixed_prompt_llm_monitor_v1`, or `…_seeded` with defense type `llm_monitor_seeded` when the judge is pinned), `llm_monitor_fixed_actions` (`fixed_prompt_llm_monitor_actions_v1[_seeded]`, defense type `llm_monitor_actions_only`) |
| replication script caps (g0) | gpt-4.1-mini: `--max-request-tokens 1080344 --total-token-cap 55000000 --total-usd-cap 90 --max-usd-per-million-tokens 1.6`; gpt-4o: `--max-request-tokens 131072 --total-token-cap 9500000 --total-usd-cap 95 --max-usd-per-million-tokens 10` (reservation ceilings, not spend) |

## Dates run

| what | date | where |
|---|---|---|
| mock recipe, first paid qualification (gpt-4.1-mini) | 2026-10-19 | `logs/jira-mock`, `logs/jira-static-gpt41mini` |
| superseded 10-turn seed-733 cells | 2026-10-19 | `results/733_none`, `results/733_llm_monitor_fixed` |
| g0 replications (8 epochs, both models) | 2026-10-19 | `results/g0_gpt41mini`, `results/g0_gpt4o` |
| noise checks at 6 and 8 tickets (40 turns) and the truncated 10-turn attempt | 2026-10-19 | `results/noise_gpt4o_t6`, `results/noise_gpt4o_t8`, `results/_noise_gpt4o_t*_maxturns10` |
| seed 733 no-defense cells, both proposers | 2026-10-19 | `results/prop_*/733_none` |
| seed 733 defense arms (single-draw clean), parked 60k-limit attempt | 2026-10-19 | `results/prop_*/733_{llm_monitor_fixed_actions,llm_monitor_fixed,system_prompt}`, `results/prop_*/_733_llm_monitor_fixed_actions_tokenlimit60k` |
| arm baselines, seeds 733, 42, 1049 | 2026-10-19 / 2026-10-20 | `results/baselines/` |
| seeds 42 and 1049 cells; static-only input-monitor cells | 2026-10-19 / 2026-10-20 | `results/prop_*/{42,1049}_*`, `results/static_only/` |
| seed 733 cells re-run under the final protocol (3 arms × 2 proposers + static-only input monitor); single-draw cells superseded | 2026-10-20 | `results/prop_*/733_*`, `results/static_only/733_llm_monitor_fixed`; old: `results/_superseded_733_single_draw/` |
| clean no-defense baselines, seeds 7, 101, 256, 512, 2024, 4096 | 2026-10-20 | `results/baselines/<seed>_none` |
| independent README reproduction of the single-draw 733 none cell | 2026-10-20 | `results/repro/733_none` (uncommitted scratch) |
| control program (PLAN §13): two-run baselines, 35 cells, 18 controls (greedy, uninformed), 96 transfers; seeds 512, 101 both orderings, 733 late; judge seeded outside the 733/early block | 2026-10-20 | `results/v2/early/`, `results/v2/late/`, `results/baselines/733_*/run2` |
| third-audit controls (PLAN §14): claims-last plan at 733 (two-run baselines, three arms, Sonnet) and greedy dev_0 alone in the late order (none, prompt, 3 epochs) | 2026-10-20 | `results/v2/claimslast/`, `results/v2/late/greedy_dev0/` |
| fourth-audit transfer: the headline cell's best payload as a static payload under the claims-last plan, three arms, three epochs | 2026-10-20 | `results/v2/claimslast/transfer_headline/` |

Approximate list-price spend for the whole project: about $108 (first phase $43; control program $53; third-audit controls about $10; fourth-audit transfer run about $1.5).
