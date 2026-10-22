# Legacy absolute paths in tracked run artifacts (2026-10-22)

Owner's decision (c) of 2026-10-22 (STATUS.md decisions log; SOP check items T1.12, T2.6, T3.9, T4.6):
absolute paths in the tracked **JSON / JSONL** driver artifacts of Phases 1–4 were rewritten to
repository-relative paths; the **`.out` runner logs** keep their absolute paths and are listed here as
legacy output. No `.eval` log, no code and no table was touched. Done by the p14-paths session on the pod,
no model call.

## Rule

- A `.out` file is runner output (SOP §3: beside the log directory, never cited for spend). The files in
  the table below contain the pre-standalone Mac paths. They enter no table, are never cited for a path or a
  number, and are not edited (SOP §3: no log edited, moved or deleted). A reader who needs the log they
  name maps `/Users/hemant/Desktop/Defense RSI/control-loop/` to the repository root and
  `/Users/hemant/Desktop/Defense RSI/orbit/results/` to `results/` (Phase 1 and the first Phase 2 cells ran inside the ORBIT clone before
  `63a9ed5` made this repository standalone; the logs are tracked here under the same path below `results/`).
- Every path written from now on goes through `control_loop/paths.py` (`rel_text`, `write_json`, `json_line`).

## JSON / JSONL files rewritten

Byte-level string replacement on the raw text (no JSON re-serialisation: key order, spacing, numbers and
NaN values untouched); each file parsed before and after, and every difference was verified to be a string
whose only change is the root prefix. Roots replaced, in this order:

| root | replaced by | occurrences |
|---|---|---|
| `/Users/hemant/Desktop/Defense RSI/control-loop/` (bare root → `.`) | repository root | 79 |
| `/root/control-loop/` (bare root → `.`) | repository root | 0 |
| `/Users/hemant/Desktop/Defense RSI/orbit/` (bare root → `../orbit`) | `../orbit/` (the ORBIT clone, a sibling repository) | 1638 |

Of the 864 distinct `../orbit/results/...` paths now written, 774 exist in this repository as the same path under `results/`
(the remaining 90 name logs that were never copied here).

| phase | files | changed lines | directories (files) |
|---|---|---|---|
| 1 | 448 | 1484 | `results/733_llm_monitor_fixed` (2), `results/733_none` (1), `results/_superseded_733_single_draw` (8), `results/baselines_meta` (18), `results/g0_gpt41mini` (1), `results/g0_gpt4o` (1), `results/prop_qwen3` (19), `results/prop_sonnet55` (19), `results/repro` (2), `results/static_only` (6), `results/v2` (371) |
| 2 | 24 | 49 | `results/phase2_claim_monitor` (24) |
| 3 | 24 | 64 | `results/phase3_allocation_monitor` (24) |
| total | 496 | 1597 | 1717 string values |

File kinds: `baseline.json`, `rounds.jsonl`, `results/v2/driver_*.json`, `replication.json`. The per-file
unified diffs and the inventory (`json_files.txt`, `out_files.txt`, `summary_apply.json`) are in the pod's
scratch directory `scratch/p14-paths/` outside the repository. Count note: the Phase 1 SOP check (T1.12)
counted 256 json + jsonl files; the grep `-e /Users/hemant -e /root/control-loop` over `results/` finds
448 for Phase 1 (the audit's `.out` counts 262 / 0 / 20 / 3 are reproduced exactly).

## Decision (d): the uv `.env` parse warning in `.out` files

uv printed `warning: Failed to parse environment file \`../.env\` at position 2` followed (STATUS.md open question, 2026-10-20) by a fragment of the
old `.env`; the whole was one line of 90 characters in `60b4dcd`. Commit `5fb6ab5` (2026-10-21, "results: strip uv .env-parse warning line from
.out logs") removed that one line from every affected `.out` file (one or two lines per file). At `8c30063`
no tracked file contains the warning or any `.env` content (checked with `git grep`; the two mentions in
`STATUS.md` and `results/spend_2026-10-20.md` quote the warning's prefix only). The line remains in the
history of the commits that introduced those files (`63a9ed5`, `60b4dcd`, `f10c15f`, `2fb1268`, `994a7fa`,
`3fe0819`); rewriting history is the owner's call (T3.9), not an agent's. Nothing was scrubbed by this session
because nothing remained in the working tree; the secret fragment was not read or printed.

## `.out` files kept as legacy runner output

| phase | files | lines with an absolute path |
|---|---|---|
| 1 | 262 | 1534 |
| 3 | 20 | 130 |
| 4 | 3 | 3 |
| total | 285 | 1667 |

| file | phase | roots it contains | lines |
|---|---|---|---|
| `results/733_llm_monitor_fixed.attempt2.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/733_llm_monitor_fixed.out` | 1 | orbit, uv cache (~/.local/share/uv), Defense RSI (truncated by the runner) | 26 |
| `results/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/_damaged/101_llm_monitor_fixed_actions_run2.out` | 1 | orbit, Defense RSI (truncated by the runner) | 36 |
| `results/_superseded_733_single_draw/prop_qwen3/733_llm_monitor_fixed.out` | 1 | orbit, Defense RSI (truncated by the runner) | 18 |
| `results/_superseded_733_single_draw/prop_qwen3/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 18 |
| `results/_superseded_733_single_draw/prop_qwen3/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 18 |
| `results/_superseded_733_single_draw/prop_qwen3/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 18 |
| `results/_superseded_733_single_draw/prop_sonnet55/733_llm_monitor_fixed.out` | 1 | orbit, Defense RSI (truncated by the runner) | 18 |
| `results/_superseded_733_single_draw/prop_sonnet55/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 18 |
| `results/_superseded_733_single_draw/prop_sonnet55/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 18 |
| `results/_superseded_733_single_draw/prop_sonnet55/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 18 |
| `results/baselines_meta/101_none.out` | 1 | orbit | 1 |
| `results/baselines_meta/1049_llm_monitor_fixed.out` | 1 | orbit | 1 |
| `results/baselines_meta/1049_llm_monitor_fixed_actions.out` | 1 | orbit | 1 |
| `results/baselines_meta/1049_none.out` | 1 | orbit | 1 |
| `results/baselines_meta/1049_system_prompt.out` | 1 | orbit | 1 |
| `results/baselines_meta/2024_none.out` | 1 | orbit | 1 |
| `results/baselines_meta/256_none.out` | 1 | orbit | 1 |
| `results/baselines_meta/4096_none.out` | 1 | orbit | 1 |
| `results/baselines_meta/42_llm_monitor_fixed.out` | 1 | orbit | 1 |
| `results/baselines_meta/42_llm_monitor_fixed_actions.out` | 1 | orbit | 1 |
| `results/baselines_meta/42_none.out` | 1 | orbit | 1 |
| `results/baselines_meta/42_system_prompt.out` | 1 | orbit | 1 |
| `results/baselines_meta/512_none.out` | 1 | orbit | 1 |
| `results/baselines_meta/733_llm_monitor_fixed.out` | 1 | orbit | 1 |
| `results/baselines_meta/733_llm_monitor_fixed_actions.out` | 1 | orbit | 1 |
| `results/baselines_meta/733_none.out` | 1 | orbit | 1 |
| `results/baselines_meta/733_system_prompt.out` | 1 | orbit | 1 |
| `results/baselines_meta/7_none.out` | 1 | orbit | 1 |
| `results/g0_gpt41mini.out` | 1 | orbit | 1 |
| `results/g0_gpt4o.out` | 1 | orbit | 1 |
| `results/phase3_allocation_monitor/check_llm.out` | 3 | control-loop | 5 |
| `results/phase3_allocation_monitor/check_rule.out` | 3 | control-loop | 5 |
| `results/phase3_allocation_monitor/early_512_allocation_llm_autoallow.out` | 3 | control-loop | 13 |
| `results/phase3_allocation_monitor/early_512_allocation_llm_autoallow_run2.out` | 3 | control-loop | 1 |
| `results/phase3_allocation_monitor/early_512_allocation_rule_autoallow.out` | 3 | control-loop | 13 |
| `results/phase3_allocation_monitor/early_512_allocation_rule_autoallow_run2.out` | 3 | control-loop | 1 |
| `results/phase3_allocation_monitor/early_733_allocation_llm_autoallow.out` | 3 | control-loop | 13 |
| `results/phase3_allocation_monitor/early_733_allocation_llm_autoallow_run2.out` | 3 | control-loop | 1 |
| `results/phase3_allocation_monitor/early_733_allocation_rule_autoallow.out` | 3 | control-loop | 13 |
| `results/phase3_allocation_monitor/early_733_allocation_rule_autoallow_run2.out` | 3 | control-loop | 1 |
| `results/phase3_allocation_monitor/late_512_allocation_llm_autoallow.out` | 3 | control-loop | 13 |
| `results/phase3_allocation_monitor/late_512_allocation_llm_autoallow_run2.out` | 3 | control-loop | 1 |
| `results/phase3_allocation_monitor/late_512_allocation_rule_autoallow.out` | 3 | control-loop | 13 |
| `results/phase3_allocation_monitor/late_512_allocation_rule_autoallow_run2.out` | 3 | control-loop | 1 |
| `results/phase3_allocation_monitor/late_733_allocation_llm_autoallow.out` | 3 | control-loop | 13 |
| `results/phase3_allocation_monitor/late_733_allocation_llm_autoallow_run2.out` | 3 | control-loop | 1 |
| `results/phase3_allocation_monitor/late_733_allocation_rule_autoallow.out` | 3 | control-loop | 13 |
| `results/phase3_allocation_monitor/late_733_allocation_rule_autoallow_run2.out` | 3 | control-loop | 1 |
| `results/phase3_allocation_monitor/sweep_llm.out` | 3 | control-loop | 4 |
| `results/phase3_allocation_monitor/sweep_rule.out` | 3 | control-loop | 4 |
| `results/phase4_controlarena/_attempt1_eot_overwrite/mechanism_check_real.out` | 4 | control-loop | 1 |
| `results/phase4_controlarena/mechanism_check_mock.out` | 4 | control-loop | 1 |
| `results/phase4_controlarena/mechanism_check_real.out` | 4 | control-loop | 1 |
| `results/prop_qwen3/1049_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_qwen3/1049_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_qwen3/1049_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_qwen3/42_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_qwen3/42_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_qwen3/42_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_qwen3/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_qwen3/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_qwen3/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_qwen3/_733_llm_monitor_fixed_actions_tokenlimit60k.out` | 1 | orbit, Defense RSI (truncated by the runner) | 4 |
| `results/prop_sonnet55/1049_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_sonnet55/1049_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_sonnet55/1049_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_sonnet55/42_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_sonnet55/42_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_sonnet55/42_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_sonnet55/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_sonnet55/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_sonnet55/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/prop_sonnet55/_733_llm_monitor_fixed_actions_tokenlimit60k.out` | 1 | orbit, Defense RSI (truncated by the runner) | 7 |
| `results/static_only/1049_llm_monitor_fixed.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/static_only/42_llm_monitor_fixed.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/static_only/733_llm_monitor_fixed.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/claimslast/baselines_meta/733_llm_monitor_fixed_actions_run1.out` | 1 | orbit | 1 |
| `results/v2/claimslast/baselines_meta/733_llm_monitor_fixed_actions_run2.out` | 1 | orbit | 1 |
| `results/v2/claimslast/baselines_meta/733_none_run1.out` | 1 | orbit | 1 |
| `results/v2/claimslast/baselines_meta/733_none_run2.out` | 1 | orbit | 1 |
| `results/v2/claimslast/baselines_meta/733_system_prompt_run1.out` | 1 | orbit | 1 |
| `results/v2/claimslast/baselines_meta/733_system_prompt_run2.out` | 1 | orbit | 1 |
| `results/v2/claimslast/prop_sonnet55/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 12 |
| `results/v2/claimslast/prop_sonnet55/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/claimslast/prop_sonnet55/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/claimslast/transfer_headline/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/claimslast/transfer_headline/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/claimslast/transfer_headline/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/baselines_meta/101_llm_monitor_fixed_actions_run1.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/101_llm_monitor_fixed_actions_run2.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/101_llm_monitor_fixed_run1.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/101_llm_monitor_fixed_run2.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/101_none_run1.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/101_none_run2.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/101_system_prompt_run1.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/101_system_prompt_run2.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/512_llm_monitor_fixed_actions_run1.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/512_llm_monitor_fixed_actions_run2.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/512_llm_monitor_fixed_run1.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/512_llm_monitor_fixed_run2.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/512_none_run1.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/512_none_run2.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/512_system_prompt_run1.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/512_system_prompt_run2.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/733_llm_monitor_fixed_actions_run2.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/733_llm_monitor_fixed_run2.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/733_none_run2.out` | 1 | orbit | 1 |
| `results/v2/early/baselines_meta/733_system_prompt_run2.out` | 1 | orbit | 1 |
| `results/v2/early/greedy/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/greedy/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/greedy/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/greedy/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/greedy/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/greedy/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/prop_qwen3/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 12 |
| `results/v2/early/prop_qwen3/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/early/prop_qwen3/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/early/prop_qwen3/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 12 |
| `results/v2/early/prop_qwen3/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/early/prop_qwen3/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/early/prop_sonnet55/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 12 |
| `results/v2/early/prop_sonnet55/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/early/prop_sonnet55/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/early/prop_sonnet55/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 12 |
| `results/v2/early/prop_sonnet55/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/early/prop_sonnet55/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/early/prop_sonnet55_uninformed/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 12 |
| `results/v2/early/prop_sonnet55_uninformed/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/early/prop_sonnet55_uninformed/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/early/prop_sonnet55_uninformed/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/early/prop_sonnet55_uninformed/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/early/prop_sonnet55_uninformed/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/early/static_only/101_llm_monitor_fixed.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/static_only/512_llm_monitor_fixed.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/transfer/from_101_prop_qwen3/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/transfer/from_101_prop_qwen3/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_101_prop_qwen3/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/transfer/from_101_prop_qwen3/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_101_prop_qwen3/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_101_prop_qwen3/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_101_prop_qwen3/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_101_prop_qwen3/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_101_prop_sonnet55/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/transfer/from_101_prop_sonnet55/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_101_prop_sonnet55/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/transfer/from_101_prop_sonnet55/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_101_prop_sonnet55/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_101_prop_sonnet55/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_101_prop_sonnet55/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_101_prop_sonnet55/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_512_prop_qwen3/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/transfer/from_512_prop_qwen3/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_512_prop_qwen3/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_512_prop_qwen3/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/transfer/from_512_prop_qwen3/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_512_prop_qwen3/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_512_prop_qwen3/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_512_prop_qwen3/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_512_prop_sonnet55/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/transfer/from_512_prop_sonnet55/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_512_prop_sonnet55/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_512_prop_sonnet55/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/transfer/from_512_prop_sonnet55/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_512_prop_sonnet55/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_512_prop_sonnet55/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_512_prop_sonnet55/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_733_prop_qwen3/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/transfer/from_733_prop_qwen3/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_733_prop_qwen3/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_733_prop_qwen3/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/transfer/from_733_prop_qwen3/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_733_prop_qwen3/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_733_prop_qwen3/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_733_prop_qwen3/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_733_prop_sonnet55/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/transfer/from_733_prop_sonnet55/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_733_prop_sonnet55/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_733_prop_sonnet55/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/early/transfer/from_733_prop_sonnet55/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_733_prop_sonnet55/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_733_prop_sonnet55/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/early/transfer/from_733_prop_sonnet55/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/baselines_meta/101_llm_monitor_fixed_actions_run1.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/101_llm_monitor_fixed_actions_run2.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/101_llm_monitor_fixed_run1.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/101_llm_monitor_fixed_run2.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/101_none_run1.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/101_none_run2.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/101_system_prompt_run1.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/101_system_prompt_run2.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/512_llm_monitor_fixed_actions_run1.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/512_llm_monitor_fixed_actions_run2.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/512_llm_monitor_fixed_run1.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/512_llm_monitor_fixed_run2.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/512_none_run1.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/512_none_run2.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/512_system_prompt_run1.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/512_system_prompt_run2.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/733_llm_monitor_fixed_actions_run1.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/733_llm_monitor_fixed_actions_run2.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/733_llm_monitor_fixed_run1.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/733_llm_monitor_fixed_run2.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/733_none_run1.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/733_none_run2.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/733_system_prompt_run1.out` | 1 | orbit | 1 |
| `results/v2/late/baselines_meta/733_system_prompt_run2.out` | 1 | orbit | 1 |
| `results/v2/late/greedy/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/greedy/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/greedy/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/greedy/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/greedy/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/greedy/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/greedy_dev0/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/greedy_dev0/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/prop_qwen3/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 12 |
| `results/v2/late/prop_qwen3/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/late/prop_qwen3/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/late/prop_qwen3/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 12 |
| `results/v2/late/prop_qwen3/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/late/prop_qwen3/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/late/prop_qwen3/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 12 |
| `results/v2/late/prop_qwen3/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/late/prop_qwen3/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/late/prop_sonnet55/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 12 |
| `results/v2/late/prop_sonnet55/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/late/prop_sonnet55/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/late/prop_sonnet55/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 12 |
| `results/v2/late/prop_sonnet55/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/late/prop_sonnet55/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/late/prop_sonnet55/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 12 |
| `results/v2/late/prop_sonnet55/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/late/prop_sonnet55/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 17 |
| `results/v2/late/static_only/101_llm_monitor_fixed.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/static_only/512_llm_monitor_fixed.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/static_only/733_llm_monitor_fixed.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_101_prop_qwen3/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_101_prop_qwen3/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_101_prop_qwen3/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_101_prop_qwen3/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_101_prop_qwen3/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_101_prop_qwen3/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_101_prop_qwen3/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_101_prop_qwen3/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_101_prop_sonnet55/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_101_prop_sonnet55/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_101_prop_sonnet55/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_101_prop_sonnet55/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_101_prop_sonnet55/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_101_prop_sonnet55/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_101_prop_sonnet55/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_101_prop_sonnet55/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_512_prop_qwen3/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_512_prop_qwen3/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_512_prop_qwen3/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_512_prop_qwen3/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_512_prop_qwen3/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_512_prop_qwen3/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_512_prop_qwen3/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_512_prop_qwen3/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_512_prop_sonnet55/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_512_prop_sonnet55/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_512_prop_sonnet55/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_512_prop_sonnet55/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_512_prop_sonnet55/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_512_prop_sonnet55/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_512_prop_sonnet55/733_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_512_prop_sonnet55/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_733_prop_qwen3/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_733_prop_qwen3/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_733_prop_qwen3/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_733_prop_qwen3/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_733_prop_qwen3/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_733_prop_qwen3/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_733_prop_qwen3/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_733_prop_qwen3/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_733_prop_sonnet55/101_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_733_prop_sonnet55/101_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_733_prop_sonnet55/101_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_733_prop_sonnet55/512_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_733_prop_sonnet55/512_none.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_733_prop_sonnet55/512_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |
| `results/v2/late/transfer/from_733_prop_sonnet55/733_llm_monitor_fixed_actions.out` | 1 | orbit, Defense RSI (truncated by the runner) | 2 |
| `results/v2/late/transfer/from_733_prop_sonnet55/733_system_prompt.out` | 1 | orbit, Defense RSI (truncated by the runner) | 3 |

## Pre-commit hygiene of the uncommitted tree, 2026-10-22 (task precommit-hygiene; no pod, no model call, $0)

Scope: every path in `git status --short --untracked-files=all` on the pod at the time. Placeholders used from
now on in prose: repository paths are repository-relative; `../.env` (the project `.env`); `<pod home>/x` (any
other file in the pod user's home, e.g. `<pod home>/.runpod.env`, `<pod home>/opencode.json`);
`$RESEARCHARENA_ROOT` (the pinned ResearchArena checkout); `$P6_ARENA_ROOT` (the Phase 6 composed root on the
CPU pod); `<session scratch>/` (a session's scratch directory outside the repository).

### Prose rewritten (string replacement; originals kept in the pod's scratch `precommit-hygiene/prose_orig/`)

| file | occurrences |
|---|---|
| `STATUS.md` | 22 |
| `phases/phase6_researcharena/FINDINGS.md` | 15 |
| `phases/phase6_researcharena/PLAN.md` | 1 |
| `phases/phase6_researcharena/pins.md` | 4 |
| `phases/phase4_controlarena/audits/sop_check.md` | 1 |
| `phases/phase5_claim_protocol/audits/RESPONSE.md` | 1 |
| `phases/phase8_transcript_monitor/audits/sop_check.md` | 2 |
| `results/phase6_researcharena/sweep/qwen3_733_run2/CHECK_BYHAND.md` | 5 |
| total | 51 |

Four `RESEARCHARENA_ROOT=<checkout>` mentions now read `` `$RESEARCHARENA_ROOT` ``. Tests: `tests/test_results_store_fallback.py`
reads the Phase 5 mock-log directory from `P5_MOCK_LOGS` (skipped when unset); `tests/test_researcharena_adapter.py`
and `tests/test_researcharena_sweep.py` use a `tmp_path` root and `/srv/other` for their placeholder arguments.

### Phase 6 run logs rewritten (byte-level prefix replacement, as for Phases 1–4 above)

Roots, in this order: `/root/control-loop/` → repository root; `/root/src/ResearchArena` → `$RESEARCHARENA_ROOT`;
`/root/phase6_arena_root` → `$P6_ARENA_ROOT`; any other `/root/` → `<pod home>/`. Each file parsed before and
after; every difference is a string whose only change is these prefixes; key order, spacing and numbers untouched.
Per-file unified diffs, the originals and `summary_apply.json` are in the pod's scratch `precommit-hygiene/logs/`.

| file | changed lines | changed strings | roots |
|---|---|---|---|
| `results/phase6_researcharena/smoke/run.jsonl` | 2 | 2 | `<pod home>/` (the runpodctl ssh key path in two dry-run notes) |
| `results/phase6_researcharena/smoke2/run.jsonl` | 2 | 2 | `<pod home>/` (same) |
| `results/phase6_researcharena/sweep/qwen3_733/run.jsonl` | 4 | 4 | `$P6_ARENA_ROOT` |
| `results/phase6_researcharena/sweep/qwen3_733_run2/run.jsonl` | 4 | 4 | `$P6_ARENA_ROOT` |
| `results/phase6_researcharena/sweep/qwen3_733/arena_root_manifest.json` | 2 | 2 | `$RESEARCHARENA_ROOT`, `$P6_ARENA_ROOT` |
| `results/phase6_researcharena/sweep/qwen3_733_run2/arena_root_manifest.json` | 2 | 2 | `$RESEARCHARENA_ROOT`, `$P6_ARENA_ROOT` |
| total | 16 | 16 | |

Manifest hash: `pins.md` and `CHECK_BYHAND.md` cite the manifest's SHA-256 as `b571fc680b59…00661`. That is
the hash of the bytes as written (both copies identical). After the rewrite the two copies hash to
`df602820c5dd200afaabc1db658df7ef915b613d7f1a66c63d727b5c71d5128e`. The cited hash is recovered exactly by the
reverse substitution (`$RESEARCHARENA_ROOT` → `/root/src/ResearchArena`, `$P6_ARENA_ROOT` →
`/root/phase6_arena_root`). Checked with `sha256sum` on 2026-10-22.

### Intended absolute paths (container and scanner), 2026-10-22

These hits of `grep -E '/root/|/Users/'` are deliberate. The SOP §8 item 7 check lists them as intended, not as gaps.

| file | what the path is |
|---|---|
| `docker/phase6/scan_image.py` | the scanner's search string `/root/` and its docstring |
| `docker/phase6/Dockerfile` | container paths inside the image (`/root/.npm`, `/root/.cache/...`, `/root/.config/opencode`, ... removed in the image; the scan stage's `--forbid` credential paths) |
| `docker/phase6/README.md` | the same container credential paths and the scan rule, described |
| `.github/workflows/phase6-image.yml` | comment describing the scan's `/root/` rule |
| `tests/test_researcharena_pods.py` | the image scanner's test fixtures (strings the scanner must flag or pass) |
| `docs/SOP.md` | the §8 item 7 grep pattern |
| `phases/phase1_orbit_redteam/audits/sop_check.md` (line 25), `phases/phase8_transcript_monitor/audits/sop_check.md` (line 153) | the same grep pattern, quoted |
| `docs/legacy_absolute_paths.md` | this file: the legacy Mac roots it maps for the `.out` logs |

Container and RunPod-pod paths that exist only inside the image or on a GPU pod (`/workspace/...`, `/opt/...`,
`/etc/p6_image.json`, `/etc/rp_environment`) are intended too and do not match the grep.

### Verbatim third-party text, kept as written

Model or auditor output quoted verbatim (SOP §7: an audit is never edited): `phases/phase5_claim_protocol/audits/audit_codex.md`
(3 lines), `phases/phase8_transcript_monitor/audits/audit_codex.md` (6), `phases/phase8_transcript_monitor/audits/audit_claude.md` (1).

### Runner logs kept as written

`results/phase6_researcharena/sweep/qwen3_733/driver.log` and `.../qwen3_733_run2/driver.log` (3 lines each,
`verify_root ok:` followed by the composed root's pod path). They are logs: not edited (SOP §3), never cited for
a path. `.eval` files are excluded from the check as before.

### Nested git repositories in Phase 6 snapshots

Four collected snapshots carry ResearchArena's task git metadata:
`results/phase6_researcharena/sweep/qwen3_733_run2/{clean/run1/e1,rounds/r0a/e1,rounds/r0a/e2,rounds/r0a/e3}/red_team/task_snapshot/.git`.
Each is about 210 KB with one commit, "Initial starter kernels". They are not moved or deleted. `.gitignore` now has
`results/**/task_snapshot/.git/`, so that metadata stays on the pod and out of the repository. No other `.git`
directory exists under `results/phase5_claim_protocol` or `results/phase6_researcharena`. Git 2.43 still treats a
directory that contains `.git` as an embedded repository, ignored or not. `git add -A` would record each
`task_snapshot/` as a gitlink (a submodule entry with no URL), not as its files. A scratch-repository test on the
pod confirmed this, and an explicit `git add <file inside>` adds nothing. How the snapshot files enter a commit is
the owner's decision (see Phase 6 FINDINGS, 2026-10-22 "Pre-commit hygiene").
