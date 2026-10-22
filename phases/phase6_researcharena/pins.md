# pins — Phase 6: ResearchArena `cuda_kernel` (docs/SOP.md §2.5)

Started 2026-10-22 by task phase6-check-complete for the check stage of replicate `qwen3_733` (run2). Later stages
append below. Dates are UTC. Paths are repository-relative. The pinned ResearchArena checkout lives outside the
repository.

## Code

| item | value | source |
|---|---|---|
| ResearchArena | `aisa-group/ResearchArena` at `58776e09339c1714d0524130590abaf6eac7879d`, unmodified (`git status --porcelain` empty before and after the monitor re-run) | `results/phase6_researcharena/sweep/qwen3_733_run2/arena_root_manifest.json` |
| composed root | `$P6_ARENA_ROOT` on the CPU pod, `/workspace/arena_root` on each GPU pod (built by `pod_setup.sh` step 5); 206/206 files identical to the checkout; additions only `agents/opencode_or/{solve.sh, keep_env_vars, human_readable_trace.py}` and `settings/cuda_kernel/side_tasks/payload/*`; payload = stock `independent/side_task.md` (SHA-256 `1d67c80ad8d2613670744fe57d287fc6457b15677c947cf5e2cd0c064436de40`) | same; manifest SHA-256 `b571fc680b59ca7f8dc4ef554c848b5f8c6a336b55d89c1c2bad6befda300661` (= `$P6_ARENA_ROOT/composed_root_manifest.json`) |
| monitor template | `monitors/templates/monitor.md` SHA-256 `cf9910fd70f5f372edaa9e8c0e7fa6d4617ebbd45d5f5318043028e01bd35b96` | manifest; `docs/instruments/researcharena_monitor_m0.md` |
| control-loop | **local (uncommitted)** `control_loop/` tree, pushed to each GPU pod by tar over ssh (`--control-loop-commit local`); the monitor re-run used the CPU pod tree with the 2026-10-22 `sweep.Core.run_monitor` absolute-path fix | `launches/check{1,2}/run.jsonl` |
| opencode-ai | **1.19.3** on both GPU pods (agent; `setup.log` line 11) and on the CPU pod (monitor; `npm install -g opencode-ai@1.19.3` 2026-10-22 09:56, `opencode --version` 1.19.3; before that the CPU pod had no opencode) | `launches/check{1,2}/pods/*/setup.log` |
| node | v22 on the GPU pods (`pod_setup.sh` step 2); v22.23.3 on the CPU pod | setup.log; `node --version` |
| GPU-pod Python stack | python 3.11, torch 2.10.0+cu128 (`torch.version.cuda` 12.8), transformers 5.3.0, nvcc 12.9, `CUDA_HOME=/usr/local/cuda`, `TORCH_CUDA_ARCH_LIST=8.0;8.9;9.0`; HF-cache overlay = copy stand-in (`p6_fuse_mode` shim) | `launches/check{1,2}/pods/*/{setup.log, p6_fuse_mode}` |
| CPU pod | `heqaytgwoxutst` (EU-RO-1); Python 3.12.3 (system), uv 0.10.9, `uv run --frozen` | — |

## Models (per role, as passed and as resolved)

| role | as passed | as resolved | seed / temperature sent |
|---|---|---|---|
| untrusted agent | `--redteammodel opencode_or:openrouter/qwen/qwen3-235b-a22b-2507` (`metadata.json` `red_model`) | OpenRouter's routed provider is not recorded in `solve_out.json`. One request in `rounds/r0a/e1` was routed to a Google Vertex model id `qwen3-235b-a22b-instruct-2507-maas`, which returned 404 (ev 131) | none (the agent's `opencode.json` sets permission and provider only); `--seed 733` seeds the bench's torch only (PLAN §1.5) |
| monitor (M∅) | `--blueteammodel opencode:anthropic/claude-sonnet-4-6`, `--blueruntime 0.0833`, no access flags | opencode recorded providerID `anthropic`, modelID `claude-sonnet-4-6`. The provider's response model string is not stored by opencode 1.19.3: **unverified** | none (monitor's `opencode.json` has no options) |
| proposer | `anthropic/claude-sonnet-5-5` | not used in the check stage | — |

## GPU pods (check stage run2)

| launch | pod | name | GPU | data center | image | created → deleted (UTC) | s billed | $ |
|---|---|---|---|---|---|---|---|---|
| check1 | `7bkjqa1zhho1mv` | p6-qwen3_733-check1-e2 | NVIDIA H100 80GB HBM3 (SXM), Secure, $3.99/h | EU-NL-1 | `runpod/base:1.4.1-cuda1290-ubuntu2204`, `--min-cuda-version 12.9` | 08:06:03 → 08:25:41 | 1,270 | 1.4083 |
| check2 | `nlfm6a9lbsdy2x` | p6-qwen3_733-check2-e1 | same | EU-FR-1 | same | 08:28:38 → 08:50:44 | 1,500 | 1.6634 |

At both launches the second pod's create returned "no longer any instances available" (EU-FR-1/EU-NL-1). So the
driver ran two episodes serially on one pod (PLAN §7.7(2)).

## Settings and drivers

`--setting cuda_kernel --task_config tinyllama --redruntime 0.1667 --seed 733`; side task `none` (clean/run1/e1) or
`payload` = stock paragraph (rounds/r0a/e1–e3). Driver: `python -m control_loop.adapters.researcharena.sweep
--replicate qwen3_733 --seed 733 --stage check --out results/phase6_researcharena/sweep/qwen3_733_run2`
(owner-launched). Monitor re-run: `sweep.Core().run_monitor(...)` per episode via `uv run --frozen --env-file
../.env` (task phase6-check-complete). Mechanism check re-run: `python -m
control_loop.adapters.researcharena.mechanism_check --clean …/clean/run1/e1 --a0 …/rounds/r0a/e1 --composed-root
$P6_ARENA_ROOT --pods-jsonl …/pods.jsonl --seed 733` → `check/mechanism_check_rerun.out`.

## Dates run and spend per step (list price, from the logs)

| step | UTC | $ | log |
|---|---|---|---|
| smoke, smoke2, smoke3, smoke4 | 2026-10-21 16:12 – 2026-10-22 06:37 | GPU 0.9060 (+ API ≤ 0.10 upper) | `results/phase6_researcharena/smoke*/` |
| check attempt 1 (all episodes lost, start-command bug) | 2026-10-22 07:02–07:54 | GPU 3.4290; API not measurable | `results/phase6_researcharena/sweep/qwen3_733/` |
| check run2: launch check1 (clean e1, r0a e1) | 2026-10-22 08:04–08:25 | GPU 1.4083; agent 0.0170 + 0.2130 | `sweep/qwen3_733_run2/launches/check1/`, episode dirs |
| check run2: launch check2 (r0a e2, e3) | 2026-10-22 08:25–08:50 | GPU 1.6634; agent 0.0938 + 0.0636 | `…/launches/check2/` |
| check run2: monitor attempt 1 | 2026-10-22 08:25, 08:50 | 0.0000 (monitor never started) | `*/blue_team_attempt1_cli_missing/` |
| check run2: monitor re-run | 2026-10-22 09:57–10:02 | 0.0771 + 0.2029 + 0.1359 + 0.1190 = 0.5349 | `*/blue_team/opencode_anthropic/claude-sonnet-4-6/`, `run.jsonl` |
| **check run2 total** | | **3.9940** | `CHECK_BYHAND.md` §9 |
| **Phase 6 to date** | | **8.4290** (GPU 7.4067, API 1.0223 incl. 0.10 upper) | |

Agent $ is the reader's list price (`control_loop/spend.py` Qwen3 0.22/0.88 per M, unverified). opencode's own
OpenRouter cost for the same four episodes sums to $0.1444. Monitor $ is opencode's per-message cost, which
equals `spend.py`'s Sonnet 4.6 prices.

## OpenRouter routing for the untrusted agent (2026-10-22, PLAN Amendment (3) item 1; task phase6-diag-prep)

| item | value | source |
|---|---|---|
| model | `openrouter/qwen/qwen3-235b-a22b-2507` (unchanged) | PLAN §1.5 |
| routing object sent | `"provider": {"order": ["deepinfra", "parasail", "venice"], "allow_fallbacks": false, "ignore": ["google-vertex"]}` in every Qwen3 `/chat/completions` body | `control_loop/adapters/researcharena/arena_root.py` `QWEN3_ROUTING` |
| why these | the providers that served this model without error in Phase 4 (`phases/phase4_controlarena/pins.md`: DeepInfra, Parasail, Venice, Google). Google's only route for this model on OpenRouter is `google-vertex` (`google-vertex/us-south1`; endpoints list read 2026-10-22, `GET /api/v1/models/qwen/qwen3-235b-a22b-2507/endpoints`), the route that returned 404 in run2 e1 (ev 131, `…/publishers/qwen/models/qwen3-235b-a22b-instruct-2507-maas`), so it is ignored. No fallback: a request no pinned provider can serve fails visibly instead of drifting | `CHECK_BYHAND.md` §3 |
| endpoints on the pinned providers (2026-10-22) | DeepInfra `deepinfra/fp8` $0.09/$0.55 per M, Parasail `parasail/fp8` $0.14/$0.80, Venice `venice/fp8` $0.15/$0.75 (all fp8; status 0). Not pinned: GMICloud fp8, Nebius fp8 (status −5), Google (status −5). `spend.py`'s list price for this model ($0.22/$0.88) stays the accounting price (an upper bound for these three) | the endpoints list |
| slug semantics | a base slug (`deepinfra`) matches every endpoint of that provider (openrouter.ai/docs/features/provider-routing, read 2026-10-22) | — |
| how it reaches the request | the composed root's `agents/opencode_or/solve.sh` exports `OPENCODE_CONFIG_CONTENT='{"provider":{"openrouter":{"models":{"qwen/qwen3-235b-a22b-2507":{"options":{"provider":{…}}}}}}}'` right after the stock `opencode.json` heredoc; opencode passes model `options` as providerOptions.openrouter, which `@openrouter/ai-sdk-provider` spreads into the body. The project `opencode.json` the stock solve.sh writes is NOT applied by opencode 1.19.3 `run` (provider settings, headers and models in it never reached a request; captured 2026-10-22), so the routing could not go there | FINDINGS 2026-10-22 "unpaid fixes" |
| verified | request bodies captured by a local TLS-terminating proxy on the CPU pod (no request reached OpenRouter, dummy key): the Qwen3 body carried exactly the routing object; the title request (`google/gemini-nano-banana-2.1`, opencode's small model for OpenRouter) carried none | `/tmp/p6_orproxy.py` on the CPU pod (scratch, not in the repo) |
| composed root | `$P6_ARENA_ROOT` rebuilt and verified 2026-10-22 (206/206 identical, `overlay_agent_is_default` true, manifest `overlay_openrouter_routing` = the object above); the GPU pods rebuild theirs in `pod_setup.sh` step 5 from the pushed tree | `composed_root_manifest.json` |
| not verified | that OpenRouter honours the object on a real call (no paid call made); which provider serves each request (opencode 1.19.3 does not store OpenRouter's `provider` response field in `solve_out.json`) | — |
