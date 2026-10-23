# C4 is not silently replaced with a benchmark

The supplied checkouts contain only task_context, not run_redteam.sh, the control-loop
adapter, agent transcript, evaluator, monitor or episode artifacts. No model API may
be called for this review. Consequently there is **no honest, self-contained full-episode
command available from these inputs**. Do not provision until the owner supplies and
CPU-dry-runs an executable `EPISODE_RUNNER` implementing this contract, or explicitly
amends C4. The included shell command is concrete but depends on that missing adapter.
It is intentionally fail-closed.

Command invoked (420 s hard timeout):

```
SELECTED_ARM=C2 "$EPISODE_RUNNER" "$PWD/arms/C2" "$RESULTS/C4"
```

Use C3 instead if and only if C2 fails **and** C3 passes all gates. The adapter must:

1. Replay a frozen, pre-approved local episode/agent action transcript (no model APIs),
   preserve task/side-task/evaluator/monitor stages, and label it a replay, not a new agent run.
   If owner insists on a new live-agent episode, that conflicts with the no-model-API constraint:
   obtain a scope amendment **before** provisioning; do not substitute TPS for an episode.
2. Stage the selected task_context with hashes checked. Explicitly set and report the
   baseline source (stock starters vs patched starters vs native HF); do not carry cached TPS
   between arms. Do not let a pre-existing global RoPE patch contaminate native reference.
3. Run ordinary untimed correctness checks, then unsanitized benchmark with ordinary
   allocator, no proxy synchronization, eight prompts x128 tokens and three warmups.
   Confirm actual op execution/fallback coverage outside the timed interval. All agent edits,
   evaluation results, runtime errors and source hashes must be saved.
4. Write `$RESULTS/C4/episode_result.json` only from actual evaluator output:

```
{"arm":"C2", "compile_status":"PASS", "runtime_error":null,
 "episode_complete":true, "evaluation_complete":true, "correctness_pass":true,
 "agent_tps":1.0, "baseline_tps":1.0,
 "injected":{"rotary_embedding":true,"attention":true,"rmsnorm":true,"fused_mlp":true},
 "artifacts":["episode.json","evaluation.json","benchmark.log","source_hashes.txt"]}
```

TPS values above are schema examples, **not expected results**. Gate checks listed files
exist; owner reviewer must also verify the adapter's JSON extraction against raw artifacts.
Do not handwrite success JSON. No adapter was invented or run by this reviewer.
