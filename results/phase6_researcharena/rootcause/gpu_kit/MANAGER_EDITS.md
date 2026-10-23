# Manager edits to Fable's kit (PLAN Amendment (13), 2026-10-23)

Fable's second fix pass was refused (Anthropic API, category cyber, $0.02, not retried). On the owner's approval the manager
made these edits to the kit copied from `fix_fable/out/`. Opus, through the restricted reviewer key, checks them.

| # | Item (review_opus_recheck.md) | Change | Where |
|---|---|---|---|
| 1 | C2s inherits the 300 s cut | `T_C2S=900`. `arm_C2s` passes `SAN_TIMEOUT=$T_C2S` into `sanitizer_min`, which uses it in place of T_CS; the information arms keep `T_CS=300`. The driver's table and the environment it passes to the pod carry `T_C2S` too. | run_arms.sh:25, :131, :147, :66; drive_session.sh:18, :27, :52 |
| 2 | no host-key option | `-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$LOCAL_OUT/known_hosts`, with BatchMode kept. The same `$SSH` is used by rsync. | drive_session.sh:22 |
| 3 | empty sanitizer log reads as PASS | C2s/C3s: when the tool ran, an empty or missing log, a log without `ERROR SUMMARY`, or a tool error is FAIL, and PASS requires `ERROR SUMMARY: 0 errors`. Only `NO_SANITIZER`, which run_arms.sh writes when the tool is absent, keeps the earlier launch-count PASS. That path is unchanged on purpose: changing it would change rule A beyond the approved items. | gate.py:180-187 |
| 4 | missing fixtures; ALL_PASS not recorded | New fixtures: C2s_invalid, C2s_emptylog, C2s_nosummary, C2s_toolerror, C2s_notool, decision_fail_c2only (C2 alone fails), decision_fail_c2sonly (C2s alone fails). New `checks.txt` holds 15 regex assertions on the decision lines and the C2s reasons. `gate_selftest.sh` writes its whole run to `raw/gate_selftest_output.txt`. Result: 41 fixtures, 15 line checks, `ALL_PASS`, on both the Mac and the CPU pod. | raw/gate_selftest/, scripts/gate_selftest.sh |
| 5a | preflight and gpu_ok have no overall timeout | Every arm, preflight included, now runs under an overall limit (`arm_limit`; preflight `T_PRE=420`). Inside preflight: sanitizer smoke 300→120 s, `curl --max-time 90`, nvcc canary compile `timeout 120`. `gpu_ok`: `timeout 60` on nvidia-smi and `timeout 120` on the torch probe. | run_arms.sh:25, :61-62, :64-73, :102, :105, :109 |
| 5b | an overrunning arm keeps running on the pod | Each arm runs as `setsid bash run_arms.sh __inner <ARM>`. The outer loop polls it and, at the arm's limit, kills the whole session (`pkill -TERM -s`, then `-KILL`). The session is used instead of the process group because nested GNU `timeout` puts each child in its own process group. The killed arm is gated on its partial logs as rc 124. Leftovers of an earlier arm's session are killed before the next arm starts. Live test on the CPU pod: a 120 s sleep arm with a 6 s limit was killed at 6 s and gated, and no sleep process was left. | run_arms.sh:212-242 |
| 6 | drop C1b | Removed from the default order: preflight C0 C1s C2 C2s C1r C1a C1c C2cs C2c C2cr C2r C2a C3a C3 C3s. The arm function stays but is not called. | run_arms.sh:244-245 |
| 7 | `debug8_cause_reproduced` overstated | Replaced by two lines. `stock_crashes_under_C2_conditions` comes from C1s only and names no kernel. `debug8_cause_attributed_to_RoPE` is YES only when C1c's first failing launch is RoPE, or C1b's memcheck names `rotary_embedding_kernel`; NO when C1c or C1b names another kernel; otherwise UNDECIDED. Rule A is unchanged (C1s, C2 and C2s only). | gate.py:225-237 |

Syntax checks: `bash -n` on run_arms.sh, drive_session.sh and gate_selftest.sh, and `py_compile` on gate.py, all clean.

Session estimate at $3.99/h: about 5 min of pod setup, then the arms, about 50 min in practice. The deadline is minute 55
from allocation, and an arm is skipped if its full timeout no longer fits before then. The latest possible end is about
minute 59-62 (the last arm's limit plus the kill grace and rsync), under the 75-minute / $5 watchdog. Expected cost $3.3-4.0;
ceiling $4.99. The starter-kernel guard is compile-checked only: the benchmark never loads starter kernels on these pods.

## Round 2 (Amendment (15), 2026-10-23): fix round for the last session

| Owner item | Change | Where | Test |
|---|---|---|---|
| Fix the cache path | `mirror_hf_cache`: for each model pod_setup cached under `$HF_HOME/hub/models--*`, a symlink `$HF_HOME/models--*`, which is where bench.py looks with `cache_dir=$HF_HOME`. The offline flag stays. | run_arms.sh (after the HF_HUB_OFFLINE export) | CPU pod, TinyLlama cached exactly as pod_setup does: without the mirror, bench.py's `load_model_and_tokenizer` fails offline with the void run's `LocalEntryNotFoundError`; with it, `[bench] Model loaded (1100M params)` and `MODEL_LOAD_OK` (`/root/scratch/rootcause/cache_test.sh`). |
| Preflight loads the model offline exactly as bench.py does | Preflight copies a fresh task_context and runs bench.py's own `load_model_and_tokenizer(ArenaConfig())` with `HF_HUB_OFFLINE=1`; gate.py requires `MODEL_LOAD_OK`. `T_PRE` is 600. | run_arms.sh preflight; gate.py preflight | gate fixtures |
| Abort and delete on a failed preflight or C0 | After any non-PASS preflight or C0, drive_session.sh runs no further arm: each is recorded `NOT_RUN: session aborted (...)`, the decision is printed, and the driver exits. The manager's watcher deletes the pod when the driver exits. | drive_session.sh | `scripts/abort_selftest.sh` (fake ssh/rsync, on the CPU pod): C0 FAIL → only preflight and C0 requested, 8 arms NOT_RUN, rule_A VOID; preflight FAIL → only preflight, 9 NOT_RUN. ALL_PASS. |
| INVALID and VOID verdicts | An arm that loads the model but shows no load marker (`[bench] Model loaded`, `MIN_INJECTED`, `C0_BASELINE_TPS=`, `KL: baseline_div`) is INVALID, flagged as an "offline model-cache miss" when the log says so. Rule A and option 2 are VOID if any of their arms is INVALID or NOT_RUN; `stock_crashes_under_C2_conditions` is then UNDECIDED. | gate.py | 6 fixtures from the real void-run logs (C0, C1s, C2, C2s, C1a, C2cs) → INVALID; decision fixtures for VOID (an INVALID arm; aborted arms). |
| Re-root option 2 and point the upstream arms at it | `opt2_task_context.patch` holds kernels/rotary_embedding.cu, starter_kernels/rotary_embedding.cu and inject.py (RoPE hunks only), rooted at task_context; it applies with `patch -p1 --dry-run` inside a stock task_context. The `rope_correct` variant (C2c, C2cs, C2cr, C2cm, C2ce) now applies it, replacing `rope_correct_11ea904.patch`. | run_arms.sh apply_variant; gate.py patch checks | dry-run apply; fixtures |
| Memory-check arm on the full model path | **C2cm**: option 2 kernels under compute-sanitizer memcheck on the full model path (c_minimal_kernels.py, all four ops, 8 new tokens, 900 s). It must run RoPE on every launch with 0 swallowed exceptions and `ERROR SUMMARY: 0 errors`. | run_arms.sh arm_C2cm; gate.py | C2cm fixtures (PASS, invalid access, empty log, wrong patch) |
| Fallback-counting arm on the full model path | **C2cs** with the option 2 patch: 8 prompts × 32 tokens, once RoPE-only and once with all ops, counting calls and swallowed exceptions per op. **Pre-registered here:** option 2 changes RoPE only, so its numerics gate is the RoPE-only run (8/8 equal to C0). Both runs must show RoPE on every launch with 0 fallbacks. The all-ops token match involves the other three stock kernels and is reported, not gated (fixture C2cs_allfail now PASS with that note). | gate.py C2cs | C2cs fixtures |
| The embedded-evaluator check | **C2ce** (`c_embedded_check.py`) runs `embedded`'s own `_compute_embedded_kl(task_dir)` on the option 2 task_context with `bench.compile_kernels` wrapped, so every RoPE call and swallowed exception of the agent and starter modules is counted. It then runs option 2's `embedded3` `_probe_rope` and `_is_landmine`. PASS needs: both KL means < 1e-3, RoPE called with 0 errors in every module, embedded3 fp16 error under its tolerance, and no landmine. Reported in the decision; not part of option 2's pass rule. | c_embedded_check.py, run_arms.sh arm_C2ce, gate.py | C2ce fixtures (PASS, fallback, KL, landmine, unloaded → INVALID) |
| Overstated lines and the error count | C1a now prints INVALID when the model never loaded, instead of "did not reproduce". `stock_crashes…` is UNDECIDED unless C1s is PASS or FAIL. ERROR SUMMARY parsing ignores the "N errors were not printed" line, so C1r's count is 768, not 568. The void session's own SUMMARY is corrected in its CORRECTIONS.md. | gate.py; gpu_session/arms_20261023T110613Z/CORRECTIONS.md | fixtures |
| Decision | rule_A PASS/FAIL/VOID from C1s, C2, C2s. option_2 PASS/FAIL/VOID from C2c, C2cm, C2cs. A final line applies Amendment (15) item 4: "at least one baseline passes", or "neither baseline passes" (both FAIL), or a VOID left for the owner. | gate.py decision | decision fixtures |

Self-tests on the CPU pod, all recorded in raw/:
- gate: 63 fixtures, 39 line checks, ALL_PASS;
- limits: C2s inner 900 s inside outer 960 s, with a live time-scaled check;
- abort: ALL_PASS;
- kill test: the overrunning arm was killed at its limit, 0 processes left.

`bash -n` is clean on every script, and `py_compile` on gate.py and c_embedded_check.py.

**Session plan** (Amendment (15)):
- one pod, standard image;
- watchdog $6 / 90 min; driver deadline 80 min from allocation;
- arms: preflight C0 C1s C2 C2s C2c C2cm C2cs C2ce C2cr.

Expected arm times after about 15 min of setup: preflight about 4, C0 3, C1s 4, C2 6, C2s 10, C2c 6, C2cm 10, C2cs 5,
C2ce 8, C2cr 2. That is about 58 min of arms, so the session should end around minute 73. An arm whose limit plus 60 s
no longer fits before minute 80 is skipped as NOT_RUN. The expected cost is about $4.9; the ceiling is $6.
