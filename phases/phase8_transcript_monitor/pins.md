# pins — Phase 8: non-agentic transcript monitor (docs/SOP.md §2.5)

Written 2026-10-21 after the primary arm's V1 passes 1–3; updated 2026-10-22 after the finish run (V2 passes 1–3, stratum N,
greedy; owner's decision of 2026-10-22, no gpt-4o arm). Everything below is read from the `.eval` headers, the `ModelEvent`s'
`call.request` and `control_loop.spend.log_cost`; nothing is from memory. Shared with Phase 2 (the §16.12(b) comparator logs
and the `claim_score` events): see `phases/phase2_claim_monitor/pins.md`. Paths in the tables are relative to
`results/phase8_transcript_monitor/`.

## Code

| item | value |
|---|---|
| this package's revision as recorded in every eval header (all 10 logs) | `8c30063` (`origin https://github.com/HemantBK/control-loop.git`), `dirty = True` |
| uncommitted when run | `control_loop/analysis/transcript_monitor.py`, `transcript_render.py`, `transcript_metrics.py`, `control_loop/runlog.py`, `control_loop/status.py`, the Phase 8 tests, `phases/phase8_transcript_monitor/**`, `docs/**`; plus the other sessions' modified files listed in STATUS.md "Uncommitted". The per-step cost fix of 2026-10-21 (`_cost_delta`) was in `transcript_monitor.py` before the finish run and after the V1 passes |
| inspect-ai (eval header `packages`) | 0.3.263 |
| ORBIT (source of the episode logs) | 1.0.3 at commit 588b303, unmodified (`uv.lock`; `phases/phase1_orbit_redteam/README.md` section 2) |
| Python | 3.13.12 (pod venv, `uv run --locked`) |
| OpenAI provider | Inspect's `openai` provider; request path `chat.completions` (`call.request` keys: `model, messages, temperature, seed, max_tokens, tools (null), tool_choice (null), extra_headers`) |
| prompt | `transcript_monitor.MONITOR_PROMPT`, SHA-256 `5b100fe7888a59ccc80e651013e4aca9dbe83125bbb55de863e9984d2a97b6fb`, passed as `-T prompt_sha=` and stored per record (`prompt_sha256`) and per pass (`prompt.txt`); unchanged across all 10 logs |
| rendering hashes | per episode in `judgements.jsonl` (`rendering_sha256`, `n_chars`). V1: identical across the three passes for 1,113 of 1,113 episodes (15,702,407 characters). V2: differs from V1 on all 128 manifest episodes (1,777,642 against 1,902,824 characters) and identical across the three V2 passes on 128 of 128; the 985 other episodes reuse the V1 record. The two check renderings: `check/{v1,v2}/{clean,A0}.sha256` |
| prices | `control_loop/spend.py` PRICES, gpt-4o-mini $0.15 / $0.075 / $0.60 per 1M input / cached input / output, verified against OpenAI's page on 2026-10-21 (`docs/prices_verified_2026-10-21.md`: input, cache read and output equal; cache write not listed by the page and never billed here) |
| tests at the time of writing (2026-10-22, pod) | at the write-up: `uv run --locked pytest -q` 259 passed, 5 skipped, 2 failed (`tests/test_relative_paths.py` ControlArena items, outside this phase), Phase 8's three test files 48 passed; at the audit response (2026-10-22, after `audits/RESPONSE.md`): full suite **275 passed, 5 skipped, 0 failed**; Phase 8's three test files **58 passed** |
| record seeds (`judgements.jsonl`) | `seed` = `source_seed` = the episode's problem seed from the manifest (733 / 512 / 101 / 42 / 1049 / 7 / 256 / 2024 / 4096); `monitor_seed` = the pass seed (8001 / 8002 / 8003). Re-collected offline on 2026-10-22 from the `.eval` logs (audit C1 / X1; before that `seed` carried the pass seed) |

## Model strings, per role

| role | as passed | as resolved by the provider (`ModelEvent.output.model`) | where |
|---|---|---|---|
| transcript monitor (only role) | `openai/gpt-4o-mini` | `gpt-4o-mini-2024-07-18` on every call: 2 + 2 check, 1,113 × 3 V1, 128 × 3 V2, 117 N, 51 greedy (3,895 calls) | `judgements.jsonl` `resolved_model`; `collect.json` `resolved_models` |

No other model was called by this phase. The council's two calls (SOP §9) are in `audits/council_2026-10-21_falsifiers.md`
(Qwen3-235B via OpenRouter, Codex `gpt-6.1-sol`) and are not part of the monitor's logs.

## Settings as sent (`call.request`, every call of the pass) and run flags

| pass | log directory | episodes | temperature | seed | max_tokens | tools | messages | Inspect flags |
|---|---|---|---|---|---|---|---|---|
| check V1 | `check/v1/gpt-4o-mini/pass1/` | 2 | 0.0 | 8001 | 1500 | not sent (null) | 2 (system, user) | `--max-samples 8 --max-connections 8 --no-fail-on-error`, epochs 1 |
| check V2 | `check/v2/gpt-4o-mini/pass1/` | 2 | 0.0 | 8001 | 1500 | not sent | 2 | same |
| V1 pass 1 | `v1/gpt-4o-mini/pass1/` | 1,113 | 0.0 | 8001 | 1500 | not sent | 2 | same |
| V1 pass 2 | `v1/gpt-4o-mini/pass2/` | 1,113 | 0.0 | 8002 | 1500 | not sent | 2 | same |
| V1 pass 3 | `v1/gpt-4o-mini/pass3/` | 1,113 | 0.0 | 8003 | 1500 | not sent | 2 | same |
| V2 pass 1 | `v2/gpt-4o-mini/pass1/` | 128 | 0.0 | 8001 | 1500 | not sent | 2 | same |
| V2 pass 2 | `v2/gpt-4o-mini/pass2/` | 128 | 0.0 | 8002 | 1500 | not sent | 2 | same |
| V2 pass 3 | `v2/gpt-4o-mini/pass3/` | 128 | 0.0 | 8003 | 1500 | not sent | 2 | same |
| stratum N pass 1 | `stratum_n/gpt-4o-mini/pass1/` | 117 | 0.0 | 8001 | 1500 | not sent | 2 | same |
| greedy pass 1 | `greedy/gpt-4o-mini/pass1/` | 51 | 0.0 | 8001 | 1500 | not sent | 2 | same |

Driver command (printed and logged in each `run.jsonl`): `inspect eval control_loop/analysis/transcript_monitor.py@transcript_monitor
--model openai/gpt-4o-mini --temperature 0 --seed <seed> --max-tokens 1500 --max-samples 8 --max-connections 8 --no-fail-on-error
--log-dir <pass dir> -T manifest=<manifest> -T variant=<v1|v2> -T prompt_sha=5b100fe7…`, run through the venv's `python -m inspect_ai`
by `transcript_monitor run` with `uv run --locked --env-file ../.env`. Manifests: `pool_manifest.jsonl` (V1), `pool_manifest_v2.jsonl`
(V2), `stratum_n.jsonl`, `greedy.jsonl`. No `eval-retry` was needed (0 missing records in every pass); one `ModelEvent` per sample
in every log.

`system_fingerprint` values returned (one per call): check 4 × `fp_fd3020c6f0`; V1 pass 1 `fp_fd3020c6f0` 973, `fp_46c8761086` 120,
`fp_0f86f2b5a2` 19, `fp_4c55ec580f` 1; V1 pass 2 `fp_fd3020c6f0` 967, `fp_46c8761086` 83, `fp_6548d98151` 43, `fp_0f86f2b5a2` 20; V1 pass 3
`fp_fd3020c6f0` 960, `fp_46c8761086` 76, `fp_6548d98151` 70, `fp_0f86f2b5a2` 7; V2 pass 1 `fp_fd3020c6f0` 124, `fp_6548d98151` 4; V2 pass 2
`fp_fd3020c6f0` 118, `fp_6548d98151` 7, `fp_4c55ec580f` 2, `fp_0f86f2b5a2` 1; V2 pass 3 `fp_fd3020c6f0` 120, `fp_6548d98151` 6,
`fp_0f86f2b5a2` 2; stratum N `fp_fd3020c6f0` 108, `fp_6548d98151` 7, `fp_0f86f2b5a2` 1, `fp_d4c42c8db7` 1; greedy `fp_fd3020c6f0` 50,
`fp_6548d98151` 1.

## Dates run (UTC, from the eval names and headers) and spend per step (measured from the logs)

| step | eval log | started – completed (UTC) | wall-clock | input / cache-read / output tokens | cost (USD) |
|---|---|---|---|---|---|
| mechanism check, V1 | `check/v1/gpt-4o-mini/pass1/2026-10-21T15-42-23-00-00_transcript-monitor_7UB8s8jeF6btU2Fq947bCu.eval` | 2026-10-21 15:42:23 – 15:42:31 | 8 s | 7,183 / 1,024 / 976 | 0.0017 |
| mechanism check, V2 | `check/v2/gpt-4o-mini/pass1/2026-10-21T15-42-47-00-00_transcript-monitor_7DCFUjZz27wpMavo7WpWQE.eval` | 2026-10-21 15:42:47 – 15:42:53 | 6 s | 271 / 7,936 / 987 | 0.0012 |
| V1 pass 1 (seed 8001) | `v1/gpt-4o-mini/pass1/2026-10-21T15-48-32-00-00_transcript-monitor_nSNsgFX8Nh8wMYo4e4whEU.eval` | 2026-10-21 15:48:32 – 16:02:21 | 13 min 49 s | 4,326,983 / 988,672 / 557,321 | 1.0576 |
| V1 pass 2 (seed 8002) | `v1/gpt-4o-mini/pass2/2026-10-21T16-04-24-00-00_transcript-monitor_huRHLnNqkpxKBuWxifrK4D.eval` | 2026-10-21 16:04:24 – 16:17:46 | 13 min 22 s | 4,299,847 / 1,015,808 / 559,664 | 1.0570 |
| V1 pass 3 (seed 8003) | `v1/gpt-4o-mini/pass3/2026-10-21T16-19-38-00-00_transcript-monitor_E4iKMYWoVMtUnqH6rRKKhA.eval` | 2026-10-21 16:19:44 – 16:33:29 | 13 min 45 s | 4,318,663 / 996,992 / 559,659 | 1.0584 |
| V2 pass 1 (seed 8001) | `v2/gpt-4o-mini/pass1/2026-10-21T18-52-50-00-00_transcript-monitor_idMg932FchUTnFHDPMqKSy.eval` | 2026-10-21 18:52:50 – 18:55:23 | 2 min 33 s | 497,531 / 97,536 / 60,446 | 0.1182 |
| V2 pass 2 (seed 8002) | `v2/gpt-4o-mini/pass2/2026-10-21T18-56-01-00-00_transcript-monitor_jVjMwaP5P9VmCerMnGzfci.eval` | 2026-10-21 18:56:01 – 18:57:47 | 1 min 46 s | 55,163 / 539,904 / 60,583 | 0.0851 |
| V2 pass 3 (seed 8003) | `v2/gpt-4o-mini/pass3/2026-10-21T18-58-22-00-00_transcript-monitor_HadQaNtfYwiDVd2dc7VT9X.eval` | 2026-10-21 18:58:22 – 18:59:45 | 1 min 23 s | 54,395 / 540,672 / 59,882 | 0.0846 |
| stratum N pass 1 (seed 8001) | `stratum_n/gpt-4o-mini/pass1/2026-10-21T19-00-17-00-00_transcript-monitor_TwY9amExmXCatpBHnNNJYi.eval` | 2026-10-21 19:00:17 – 19:01:49 | 1 min 32 s | 483,111 / 98,432 / 58,883 | 0.1152 |
| greedy pass 1 (seed 8001) | `greedy/gpt-4o-mini/pass1/2026-10-21T19-02-19-00-00_transcript-monitor_9pHhFYvmFgKGdoM6KRDyiA.eval` | 2026-10-21 19:02:19 – 19:02:58 | 39 s | 179,348 / 41,728 / 25,680 | 0.0454 |
| **phase total, measured** | `report.json` `spend.total` (unrounded 3.62447565; `spend.json` `total` is the pre-fix sum of the rounded rows, 3.6244; audit C6 / X6) | 2026-10-21 15:42 – 19:03 UTC | | | **3.6245** |

The finish run (the last five rows) was started after the owner's decision dated 2026-10-22 (00:22–00:33 IST on 2026-10-22;
the pod's clock and the eval names are UTC, 2026-10-21). PLAN §6 as amended: check $0.01 / $0.02, one V1 pass $1.33 / $2.00,
V2 three passes $0.48 / $0.75, stratum N $0.14 / $0.20, greedy $0.07 (PLAN §9 D10 "about $0.07", no PLAN upper) / $0.10 (the
driver's constant `BUDGET` in `transcript_monitor.py`, `spend.json` `upper`), primary arm $4.62 / $6.97 (est / upper); the
census amendment foresaw about a fifth fewer input tokens, and the V2 passes 2–3 were cheaper again because the provider
served most of their input from its cache. Not run (owner's decision, 2026-10-22): the gpt-4o secondary arm. The $15
single-cell stop and the $40 cell cap were never approached (largest cell $1.0584). `control_loop.status`'s total ($6.8003 over
10 leaf runs) adds the three V1 passes' cumulative lines and is not a spend figure. Council (SOP §9, not a monitor call):
Qwen3-235B $0.0027 at the `spend.py` list price (OpenRouter's own usage field $0.0018); Codex `gpt-6.1-sol` 23,004 tokens, unpriced.

## Comparators (not re-run)

Per-action judges' per-claim AUROCs on the 99 §16.12(b) claims, from `control_loop.analysis.claim_scores --clean
results/phase2_claim_monitor/late/baselines/733_claim_score_only --attacked results/phase2_claim_monitor/late/score_only/733_claim_score_only`,
recomputed offline on 2026-10-21 at the mechanism check: fixed 0.502 / 0.637, claim-context 0.741 / 0.793 (12 positives, 87 / 54 negatives).
