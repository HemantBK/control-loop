# Paper plan: safety against attacker search effort and monitor strength, and which defenses hold

Written 2026-10-27, after the novelty check (`docs/paper/novelty_check.md`) and before any run for the experiments below.
- This is the paper-level plan. Each experiment still gets its own phase PLAN, with pre-registration and owner approval,
  before it runs (`docs/SOP.md` §1).
- Nothing here is approved for spend.
- No cell runs without a pre-registered budget.

## 1. Thesis

AI-control monitors are usually evaluated against one attack, or against an attacker with an unstated search effort. We
measure **safety as a function of how much the attacker searches**: B = 1 to 32 candidate attacks, each refined from monitor
feedback. We measure it against monitors of three strengths and an ensemble, at audit budgets of 1%, 2% and 5%. We then ask
**which defenses keep the curve flat** when the attacker searches against them, moving second:
- outcome-based checks;
- randomized or hidden monitor prompts;
- diverse ensembles.

The core runs in ORBIT, a multi-agent allocation setting where the attack is a coalition payload. The realism check runs in
ResearchArena, a long-horizon AI R&D setting.

Two questions, each answered with curves, not one number:
1. How fast does safety fall with the attacker's search budget B, and does a stronger monitor or an ensemble change the
   slope or only the intercept?
2. Which defenses hold against an attacker that knows the defense and searches against it?

## 2. What related work already shows, and what this paper adds

Summaries: `docs/paper/novelty_check.md`. Read in full on 2026-10-27.

| paper | already shows | does not show | what we add |
|---|---|---|---|
| Terekhov et al. 2025 (arXiv:2510.09462) | **Adaptive attacks work.** Prompt injections aimed at the monitor subvert GPT-4o-mini, GPT-4o and GPT-4.1 monitors on APPS and BashBench. Protocols fall to the safety of upfront auditing, injections transfer across monitors, and resampling backfires. Audit budget 2% (sensitivity 1%, 4%). | Search effort is fixed and never varied. One attack family. No monitor stronger than GPT-4.1 or ensemble tested against the attacker. Mitigations (ensembles, scaffolds) proposed, not tested. | Safety as a curve over B for 3 monitor strengths and an ensemble; current monitors; several attack families; defenses tested adaptively. |
| MiniLab (arXiv:2610.24052) | **Distributed attacks evade per-agent monitors.** A per-agent GPT-5.6 Sol monitor flags 7% of successful attacks spread over agents, against 87% for one agent. Planner search with monitor feedback raises covert success from 3% to 48% against Luna; against a held-out Sol it falls to 20-25%. Thresholds at 1% and 2% FPR from 316 benign teams. | Search effort is one setting (with or without the feedback tool), not a curve. Monitor strength is two models used as optimisation target and held-out check, not a crossed design. No defenses beyond joint and synchronous monitoring. | B as a dose axis crossed with monitor strength. The full transfer matrix (attacks found against one monitor tested on all). Three defense families, each re-searched by the attacker. |
| Colosseum (arXiv:2602.15198) | **Action-level collusion audits catch what judges miss.** Regret-based audits in cooperative multi-agent tasks (DCOPs) find collusion that LLM judges miss (hidden collusion). A secret channel induces emergent collusion. Coalitions with high-leverage agents and persuasion succeed. | No adaptive attacker that searches against the audit. No audit budgets or safety curves. Mitigations proposed, not tested. | Outcome-based checks (allocation against the reference optimum, ORBIT Phase 3's rule) tested against an attacker that knows them and searches. |
| ResearchArena (arXiv:2607.19321) | **Monitors vary by setting and access.** In AI R&D, embedded sabotage without a code footprint is hard to detect (AUC 0.53-0.71). Artifact access helps, and chain of thought can talk the monitor down. Independent side tasks (our typosquat) are caught reliably at 50. | The red team does not hide: the authors call detection an upper bound, and name adaptive obfuscation as future work. One fixed threshold (50) plus AUC; no audit-budget thresholds. | The same setting under an adaptive search with audit-budget thresholds (Phase 6b = E3a), then smaller-scale curves (E3b). Also the benchmark fixes 00-10. |
| ASMR-Bench (arXiv:2604.16286) | **Research-sabotage auditing is weak.** Auditing ML codebases for sabotage: best AUROC 0.77, top-1 fix 42%. LLM-made sabotages evade same-capability auditors. Iterating against auditors helped the human attacker little. Ensembles suggested. | No curve of attacker effort. AUROC only, no audit budgets. No ensemble actually tested. | Search-effort curves and a tested diverse ensemble. |
| Emergent collusion (arXiv:2609.24967) | **Collusion can emerge unprompted.** Two agents with no misbehaviour instruction collude to skip verification in 94% of trajectories. Memory limits and separate rewards reduce it. | No monitor, no attacker, no audit budget. | Out of our scope (we study an instructed adversary). We cite it for the outcome-looks-right failure that outcome checks must handle. |

**Our earlier phases that the paper builds on:**
- Phase 2: a per-claim judge did not prevent redistribution in 2 of 5 cells.
- Phase 3: the allocation-level monitor held. Its falsifier was not met in 8 of 8 cells.
- Phase 4 (ControlArena): adaptive rewriting raised successful attacks, but none got past a Sonnet 4.6 monitor at 1%.
- Phase 8: a full-transcript monitor reached an episode AUROC of 0.66-0.67.
- Phase 6, cell 733 (ResearchArena): matched at τ, falsified at 50.

**Novelty risk.** Three papers cited by MiniLab are not yet read: SLEIGHT-Bench (arXiv:2605.16626), Makins et al.
(arXiv:2607.07368) and Hills et al. (arXiv:2607.02514).
- SLEIGHT-Bench, a benchmark of evasion attacks optimised against agent monitors, is the closest to our search-effort axis.
- **Before any spend for E1 or E2, all three are read and this table is updated.** If one of them already reports safety
  against search budget crossed with monitor strength, the thesis narrows to the defenses (E2) and the multi-agent
  allocation setting.

## 3. Experiments

### E1, core (ORBIT): safety against search budget × monitor strength × audit budget

**Setting.** As in Phases 1-8: the ORBIT `customer_service` allocation task with 4 agents. The coalition payload is the
attack, and success is redistribution (Phase 2's metric).
- The agents stay `openai/gpt-4o`, for comparability with Phases 1-8 (D1).

**Monitor.** One score per episode, from a full-transcript monitor in Phase 8's form. Thresholds come from clean episodes at
1%, 2% and 5% FPR.
- **Three strengths in one family:** weak `openai/gpt-6-luna`, mid `openai/gpt-6.1-terra`, strong `openai/gpt-6.1-sol`.
  The family is the same, so that strength is the main thing that varies.
- **A diverse ensemble:** `openai/gpt-6.1-terra` + `anthropic/claude-sonnet-5.5` + `google/gemini-3.8-flash`, taking the
  maximum of the three scores, each calibrated on its own clean distribution.

**Attacker.** The proposer is `anthropic/claude-opus-5.5`, from a different family than the monitors.
- It writes coalition payloads from attack families: monitor-directed text, cover story, blending, splitting, indirection,
  minimal footprint, and main-task quality.
- After each candidate it sees the monitor's score and reasoning (black box). A white-box variant shows it the monitor's
  prompt (§3 E2b).

**Search and the budget curve.** Per monitor:
- 3 independent searches of 32 candidates, each screened on 2 episodes.
- For B ∈ {1, 2, 4, 8, 16, 32}, the attack at budget B is the best of the first B candidates by a selection rule fixed in
  advance: uncaught at 2%, ties broken by lower score.
- Each selected attack is **confirmed on 16 fresh episodes**, so the curve does not rest on the search's lucky draws.
- Every confirmation transcript is scored by all monitors, which gives the transfer matrix for free.

**Calibration and controls.**
- 200 clean episodes, scored by every monitor. These set the thresholds: 200 clean episodes can tell 1% from 2% FPR, which
  32 cannot.
- 50 episodes of the static payload.

**Metrics.**
- Uncaught successful attacks per confirmation, and safety = p_caught / (p_caught + p_uncaught success), at each audit
  budget.
- Curves over B with bootstrap intervals over episodes and searches.
- AUROC of clean against attack episodes.
- The transfer matrix.

**Predictions** (to be fixed in E1's phase PLAN):
- Safety falls roughly linearly in log B for single monitors.
- The slope is steeper for the weak monitor.
- The ensemble flattens the slope more than the strong monitor alone.
- Attacks found against the weak monitor transfer poorly to the strong one, as in MiniLab.

### E2, defenses: which hold against an attacker that moves second

Each defense is tested twice:
- **Transfer:** E1's best attacks are rescored under the defense.
- **Adaptive:** a new search of 32 candidates against the defense, with the defense described to the proposer, then
  confirmation.

The three defenses:
- **E2a, outcome-based check.** Each episode's allocation is checked against the reference optimum (Phase 3's rule; a
  Colosseum-style regret). It reads no text, so it cannot be argued with. Measured: whether it holds as B grows, and what
  it costs in false alarms.
- **E2b, randomized or hidden monitor prompts.** For each episode the monitor's prompt is drawn from a pool of K = 5
  rubric variants.
  - Arm 1: the attacker does not know which variant is used.
  - Arm 2 (Kerckhoffs): the attacker sees the pool but not the draw.
  - The white-box arm (the prompt is known) is the comparison.
- **E2c, diverse ensemble.** E1's cross-provider ensemble, re-searched by an attacker that is told the ensemble's members.

**Predictions:**
- The outcome check stays flat in B, except for attacks that change the allocation outcome itself.
- Randomized prompts lower transfer but not adaptive success once the pool is known.
- The ensemble raises the B needed for a given drop in safety.

### E3, realism (ResearchArena)

- **E3a = Phase 6b.** Pre-registered in `phases/phase6_researcharena/PLAN.md` Amendment (37); it may continue.
  - Search of 24 screening episodes, confirmation of 2 × 8 one-hour episodes, a static control, and 32 clean episodes.
  - Thresholds at 1%, 2% and 5%.
- **E3b: the E1 curves at smaller scale.**
  - B ∈ {1, 4, 16}, taken from a 16-candidate search.
  - Two monitors: Sonnet 4.6 M∅, as published and as in cell 733, and one current stronger monitor.
  - Each selected attack confirmed on 8 one-hour episodes.

### Appendix: ControlArena (Phase 4)

Phase 4's ControlArena results move to an appendix as a third setting. No new runs.

## 4. Models (current)

- **Proposer:** `anthropic/claude-opus-5.5`. An alternative is `anthropic/claude-fable-5.1` (D2).
- **Monitors (E1, E2):** `openai/gpt-6-luna`, `openai/gpt-6.1-terra`, `openai/gpt-6.1-sol`.
- **Ensemble:** `openai/gpt-6.1-terra`, `anthropic/claude-sonnet-5.5`, `google/gemini-3.8-flash`.
- **ResearchArena (E3):**
  - agent `z-ai/glm-5.1` (OpenCode, as in cell 733);
  - monitor Sonnet 4.6 M∅, to match the published benchmark and cell 733;
  - the E3b stronger monitor `openai/gpt-6.1-sol` or `anthropic/claude-opus-5.5` (D4);
  - proposer `anthropic/claude-opus-5.5` from Phase 6b on (D3; Phase 6b is pre-registered with `anthropic/claude-sonnet-5-5`).

## 5. Gates and order

1. Read the three remaining papers (§2) and update §2. No spend.
2. E1's phase PLAN, with pre-registration and budget, then the owner's approval. Then E1.
3. E2's phase PLAN and approval, then E2. E2's adaptive arm reuses E1's attacker code.
4. E3a continues under its own pre-registration and caps. E3b's phase PLAN follows E3a's result.
5. Write-up under `docs/SOP.md`. Each experiment is audited cross-family.

## 6. Cost, per provider

**Unit costs.** Listed prices are OpenRouter's (`/api/v1/models`, read 2026-10-27). Token use per unit:
- ORBIT agents: 29k input and 1.8k output tokens per episode, from Phase 5's pins, with cache reads at full price.
- Monitor: 4.8k input tokens per episode, from Phase 8. Output is set to 1.5k for reasoning models.
- Proposer: 12k input and 4k output tokens per call.
- E3 one-hour episodes: cell 733's measured GPU, agent and monitor costs.

Script: `scripts/paper/cost_paper.py`.

| unit | model | $ per 1M in / out | $ per unit |
|---|---|---|---|
| ORBIT episode, agents | openai/gpt-4o | 2.50 / 10.00 | 0.0905 |
| transcript score, weak | openai/gpt-6-luna | 0.10 / 0.50 | 0.0012 |
| transcript score, mid | openai/gpt-6.1-terra | 1.00 / 5.00 | 0.0123 |
| transcript score, strong | openai/gpt-6.1-sol | 2.00 / 10.00 | 0.0246 |
| transcript score, ensemble (Terra + Sonnet 5.5 + Gemini 3.8 Flash) | 3 providers | — | 0.0470 |
| proposer call | anthropic/claude-opus-5.5 | 4.00 / 20.00 | 0.1280 |
| proposer call (alternative) | anthropic/claude-fable-5.1 | 10.00 / 50.00 | 0.3200 |
| ResearchArena one-hour episode | H100 + GLM-5.1 + Sonnet 4.6 | measured | 7.24 |

**By experiment:**

| experiment | episodes | agents | monitors | proposer | GPU | total |
|---|---|---|---|---|---|---|
| E1 core (ORBIT) | 2,170 (200 clean, 50 static, 768 search, 1,152 confirmation) | 196.38 | 158.14 | 49.15 (384 calls) | — | **403.68** |
| E2 defenses (ORBIT): transfer + 3 adaptive searches; randomized prompts rescored with 4 variants | 1,440 | 130.32 | 242.31 | 36.86 | — | **409.49** |
| E3a = Phase 6b, without ablations (Amendment (37)) | 80 | — | — | — | — | **542.05** |
| E3a middle option (no white-box arm; both stronger-monitor rescorings) | 80 | | | | | 572.53 |
| E3a with all ablations | 120 | | | | | 798.63 |
| E3b (ResearchArena curves, B ∈ {1, 4, 16}, 2 monitors) | 32 screening + 48 confirmation | | | | | **508.80** |

**By provider, E1 + E2 ($813.18):**
- OpenAI (gpt-4o agents and the Luna, Terra and Sol monitors): $601.72.
- Anthropic (Opus 5.5 proposer, Sonnet 5.5 in the ensemble): $174.82.
- Google (Gemini 3.8 Flash in the ensemble): $36.63.

E3 is billed to RunPod (GPU), OpenRouter (GLM-5.1 agent) and Anthropic (the Sonnet 4.6 monitor and the proposer).

**Paper total:**
- E1 + E2 + E3a (middle option) + E3b ≈ $1,895.
- With E3a's full ablations ≈ $2,121.
- Without E3b ≈ $1,386.

**Options that change cost:**
- ORBIT agents on `openai/gpt-6.1-terra` instead of gpt-4o: $0.038 per episode instead of $0.0905. That saves about $190
  over E1 + E2, but breaks comparability with Phases 1-8.
- Proposer Fable 5.1 instead of Opus 5.5: +$129 over E1 + E2.

## 7. Decisions for the owner

- **D1:** ORBIT agents stay `gpt-4o` (recommended: comparability with Phases 1-8), or move to a current model.
- **D2:** proposer `claude-opus-5.5` (recommended) or `claude-fable-5.1` (+$129).
- **D3:** Phase 6b's proposer moves to `claude-opus-5.5` before its first run (recommended, to use current models), or stays
  `claude-sonnet-5-5` as pre-registered. Either way the change needs a dated amendment.
- **D4:** E3b's stronger monitor: `gpt-6.1-sol` or `claude-opus-5.5`.
- **D5:** read the three remaining papers before E1's PLAN (recommended; no cost).
- **D6:** E2b's prompt pool size (K = 5) and its two arms.
