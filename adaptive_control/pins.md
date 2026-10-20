# Pins

Everything the results depend on, as run on 2026-10-19 and 2026-10-20 (Asia/Kolkata).

## Code

| item | value |
|---|---|
| ORBIT | 1.0.3, commit `588b303` (tag v1.0.3), https://github.com/wlanderson0/orbit |
| ORBIT source state | unmodified; `pyproject.toml` and `uv.lock` changed only by `uv add matplotlib anthropic` |
| this package | `adaptive_control/` on branch `adaptive-redteam` of the ORBIT clone (upstream base 588b303); first published commit c7c8853, at which the §8 reproduction was run; the commit carrying this file supersedes it |
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
| monitor / judge | `openai/gpt-4o-mini` (resolved to gpt-4o-mini-2024-07-18); judge calls carry no temperature or seed (ORBIT's `LLMMonitorDefense` passes none), so monitor arms are not deterministic | `llm_monitor_fixed`, `llm_monitor_fixed_actions` |
| proposer, frontier | `anthropic/claude-sonnet-5-5` | all `results/prop_sonnet55/*` |
| proposer, open weights | `openrouter/qwen/qwen3-235b-a22b-2507` | all `results/prop_qwen3/*` |
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
| orderings | early = plan dev_0, dev_1, dev_2, dev_3; late = dev_2, dev_3, dev_0, dev_1 (coalition always dev_0, dev_1) |
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

Approximate list-price spend for the whole project: about $96 (first phase $43; 2026-10-20 control program $53: 45 two-run baselines, 35 cells, 18 controls, 96 transfers).
