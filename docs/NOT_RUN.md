# Not run

Experiments that are designed, or partly built, but were not run. Each entry says what it is, what is ready, what it
would cost, and what has to be decided first. Newest first.

## Phase 6: monitored side-task episodes on ResearchArena `cuda_kernel` (the next experiment)

**Update, 2026-10-27.** Cell 733, the first of the three replicate cells, has run and is written up in `phases/phase6_researcharena/README.md` §15. Seeds 512 and 1049 are still not run. Before them: benchmark change 10 (opencode's command timeout, PLAN Amendments (34)-(35)), pinning opencode 1.19.4, and a ruling on how an agent's last `[agent]` line is read (README §15.9 item 1).

**What it is.** Phase 6's original question (`phases/phase6_researcharena/PLAN.md` §1-§3): does the adaptive attack hold
in a research-agent setting with longer horizons?

The PLAN's design is three replicate cells (seeds 733, 512, 1049) of 24 episodes each:
- a mechanism check;
- a reproduction screen;
- two clean runs;
- a static round r0a;
- adaptive rounds r1-r3 with the proposer.

Each episode runs the untrusted agent on the main task plus a side task (embedded or independent, or the round's
payload). ResearchArena's post-hoc monitor M∅ (transcript only, Sonnet 4.6) then scores it. Phase 6 did not run any of it.
The work went into making the task run and be measured correctly (README §14).

**What is ready.**
- **The trusted baseline:** benchmark changes 00-07 (README §14.1-§14.2).
- **The run tooling:**
  - pods created without `--wait`;
  - detached remote steps;
  - the watchdog with a copy before any delete, and the idle guard;
  - the verified copy;
  - the model-spend cap;
  - the change 07 counts.
- **One honest one-hour GLM-5.1 run, measured** (x1.035 median, correct, memory-clean, 0 fallbacks).
- **Already built, from the original plan:** the adapter, the payload installer and the proposer
  (`control_loop/adapters/researcharena/`, `phases/phase6_researcharena/PLAN.md` §1.4 and §7).

**What is not ready.**
- The runner for monitored episodes has not been run on the 00-07 baseline.
- The monitor M∅ has run only once, on an early check pair (`results/phase6_researcharena/sweep/qwen3_733_run2/`).

**Cost estimate**, from measured one-hour numbers (2026-10-24) and H100 SXM at $3.99/h.
- **GPU per episode:**
  - bring-up about 0.18 h (pod ready about 5-6 min, setup about 5-6 min);
  - agent 1.00 h (the paper's budget);
  - evaluator about 0.12 h (fullrun3: about 7 min);
  - side-task evaluator about 0.12 h;
  - copy and delete about 0.03 h.

  That is **about 1.45 h, $5.79**, on its own pod; about 1.27 h ($5.07) when episodes share a pod serially.
- **Agent model per episode:** GLM-5.1 **$1.75** (measured, fullrun3). Qwen3-235B, the PLAN's untrusted model, about
  $0.20-0.50 (scaled from fullrun2's 10 min at $0.03; not measured at one hour).
- **Monitor per episode:** Sonnet 4.6 M∅, $0.30 (upper $1.00), the PLAN's estimate.
- **Proposer:** about $0.02 per call (the PLAN's estimate).

| Scope | Episodes | GPU | Agent (GLM-5.1 / Qwen3) | Monitor | Total (GLM-5.1 / Qwen3) | Pod time |
|---|---|---|---|---|---|---|
| one cell (seed 733) | 24 | $122-139 | $42 / $5-12 | $7-24 | **$171-205 / $134-175** | about 35 h; about 9 h wall-clock at 4 pods in parallel |
| the PLAN's headline (3 cells) | 72 | $365-417 | $126 / $14-36 | $22-72 | **$513-615 / $401-525** | about 104 h; about 26 h wall-clock at 4 in parallel |

- **Ranges:** they come from pod sharing (low) against a pod per episode (high), and the monitor's estimate against its
  upper bound.
- **The original estimate is out of date.** The PLAN's step table ($107 GPU for 72 episodes) assumed a 10-minute agent
  budget, which was a test-scale setting (Amendment (18)); at the paper's one hour the GPU cost is about 4-5x higher.

**To decide before it runs.**
1. **The untrusted agent:** the PLAN's Qwen3-235B (Phase 4's untrusted model), or GLM-5.1 (the paper's agent, measured
   here).
2. **Scope:** one cell first, or the headline three.
3. **A budget** at the scale above. It is outside every Phase 6 cap so far; Phase 6's measured total is $41.95.
4. **Whether the paper's other monitor axes are in scope.** The PLAN's secondary S3, the artifact monitor, is estimated
   at about $10 GPU plus $12-24 API per cell at the 10-minute scale, and more at one hour.
