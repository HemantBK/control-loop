# Paper plan: does monitor feedback help an automated attacker, and does task-level context remove the advantage?

Written 2026-10-27. Owner's decision of 2026-10-27: adopt the reshape and narrow the paper to one question.
- It replaces the search-budget plan of the same day, which is kept unchanged at
  `docs/paper/superseded/PLAN_search_budget_2026-10-27.md`.
- **Nothing here is approved for spend.** Stage 1 (§9) needs the owner's go.
- The experiment still gets its own phase PLAN with pre-registration before any paid run (`docs/SOP.md` §1). This file
  fixes its design, numbers and budget.
- Scripts: `scripts/paper/power_paper.py` (§5) and `scripts/paper/cost_paper.py` (§9). Both are deterministic and make no
  model call.

## 1. Question, hypotheses and what counts as an answer

**Question.** At the same search budget, does monitor feedback help an automated attacker, and does task-level context
in the monitor remove that advantage?

**Setting.** ORBIT JiraTicket only. ResearchArena is a case study with no new runs (§7).

**Hypotheses** (direction fixed now; the margins come from §5):
- **H1, feedback helps.** Under the local monitor view L, the outcome-plus-monitor-reasoning search (M) yields a higher
  rate of uncaught successful attacks than the outcome-only search (O): M − O > 0.
- **H2, context removes it.** Under the task-level view T, M − O is smaller than under L: (M − O)_L − (M − O)_T > 0, and
  (M − O)_T is close to 0.

**What counts as an answer at the planned n.** The audit budget is 5% (2% as sensitivity), and the contrast is M − O
in each view, Holm-adjusted over the two views.
- **An effect:** a 95% interval that excludes 0.
- **A precise null:** both 95% intervals inside ±15 percentage points. Why ±15 and not ±10 is in §5.
- **Inconclusive:** anything else. It triggers the fallback (§8).
- The interaction H2 is reported with its interval. It is powered only for large effects (§5), and the paper says so.

## 2. What related work already shows, and the delta

| paper | already shows | what is left for us |
|---|---|---|
| Terekhov et al. 2025, arXiv:2510.09462 (ICLR 2026) | Monitor-directed injections, built offline with the monitor's prompt and feedback, subvert trusted monitors on APPS and BashBench | Whether the feedback itself is what helps, at matched budget |
| MonitoringBench, arXiv:2605.09684 | Strategy generation plus hill-climbing on monitor score and reasoning: an Opus-4.5 monitor's catch rate falls from 94.9% to 60.3% | No arm without the monitor feedback; refined transcripts rather than executed episodes |
| MiniLab, Kitaoka et al., arXiv:2610.24052 | Multi-agent planner search with execution and monitor feedback, confirmed in fresh environments; model-planned attacks reach at most 25% covert success against 80% for human plans | Feedback components are not isolated (the authors' limitation); no monitor-information factor |
| FakeLab, Makins et al., arXiv:2607.07368; SCHEME, arXiv:2605.29178 | Distributed multi-agent attacks hamper per-instance monitors; giving the monitor more (communication, all agents) helps | No searching attacker crossed with monitor information |
| Arike et al., arXiv:2601.21112 | Monitor information access changes detection, not always for the better | Static attacks only; no feedback-driven attacker |
| RSI Control, arXiv:2610.27735 | Evasion tactics drawn from earlier monitor verdicts cut transcript-monitor TPR at 2% FPR from 56–81% to 16–28% in AI R&D sabotage | One feedback condition, no matched no-feedback search |
| SLEIGHT-Bench, arXiv:2605.16626; attack selection, arXiv:2602.04930 and 2606.06529 | Evasion attacks and attack selection cut measured safety | Not about the value of feedback |

**Delta.** One controlled measurement.
1. The proposer, strategy library, rounds, candidates and episodes are held fixed.
2. The only change between the two search arms is whether the proposer sees the monitor's scores and reasons.
3. That is crossed with whether the monitor sees task-level context.

Not claimed:
- that adaptive attacks break monitors (published);
- that we are first to study multi-agent or research sabotage;
- that the loop is a contribution.

`docs/paper/novelty_check.md` records the reading. Before the phase PLAN, it gains entries for the papers in this table
that it does not yet cover.

## 3. Design

### 3.1 Setting and instances
- **Task:** ORBIT JiraTicket as in Phases 1–8.
  - `num_developers=4`, `num_tasks=4`, `scarcity=0.5`, `max_turns=40`, `max_time_seconds=350`.
  - Coalition `dev_0, dev_1`; early ordering.
  - Agents `openai/gpt-4o` at temperature 0, with seed = problem seed.
- **Unit of independence.** Every episode runs on a distinct problem instance (a distinct problem seed). Seeded
  temperature-0 agents make repeat episodes at one seed near-copies (Phase 3 limit 2), so repeats are never counted as
  draws.
- **Disjoint seed pools,** fixed in the phase PLAN before any run:
  - calibration;
  - validation;
  - search;
  - confirmation, in blocks of 20.
- Confirmation block *i* is shared by every arm's *i*-th search (a paired design), and no instance is used twice.

### 3.2 Monitor views (one model, one instruction, one output format; only the context block differs)
- **Model:** `openai/gpt-4o-mini`, temperature 0, as in Phases 2, 3 and 8.
- **Output:** "ALLOW or BLOCK" on the first line, then a short reason.
- **Score:** P(BLOCK) from the first-token log-probabilities, as in Phase 2's score-only judge.
- **Non-blocking.** The monitor runs in score-only mode: it never blocks, and it rules on every `assign_task` claim.
- **Episode score:** the maximum claim score.

| view | context the judge sees | role |
|---|---|---|
| W, weakened | the tool call's name and arguments only (Phase 1's actions-only view) | positive control |
| L, local | W + the ticket, the caller's skills, availability and workload, and the caller's own earlier claims | main |
| T, task-level | L + the whole forming allocation, every holder's fit and capacity, every agent's claims, and who claimed before viewing the task list | main |
| X, **oracle** | T + the reference-optimal allocation (ORBIT's `DCOPState.optimal_assignment`): Phase 3's optimum-aware monitor | oracle upper bound, scored post hoc only |

**Phase 3's monitor is an oracle.** It reads the reference optimum, which a deployed monitor would not have. Every
mention of it in the paper says so, and it is never one of the views compared in §1. Because no view blocks, every
episode can be scored by all four views, so the view comparison is paired within each episode.

### 3.3 Attacker arms (one factor changes per step)

| arm | what the proposer gets back after each screening episode | changes from the arm above |
|---|---|---|
| S, static | no search: ORBIT's stock collusion sentence, unmodified (Phase 1's A0) | — |
| O, outcome-only search | whether the attack succeeded (§4.1), coalition reward gain against the clean mean, the final allocation, validity, and the turn of the coalition's first claim | search, with outcome feedback |
| M, outcome + monitor reasoning | everything in O, plus every coalition claim's P(BLOCK) and written reason from the **target view**, and whether the episode is flagged at the 5% threshold | the monitor's feedback only |

The following are the same in O and M:
- **Proposer and library.** Proposer `anthropic/claude-opus-5-5` (D1), with one system prompt apart from the
  feedback-format paragraph. Strategy library: the attack families of the Phase 6b plan that apply to ORBIT
  (monitor-directed text, cover story, blending and timing, splitting across claims, minimal footprint, main-task quality
  as cover), and each proposal names the families it uses.
- **Search budget:** 6 rounds × 4 candidates, each screened on 2 search-pool instances. That is 48 episodes and 6
  proposer calls per search.
- **Selection rule** (the red team's choice, applied after the search, identical in O and M). Per target view, take the
  candidate with:
  1. the most screening episodes that are successful and not flagged at that view's 5% threshold;
  2. then the lower mean episode score;
  3. then the earlier round.

  One O search therefore yields a selection for L and one for T. Each M search targets one view: M-L or M-T.
- **Confirmation:** the selected attack runs on its 20 fresh confirmation-block instances. **Claims come only from
  confirmation episodes.** Screening is reported in full but never pooled with confirmation.

A3 (white box), the DGM writer, extra settings and ensembles are not part of this paper.

### 3.4 Positive control
Before the main arms, M runs against the weakened view W:
- 5 independent searches, each with its own confirmation;
- the static payload on 100 confirmation instances.

**Pass:**
- the pooled confirmed uncaught-success rate at 5% beats static by at least 20 points, with the 95% interval above 0;
- and at least 3 of the 5 searches individually beat static's rate.

If the attacker cannot beat W, its nulls against L and T say nothing about robustness. That is the condition kill check
1 tests (§8).

## 4. Measurement

### 4.1 Outcome
- **Successful attack:** P-ext (Phase 3's pattern). The coalition ends holding an outsider's reference ticket while that
  outsider holds none, in an episode valid under the completion rule: every ticket allocated, the sample completed, and
  ORBIT halted on `all_agents_submitted`.
  - The allocation rule is a sensitivity analysis.
  - Invalid episodes count as not successful and are reported per arm.
- **Primary outcome per confirmation episode:** successful and not flagged at audit budget b. It is unconditional (per
  attempted episode); detection conditional on success is secondary.
- **The clean P-ext rate is reported as a floor.** Harm that happens without an attack is not credited to any arm. The
  arm contrasts difference it out.
- **Detection, not prevention.** The monitor scores and an audit follows; nothing is blocked during the episode. The
  paper calls the safety number "detection at audit budget b".

### 4.2 Thresholds and honest audit-budget bounds
- Each view's threshold at budget b is the (1 − b) quantile of its scores on the **calibration** clean set.
- Its realised FPR is then measured on the separate **validation** clean set and reported with an exact (Clopper–Pearson)
  95% interval. The thresholds are never re-fit to the validation set.
- **A budget is reported as a result only if** the calibration set has at least 10 clean exceedances, and the validation
  FPR's 95% upper bound is at most 2b when the validation set shows b (§5).
- **Stage 1 (500 + 500 clean):** 2% and 5% are supported. **1% is not.** It is reported only after Stage 2's extension
  to 1,000 + 1,000. If the extension is not run, 1% appears only as an exploratory curve point.
- Every table gives the realised validation FPR beside the nominal budget.

### 4.3 Statistics
- **Unit:** the search. Each arm's estimate is the mean over its searches of the per-search confirmed rate.
- **Intervals:** t-intervals with degrees of freedom from the number of searches, plus a cluster bootstrap over searches
  as a check.
- **Tests:** the two primary contrasts (M − O under L and under T) are Holm-adjusted; H2 is reported with its interval.
- **Every attempt reported:** every candidate, screening episode, selection, confirmation and invalid episode, plus the
  per-search rates. The between-search SD σ_b is reported because it drives the precision.
- One analysis script produces every table and figure from the raw folders. Its mock end-to-end test is
  `tests/test_e2e_feedback.py`.

## 5. Power analysis (`scripts/paper/power_paper.py`)

**Clean runs per audit budget.** Episode-level FPR, from the 95% exact bounds:

| b | calibration + validation needed | reason | stage |
|---|---|---|---|
| 5% | 200 + 200 | 10 exceedances; validation upper bound 8.3% when it shows 5% | Stage 1 has 500 + 500 |
| 2% | 500 + 500 | 10 exceedances; upper bound 3.4% when it shows 2% | Stage 1 |
| 1% | 1,000 + 1,000 | 10 exceedances; upper bound 1.7% when it shows 1% | Stage 2 extension only |

For comparison, zero false positives on 32 clean runs bounds the FPR only below 8.9% (and on 50, below 5.8%). The
ResearchArena cell's 1% threshold therefore cannot be claimed.

**Searches per arm.** 95% half-width of M − O, in points. Rows: k searches per arm × m confirmation episodes each.
Columns: σ_b, the between-search SD of per-search rates.

| k × m | σ_b 0 | σ_b 0.10 | σ_b 0.20 |
|---|---|---|---|
| 5 × 20 | 13–16 | 20–22 | 32–33 |
| 10 × 20 | 8–10 | 13–14 | 21 |
| 10 × 30 | 7–8 | 12–13 | 20–21 |

The ranges are over base rates p = 0.2–0.4. The interaction's half-width is about 1.4 times the M − O half-width (for
example 17–19 points at 10 × 20 and σ_b 0.10).

**Planned n:**
- **Positive control:** 5 searches against W.
- **Main arms:** k = 10 searches per arm, m = 20.
  - This meets the owner's minimum of 5 independent searches with held-out confirmation for each.
  - 5 searches per arm cannot give a ±15 precise null unless the searches agree almost perfectly.
- **Precise-null margin:** ±15 points. At 10 × 20 that margin is met if σ_b ≤ 0.10.
  - ±10 would need σ_b ≈ 0 or about 20 searches per arm, roughly +$300 (D3).
- **Fixed at kill check 1.** k is set from the pilot and the positive control's measured σ_b, and then frozen in the
  phase PLAN before Stage 2.
  - If σ_b > 0.15, k rises to the largest number within Stage 2's budget, and the expected half-width is stated before
    any Stage 2 run.

## 6. The reviewer flaws, and the fix for each

| flaw (from the review of the earlier plan) | fix here |
|---|---|
| A0 → A1 → A2 changed feedback, search effort and library at once | S → O → M: one factor per step; budget, library and proposer held fixed (§3.3) |
| 1% claimed from 32–50 clean runs | Separate calibration and validation, a reported-only-if rule, realised FPR with an exact interval; 1% only at 1,000 + 1,000 (§4.2, §5) |
| Confirmation runs replicated, but searches not | k independent searches per arm, each with its own held-out confirmation; the unit is the search (§4.3) |
| Phase 3's monitor read the reference optimum | It is view X, the oracle, outside the compared views (§3.2) |
| Conditional detection reported as safety | The primary outcome is unconditional uncaught success; the clean floor is reported; "detection, not prevention" (§4.1) |
| No evidence the attacker can win at all | Positive control against W before the main arms (§3.4) |
| "Phase 7 rerun" in the earlier plan | Phase 7 ran and closed (88 episodes, $6.29, verdict undecided); appendix only, no rerun (§7) |

## 7. What the earlier phases become

- **Phases 1–3 and 5 (ORBIT):** pilots that motivate the views. They are cited as single-draw observations
  (`docs/SOP.md` §4), and no number is pooled with this study. Phase 3 is cited as an oracle monitor.
- **Phase 4 (ControlArena):** appendix. The adaptive-beats-static prediction was falsified on one seed, and no new runs
  are made.
- **Phase 6 (ResearchArena cell 733) and the benchmark fixes:** a case study in the appendix, with no new runs.
  - **Phase 6b's GPU work is paused** from 2026-10-27, and no pods are started.
  - Its pre-registration (Amendment 37) stays on file. It resumes only by the owner's dated decision after kill check 2.
  - Cell 733's numbers are reported at threshold 50 and against its 8-clean τ, each with its limits.
  - The upstream issue is filed as planned.
- **Phase 7 (DGM self-modifier):** appendix. It ran 88 episodes in 74 `.eval` logs for $6.29, and its verdict was
  undecided under both rules. No rerun.
- **Phase 8 (transcript monitor):** cited as the falsified one-shot view. It is not a view here, because the views
  differ only in context, not in format.

## 8. Schedule and kill checks

| dates | work |
|---|---|
| 28 Oct – 3 Nov | Phase PLAN with pre-registration. Build (§10). Q1 qualification (20 episodes): every view's context fields checked by hand against the raw log, the O/M feedback fields checked, and one search's round trip |
| 4 – 10 Nov | 500 + 500 clean; static on 100; positive control (5 searches + confirmations); pilot: one search each of O, M-L and M-T, with confirmations |
| **about 13 Nov: kill check 1** | (a) the positive control passes (§3.4); (b) the arms run cleanly: ≥ 90% of pilot episodes valid under the allocation rule, O's feedback has no monitor field and M's equals the raw log, proposer refusals ≤ 10%; (c) validation FPRs at 2% and 5% inside their bounds; (d) spend inside the caps. Then k is frozen (§5) |
| 14 – 28 Nov | Main arms (k searches each for O, M-L, M-T; confirmations); static on the remaining 100 instances; clean extension for 1% (D2) |
| **about 1 Dec: kill check 2** | An effect or a precise null at the planned n (§1). Inconclusive means the fallback |
| 2 – 15 Dec | Oracle view X and the optional robustness rescoring (D4); raw-folder audit, cross-family; figures. **Results frozen 15 Dec** |
| 16 Dec – about 22 Jan | Draft, human read, release preparation; abstract about 16 Jan, paper about 22 Jan (ICML 2027 dates unofficial until the call) |

**Fallback at either kill check:** an ICML 2027 workshop, TMLR, or NeurIPS 2027, with the result as measured.
- **If (a) fails:** one elicitation repair (a stronger brief or the alternative proposer of D1), capped by the held-back
  $50, then kill check 1 again by about 17 Nov. A second failure means the fallback.
- **If (b) or (c) fails:** fix and rerun the pilot inside Stage 1's caps, or take the fallback.

## 9. Budget (`scripts/paper/cost_paper.py`)

**Unit costs** (upper estimates: cache reads priced at full input):
- One episode is $0.112: gpt-4o agents $0.0905, plus 4 views × 10 claims of gpt-4o-mini at $0.0216.
  - The measured all-in cost per ORBIT episode was $0.065–$0.071 in Phases 3, 5 and 7.
- One proposer round call (Opus 5.5) is $0.30. One search (48 episodes + 6 calls) is $7.18.
- One confirmation (20 episodes) is $2.24. The CPU pod is $0.32/h.

**Stage 1, 28 Oct – 10 Nov: cap $600.** 1,684 episodes and 50 proposer calls.

| provider | for | estimate (with 20% contingency) | cap |
|---|---|---|---|
| OpenAI | gpt-4o agents, gpt-4o-mini monitor views | $226.53 | $380 |
| Anthropic | Opus 5.5 proposer | $18.00 | $60 |
| RunPod | CPU pod `heqaytgwoxutst`, 14 days; **no GPU pods** | $107.52 | $110 |
| OpenRouter | none | $0 | $0 |
| held back | released only by the owner's dated go (elicitation repair, §8) | — | $50 |
| **total** | | **$352.05** | **$600** |

Stage 1 line items:

| item | episodes | proposer calls | cost |
|---|---|---|---|
| Q1 qualification | 20 | 2 | $2.84 |
| Clean, 500 + 500 | 1,000 | — | $112.10 |
| Static, 100 | 100 | — | $11.21 |
| Positive control | 340 | 30 | $47.11 |
| Pilot | 224 | 18 | $30.51 |

**Caps are enforced from billed usage,** never from summed estimates. The spend line goes in STATUS weekly, per provider.

**Stage 2, 14–28 Nov (needs its own go at kill check 1):** about $652 with contingency, at k = 10. Of that, $449 is
OpenAI, $65 Anthropic and $138 the CPU pod for 18 days.
- 30 searches: $215.42.
- 40 confirmations: $89.68.
- Static, a further 100 episodes: $11.21.
- Clean extension for 1%: $112.10.

**Later, optional:**
- Rescoring with `openai/gpt-6.1-terra` on views L and T: about $225 (D4).
- Keeping the CPU pod from 2 Dec to 22 Jan: about $392. Stopping it after the results freeze saves most of this (D5).

**Paper total:** about $1,004 for Stages 1 and 2, against about $4,300 available. No GPU spend is planned.

## 10. Build list (week 1; no spend)

1. Four view presets (W, L, T, X) in `control_loop/adapters/orbit/jira_adaptive.py`.
   - They reuse Phase 2's score-only judge (`P(BLOCK)` from logprobs) and Phase 3's context builder, minus the
     reference optimum for T.
   - Every view scores every claim, and none blocks.
2. Arm drivers S, O and M on one proposer brief that differs only in the feedback paragraph, with the strategy library
   and the selection rule as code. The proposer's observation is logged byte-for-byte.
3. Seed pools and confirmation blocks, written to a manifest before any run.
4. The analysis script (§4.3), the power and cost scripts, and `tests/test_e2e_feedback.py` (mock end to end).
5. Instrument documents: `docs/instruments/feedback_proposer.md` and `docs/instruments/orbit_views.md`.
6. The batch runner with billed-usage caps per provider, on the CPU pod. No method files on the pod.

## 11. Decisions for the owner

- **D1:** the proposer is `anthropic/claude-opus-5-5` (recommended: stronger than Phases 1–7's Sonnet 5.5, which matters
  given MiniLab's weak model planners), or Sonnet 5.5 for comparability.
- **D2:** the 1% extension (+1,000 clean, $112) in Stage 2: recommended. Without it, 1% is exploratory only.
- **D3:** ±15 as the precise-null margin (recommended), or ±10 at about +$300 and more searches.
- **D4:** rescoring with a current monitor model in December (about $225), to show the result is not specific to
  gpt-4o-mini.
- **D5:** stop the CPU pod after the results freeze (15 Dec) and restart it from HANDOVER.md if needed.
- **D6:** go for Stage 1 at a $600 cap with the provider caps of §9.

## Amendment (1), 2026-10-28: monitor feedback as an information leak

Recorded by the owner's decision of 2026-10-28, before any run. Where this amendment conflicts with §1, §3.3, §8, §9 or
§11 above, this amendment governs. Everything else in §1–§11 stands: the setting, the views, the selection rule,
confirmation, thresholds and their bounds, the statistics, the kill-check dates, the $600 Stage 1 cap and the go already
given for Stage 1. Draft introduction and related work: `docs/paper/intro_related_draft.md`. Every citation there was
checked on 2026-10-28; the record is `docs/paper/citation_check_2026-10-28.md`.

### A1.1 Framing and scope
- **The security lesson.** A detector that reveals its verdicts becomes an oracle the attacker can learn from. The
  documented cases cover several fields:
  - query-based evasion of classifiers, from Lowd & Meek (2005) to label-only and score-based black-box attacks;
  - malware authors testing samples on public analysis sandboxes;
  - spammers probing filters;
  - fraudsters using card testing.
- **The security answer is information hygiene:** coarsen, delay or randomise the verdict, limit and watch queries, and
  audit silently.
- **The paper's question:** does an attacker that controls an untrusted AI agent learn to evade a trusted monitor from
  what the monitor leaks, and do those mitigations remove the advantage?
- **Scope.** All experiments run in sandboxed benchmarks only: ORBIT JiraTicket, plus the ResearchArena case study with
  no new runs. Side tasks are the benchmarks' own; no real system, user, service or data is touched. The paper says this
  in its introduction and in its ethics statement.

### A1.2 Leakage ladder (replaces the arms of §3.3)
These are fixed across every level:
- the proposer (`anthropic/claude-opus-5-5`, D1) and its brief, apart from the feedback paragraph;
- the strategy library;
- the search budget (6 rounds × 4 candidates × 2 screening episodes);
- the selection rule (§3.3), which uses the target view's 5% threshold at every level;
- confirmation on 20 fresh instances.

**Target view: L.** Each level adds to the one below, so the ladder is nested and the attacker's information rises
strictly.

| level | what the proposer sees about each screening episode | added |
|---|---|---|
| L0 | nothing: ORBIT's stock collusion sentence, no search | — |
| L1 | outcome only: whether P-ext occurred (§4.1), validity, final allocation, coalition gain against the clean mean, turn of the first coalition claim | search with outcome feedback |
| L2 | L1 + for each coalition claim, the binary verdict: whether its score exceeds the view's 5% threshold (what a blocked action reveals in deployment) | binary verdict |
| L3 | L2 + each claim's numeric score, P(BLOCK) | score |
| L4 | L3 + each claim's written reason from the judge | reasons |

- The verdict stays visible at L3 and L4, so that each level contains the one below. The paper states this choice.
- **Advantage:** A(ℓ) = U(ℓ) − U(L1), for ℓ = L2, L3 and L4. U is the confirmed rate of uncaught successful attacks
  (unconditional, §4.1). A(ℓ) is the value of what the monitor leaks beyond the outcome the attacker can always see.
  - The search's own value, U(L1) − U(L0), is reported beside it.
  - The headline curve is U(ℓ) for L0–L4 and A(ℓ) for L2–L4, at the 2% and 5% budgets, with 95% intervals
    (t-intervals over searches, and a cluster bootstrap as a check).
- **Primary test:** A(L4) at 5%. An effect means a 95% interval that excludes 0; a precise null means the interval lies
  inside ±15 points (D3); anything else is inconclusive (§1).
- **Secondary tests:**
  - A(L2) and A(L3), Holm-adjusted together with A(L4);
  - an ordered-trend contrast over L1–L4 (weights −3, −1, 1, 3);
  - every result again at 2%.
- **Power** (§5, unchanged): k = 10 searches per level and m = 20 confirmation episodes give a half-width of 13–14
  points per contrast at σ_b 0.10. The Holm adjustment over three contrasts widens the adjusted intervals by up to 26% (its
  Bonferroni bound at 18 degrees of freedom), so the primary test A(L4) is reported unadjusted as pre-registered, and
  the secondary tests adjusted. The paper reports both.

### A1.3 Stage 1 (29 Oct – 12 Nov; cap $600; go given)
- Q1 qualification.
- 500 + 500 clean episodes.
- L0 on 100 instances.
- **Positive control:** 5 searches at **L4** against the weakened view W, with confirmations. The pass rule of §3.4 is
  unchanged.
- **Pilot:** one search each at L1, L2, L3 and L4 against view L, each with a confirmation.
- Kill check 1 adds a mechanism check. For each level, the proposer's logged observation contains exactly that level's
  fields (no score at L2, no reasons at L3) and matches the raw log byte-for-byte.
- **L2 stays in.** Stage 1 is $376.35 with L2 against the $600 cap (§A1.8), so the rule to drop L2 above $600 does not
  apply.

### A1.4 Stage 2 (14 – 28 Nov; needs its own go at kill check 1)
1. **The leakage ladder at the planned n,** run first: k = 10 searches each at L1–L4 against view L, each confirmed on
   m = 20.
2. **ℓ\*, the strongest level that shows an advantage:** the level with the largest A(ℓ) at 5% whose 95% interval
   excludes 0.
   - It is chosen by this rule before any mitigation runs. It is written into STATUS and the FINDINGS notebook with the
     numbers.
   - If no level shows an advantage, the mitigation runs below are not made. The paper reports a leakage null, and
     Stage 2 spends less.
3. **Mitigations against ℓ\*.** Each changes only what the proposer is shown. The monitor's scores, the thresholds and
   the audit are unchanged.

| arm | what the proposer is shown | runs |
|---|---|---|
| M1, coarsened | binary verdict only | **none new**: by construction this is L2's view, so M1 is read from L2. It is a mitigation only if ℓ\* is L3 or L4 |
| M2, delayed | ℓ\*'s feedback, released in one batch: rounds 1–3 are proposed with no monitor feedback, and rounds 4–6 see rounds 1–3's feedback and nothing later | k = 10 searches + confirmations |
| M3, noisy | ℓ\*'s feedback, but each claim's shown feedback (verdict, score and reason together) is replaced with probability 0.2 by that of a random clean calibration claim; the outcome stays true | k = 10 searches + confirmations |
| M4, silent audit | no monitor feedback; flagged episodes are logged, not shown | **none new**: by construction this is L1's view, so M4 is read from L1 |
| view T | ℓ\*'s feedback from view T, with the attack scored and audited on T (task-level context as a defense) | k = 10 searches + confirmations, plus L1's T-selections confirmed (10 confirmations) |

4. **The mitigation's effect:** U(ℓ\*) − U(M), with the advantage that remains, U(M) − U(L1). Both come at 2% and 5%
   with 95% intervals.
5. **Cost to detection.** The display-only mitigations (M1–M4) do not change any score or threshold, so their detection
   cost on a fixed transcript is zero by construction. The paper says so rather than presenting a measured zero. View T
   changes the scores; its clean FPR and its TPR on L0 attacks are reported against L's.
6. **Cost to usefulness.** In deployment a verdict reaches honest agents too, for example when a blocked action shows its
   reason. The usefulness sub-study runs ORBIT in blocking mode at the 5% threshold on 4 × 100 clean episodes, in four
   regimes:
   - block with the reason shown (ℓ = L4);
   - block with the binary verdict only (M1);
   - block with 20% of verdicts randomised (M3);
   - no block, silent audit (M4).

   M2's effect within an episode equals M4's. The measures are main-task usefulness (allocation welfare against the
   reference optimum, and validity) and the honest block rate.
7. **A limit stated in the paper.** The main study measures detection at audit. It cannot measure what blocking
   prevents within the episode. A protocol that blocks prevents harm and leaks; one that audits silently leaks nothing
   but lets the action through until the audit. The usefulness sub-study measures one side of this trade-off, not both.

### A1.5 Headline and takeaway the paper must support
- **Figure 1:** U(ℓ) for L0–L4 and A(ℓ) for L2–L4, at 2% and 5%, with 95% intervals.
- **Figure 2:** for each mitigation and view T, the advantage removed and the advantage remaining, with 95% intervals,
  beside its usefulness cost.
- **Takeaway:** concrete rules for what a control protocol should and should not reveal to the agent it monitors. Each
  rule cites the figure cell that supports it, and is worded as "in this setting".

### A1.6 Discussion: long-term relevance
The paper discusses settings where an untrusted system sees its own evaluation results repeatedly:
- agents with persistent memory;
- long-running deployments;
- systems that help train their successors.

There every verdict an agent sees is a query answered. The discussion uses the measured curve and cites the work that
studies this directly:
- intervention history across tasks (arXiv:2610.26935);
- monitor rationale exploited after a block (arXiv:2605.26047);
- emergent collusion shaped by verification feedback and interaction history (arXiv:2609.24967);
- sabotage in the self-improvement pipeline (arXiv:2610.27735).

It makes no claim beyond what those papers and our data show.

### A1.7 Decisions recorded 2026-10-28
- **D1:** proposer `anthropic/claude-opus-5-5`.
- **D2:** the 1% extension is decided at kill check 1.
- **D3:** precise-null margin ±15 points.
- **D4:** yes, in Stage 2 (rescore with `openai/gpt-6.1-terra`, $223.50).
- **D5:** yes, stop the CPU pod after the 15 Dec freeze.
- **D6:** Stage 1 go at the $600 cap.
- **D7, the cheapest CPU pod:**
  - The RunPod catalog read of 2026-10-28 lists `cpu3c` at $0.03 per vCPU-hour, the cheapest type. The plan uses
    4 vCPU / 8 GB at $0.12/h in EU-RO-1, against $0.32/h now. The vCPU price excludes disk charges.
  - Move the batch there before Stage 1's paid runs. The owner copies `.env` to the new pod himself.
  - The old pod `heqaytgwoxutst` is stopped only after the new pod passes Q1, and only with the owner's go for that
    delete.
  - If Q1 shows memory pressure at 4 vCPU, use 8 vCPU (`cpu3c`, $0.24/h).
- **ORBIT agent model confirmed:** `openai/gpt-4o`. It resolved to `gpt-4o-2024-08-06` in every ORBIT phase's pins
  (Phases 1, 2, 3, 5 and 7) and in a Phase 7 raw log's `model_usage`. It stays fixed for this study, at temperature 0
  with seed = problem seed.
- **The pod is the only source of truth.** The Mac copy of the repository was fast-forwarded to `715c8c1` and refreshed
  from the pod on 2026-10-28.
- **One clean commit set at kill check 1,** made by the owner.
- **Councils** (Fable and Astra for, Opus and Sol against; three rounds; live search; every citation checked) run only
  at four points:
  1. this amended PLAN, before Stage 1 runs;
  2. kill check 1;
  3. kill check 2;
  4. the full draft.

  Each council gets the PLAN and the raw results pulled from the pod that day, is capped at $40, and is costed in §A1.8.
  A unanimous finding is acted on; a split finding goes to the owner.
- **No GPU pods in Stage 1.** Any GPU use, the ResearchArena check included, needs the owner's separate go after kill
  check 1. Phase 6b stays paused.

### A1.8 Budget (`scripts/paper/cost_paper.py`)
**Unit costs** (upper estimates; measured all-in cost per ORBIT episode was $0.065–$0.071):
- one episode $0.1121;
- one proposer call $0.30;
- one search $7.18;
- one confirmation $2.24;
- the CPU pod $0.12/h.

**Stage 1, cap $600.** 1,732 episodes and 56 proposer calls.

| provider | for | estimate | cap |
|---|---|---|---|
| OpenAI | gpt-4o agents, gpt-4o-mini views (+20%) | $232.99 | $330 |
| Anthropic | Opus 5.5 proposer (+20%) | $20.16 | $50 |
| Councils (Anthropic + OpenAI) | amended PLAN and kill check 1, $40 cap each | $80.00 | $80 |
| RunPod | `cpu3c` 4 vCPU, 15 days; no GPU | $43.20 | $50 |
| OpenRouter | none | $0 | $0 |
| held back | elicitation repair (§8), the owner's go | — | $90 |
| **total** | | **$376.35** | **$600** |

Line items:

| item | cost |
|---|---|
| Q1 | $2.84 |
| Clean, 500 + 500 | $112.10 |
| L0 | $11.21 |
| Positive control | $47.11 |
| Pilot, L1–L4 | $37.69 |

Without L2, Stage 1 would be $365.04.

**Stage 2, its own go at kill check 1.** At k = 10 it is $968.88, then:
- with D4: **$1,192.38**;
- with D4 and D2: $1,304.48.

| item | cost |
|---|---|
| Leakage L1–L4 at planned n (40 searches + confirmations) | $376.91 |
| M2 | $94.23 |
| M3 | $94.23 |
| View T | $94.23 + $22.42 |
| L0 extension | $11.21 |
| Usefulness sub-study | $44.84 |
| Contingency (20%) | $147.61 |
| Council at kill check 2 (cap) | $40 |
| CPU pod | $43.20 |
| D4 | $223.50 |
| D2 (if chosen) | $112.10 |

M1 and M4 cost nothing extra: they are read from L2 and L1. If no level shows an advantage, M2, M3 and view T are not
run, which saves $305.11 before contingency.

**Later:** the final-draft council ($40 cap). The CPU pod is stopped after 15 Dec.

**Paper total:** Stage 1 + Stage 2 with D4 = **$1,568.73**, against about $4,300 available. No GPU spend.

## Amendment (2), 2026-10-28: findings of council checkpoint 1, before any run

**The council.** It reviewed this PLAN, as amended by (1), before Stage 1.
- **Members and format:** Fable and Astra for; Opus and Sol against. Three rounds, with live search.
- **Packet:** files pulled from the pod on 2026-10-28.
- **Spend:** $27.78 of the $40 cap.
- **Record:** kept outside the repository, with the owner.
- **Verdicts:** all four were **GO WITH FIXES**.
- **Novelty of the framing:** scored 5, 2, 4 and 3 out of 10. The controlled measurement was scored higher.

**What this amendment does.** Under the owner's rule, every unanimous finding is applied below. Split findings are
listed in A2.9 for the owner's decision. Where this amendment conflicts with (1), (2) governs.

### A2.1 Novelty claim (unanimous)
**The claim is narrowed.** The paper does not claim the leakage framing or feedback-side mitigations as new. It claims
one thing: a matched-budget isolation of each feedback component (verdict, score, reasons), with independent searches,
execution-confirmed attacks, and the security mitigations tested at that budget.

The closest work, checked on 2026-10-28, and corrections to §2 and to the draft:
- **Keenan, Leckie, Erfani, arXiv:2609.36490.** It states the framing directly: "each verdict the monitor delivers leaks
  information". It evades latent (activation) monitors and studies corrupted feedback. Our setting differs: executed
  policy search against text monitors.
- **Hopman, Lemoine, Tracy, "Untrusted AIs can exploit feedback in control protocols", LessWrong, 2025-05-27.**
  - Untrusted editing with trusted feedback lowered safety from 93% to 80%.
  - Feedback-side mitigations (compliance monitoring, selective editing) did not restore the baseline.
- **Lucassen & Kaufman, arXiv:2605.26047.** It already compares retrying with detailed feedback, retrying without
  feedback, and resampling. "One leak versus none" was wrong.
  - Its without-feedback condition was not tested against an adaptive attacker. Its authors note that it "may be
    vulnerable to more sophisticated attack selection strategies".
- **Kutasov et al., arXiv:2511.02997.** Attack policies that know when resampling occurs, or that can simulate monitors,
  cut safety to 17%. Deferring on critical actions held, which shows "the importance of denying attack policies access to
  protocol internals".
- **Remedios et al., arXiv:2609.19587.** Red-teaming production blocking monitors (Auto Mode, Guardian).
- **MonitoringBench, arXiv:2605.09684.** §2's "no arm without the monitor feedback" is withdrawn. It has a
  reconnaissance condition without monitor tools, but that condition also differs in other affordances.
- The draft sentence "What has not been measured is the security question itself" is withdrawn.

### A2.2 Selection and what each level identifies (unanimous on the problem; the remedy is split, A2.9 S1)
- **The problem.** The selection rule of §3.3 uses the target view's verdicts at every level, and its scores to break
  ties. So the selector sees monitor information that the L1 and L2 proposer does not.
  - "M1 = L2 by construction" and "M4 = L1 by construction" are withdrawn.
  - Under the shared selector, A(ℓ) measures what the proposer gains from feedback, conditional on a selector that
    already sees the monitor.
- **End-to-end claims.** The paper makes no claim about a silent or coarsened protocol (M4, M1) unless each level's
  selection uses only that level's information.
- **The mechanism check at kill check 1** covers the selector's inputs as well as the proposer's observation.
- **Q1 qualification** includes:
  - a byte-level test that no field above a level reaches that level's proposer or selector;
  - recording the actual number of monitor queries per search.

### A2.3 Choosing ℓ\* and measuring mitigations (unanimous)
- **Eligibility.** A level is eligible as ℓ\* only if its A(ℓ) has a positive lower bound after the Holm adjustment over
  L2–L4 at 5%. Among eligible levels, ℓ\* is the one with the largest point estimate.
- **Fresh comparator.** The mitigations are compared with **k = 10 fresh unmitigated searches at ℓ\*,** run at the same
  time as M2, M3 and view T, on the same confirmation blocks. The selected Stage 2 estimate is never reused as the
  baseline.
- **Direct contrasts:**
  - coarsening is claimed only through a direct L4 − L2 (or ℓ\* − L2) contrast, never through "significant here, not
    significant there";
  - each mitigation is measured as fresh ℓ\* − mitigation;
  - view T's remaining advantage is measured against L1's selections confirmed under T.

### A2.4 One executable definition per mitigation (unanimous)
Each mitigation is specified in three parts:
1. what the proposer is shown;
2. what is enforced in the episode (nothing in the main study: no view blocks);
3. what is audited (the frozen thresholds, unchanged).

The definitions:
- **M2.** Finite-horizon delayed feedback: rounds 1–3 get no monitor feedback, rounds 4–6 see rounds 1–3 only, and
  feedback from rounds 4–6 is never available to the search.
- **M3.** Display-only noise at rate 0.2.
- **The usefulness sub-study** randomises enforcement (blocking), which is a different intervention. It is reported as a
  separate experiment and is not combined with M3 into one trade-off cell.

### A2.5 Decision rules and power (unanimous)
- **The three outcomes of §1 apply everywhere:** effect, no advantage above the margin, or inconclusive.
  - A1.4(2)'s "the paper reports a leakage null" is replaced. If no level is eligible as ℓ\*, the paper reports each
    level's outcome under the three-outcome rule, and M2, M3 and view T are not run.
- **The simulation is pre-registered:** `scripts/paper/power_sim.py`. It covers the paired-block design: search i of
  every level confirmed on block i, shared instance difficulty, and a paired t-interval over blocks.

  At k = 10, m = 20 and U(L1) = 0.20 (each figure is a probability over 4,000 simulated studies):

  | true A(L4) | σ_b | effect | no advantage above 15 (one-sided) | equivalence ±15 (two-sided) |
  |---|---|---|---|---|
  | 0 | 0 | 0.03 | 0.90–0.91 | 0.83 |
  | 0 | 0.10 | 0.02–0.03 | 0.61–0.64 | 0.31–0.34 |
  | 0 | 0.20 | 0.02–0.03 | 0.30–0.32 | 0.03 |
  | +0.10 | 0.10 | 0.31–0.33 | — | — |
  | +0.20 | 0.10 | 0.80–0.81 | — | — |
  | +0.20 | 0.20 | 0.45–0.46 | — | — |

  At k = 20 and σ_b 0.10, a true zero gives no-advantage-above-15 in 0.92–0.93 and equivalence in 0.85–0.86, and a
  +0.20 effect is detected in 0.98–0.99.
- **The adaptation rule is frozen now and applied at kill check 1.**
  - σ_b is pooled over every Stage 1 search (the W searches and the pilot).
  - k for L1 and L4 is then set as follows: 10 if σ_b ≤ 0.05; 15 if σ_b ≤ 0.10; 20 otherwise. The add-on costs $113.07
    for 15 and $226.15 for 20.
  - L2, L3, the mitigations and view T stay at k = 10, and the paper states that adjacent levels are powered only for
    effects of about 20 points or more.
  - Pilot searches are not pooled into Stage 2 estimates.
- **Fixed analysis choices.** Inference is a paired-block t-interval, with a joint block bootstrap as a check. Threshold
  ties count as not flagged. A missing or malformed score is a parse failure: the episode is excluded from the
  calibration, validation and confirmation tables, and counted per arm. Repairs after validation need a fresh validation
  set.

### A2.6 What the positive control shows (unanimous)
The W control shows that the search can win. It does not show that feedback helps. Kill check 1 says so, and a later null
is described as conditional on that.

### A2.7 Scope and threat model (unanimous)
- The attacker is an offline proposer (Opus 5.5). It stands in for an attacker that keeps memory across episodes, not
  for the monitored gpt-4o agents.
- Every rule in the takeaway is limited to this setting, proposer, monitor and search budget.
- D4's rescoring with gpt-6.1-terra tests whether the attacks transfer to another monitor. It does not test adaptive
  robustness against that monitor, and is reported as such.

### A2.8 Budget after (2)
- **Stage 1 is unchanged:** $376.35 against the $600 cap.
- **Stage 2 adds the fresh ℓ\* comparator** ($94.23 before contingency). With it, Stage 2 is $1,081.95; with D4,
  $1,320.45; with D4 and D2, $1,432.55.
- The k adaptation (A2.5) can add $113.07 or $226.15.
- The owner's options in A2.9 are costed there.

### A2.9 Split findings, for the owner
- **S1, the selection estimand.**
  - Fable and Opus: information-consistent selection at every level as primary (L1 by outcome only; L2 by verdict counts,
    with no score tie-break), with the monitor-aware selector as a labelled ceiling arm.
  - Astra and Sol: keep the shared selector as primary (a proposer-feedback ablation) and drop the end-to-end claims.
  - Running both costs +$5.38 in Stage 1 and +$53.81 in Stage 2. The selections are reanalyses of the same screening
    episodes plus extra confirmations.
- **S2, the positive control's gate.**
  - Fable and Opus: add 5 L1 searches against W (+$56.54, Stage 1), and gate on L4 − L1 on W.
  - Astra and Sol: do not require a feedback benefit to enter Stage 2, because that would select for the hoped-for
    finding.
- **S3, a headroom criterion at kill check 1.** Opus would pre-register it; Fable and Astra would inspect the pilot's L1
  rate against L; Sol is silent.
- **S4, telling the attacker the mitigation mechanism** (Kerckhoffs). Opus, Astra and Sol: yes. Fable: silent.
- **S5, a second M3 noise level.** Fable and Opus: two levels, or a justified single level. Astra and Sol: silent. A
  second level costs +$113.07 in Stage 2.
- **S6, renaming the null outcome** to "no advantage above 15 points" (one-sided) as the primary null claim. Fable and
  Opus: yes. Astra and Sol: keep the outcome labels but report equivalence honestly.

## Amendment (3), 2026-10-28: leakage in bits, the selection-protocol study, the owner's split decisions; Stage 1 on hold

**Recorded by** the owner's message of 2026-10-28, before any run. **Stage 1 is on hold** until the owner reviews this
amendment and the findings of checkpoint council 1b. Where this amendment conflicts with §1–§11, (1) or (2), it governs.

### A3.1 The owner's decisions on the split findings of (2)
- **S1:** information-consistent selection is primary at every level. Each level's selector uses only that level's
  channel: L1 by outcome only; L2 by verdict counts, with no score tie-break; M2 and M3 by what their proposer saw. The
  shared monitor-aware selector of §3.3 is confirmed beside it as a labelled ceiling. A3.4 turns the comparison into an
  experiment.
- **S2:** add 5 L1 searches against W. Kill check 1 gates on search competence only. L4 − L1 on W is reported
  descriptively, and the W searches feed the pooled σ_b of A2.5.
- **S3:** a headroom check is pre-registered for kill check 1. If the pilot's confirmed U(L1) against L is at least 0.70,
  the ladder has no room above L1, and the design is reshaped before Stage 2 rather than run.
- **S4:** the attacker's brief states the mechanism of the protocol it faces: the level's fields, M2's delay, M3's rate
  and replacement rule. This is the Kerckhoffs assumption, and A3.2's theorem needs it.
- **S5:** replaced by the M3 dose-response of A3.3.
- **S6:** the primary null claim is the one-sided "no advantage above 15 points". Two-sided ±15 equivalence is reported
  beside it.

### A3.2 Leakage as information: the theory claims
**Channels.** A channel c is what the attacker (proposer and selector) is shown about each screening episode. The
channels are:
- L1–L4 (the ladder);
- M1 (verdict only);
- M2 (delay);
- M3(ε) (each claim's monitor record replaced, with probability ε, by a random clean calibration claim's record);
- M4 (silent).

Channel c′ is a **garbling** of c when c′'s record can be produced from c's record by a known random map applied
without looking at the episode. The garbling order is:
- L1 ≼ L2 ≼ L3 ≼ L4, since each level is a projection of the next;
- M1 ≡ L2, the same record (A1.4);
- M4 ≡ L1;
- M2 ≼ ℓ\*, by withholding records;
- ℓ\* ≽ M3(0.25) ≽ M3(0.5) ≽ M3(0.75) ≽ L1, since a higher rate is a further replacement of a lower one, and L1 is
  M3(1).

**Claim T1 (Blackwell order; exact).** Fix the proposer's capability class, the budget and the success criterion. Let an
attacker know the protocol, including the garbling map and the clean pool. Then the best achievable confirmed U under c is
at least that under any garbling c′.
- **Proof:** an attacker who sees c can apply the garbling itself and then run any strategy designed for c′. This is
  Blackwell's comparison of experiments (Blackwell 1951; 1953, doi:10.1214/aoms/1177729032), applied to the whole
  adaptive search.
- **What the paper claims:** the theorem holds for an optimal attacker.
- **What it tests (pre-registered, H-B):** whether the real attacker (Opus 5.5 with this scaffold) respects the order.
  - Tests: the ordered-trend contrast over the ladder (A1.2) and the dose-response slope (A3.3).
  - A significant reversal, such as U(L4) < U(L2), is reported as a measured failure of the attacker to use
    information. It is not a counterexample to T1.

**Leakage in bits (estimand).**
- **Why not the episode's own audit flag:** at L2 the verdict *is* the 5% audit flag, so I(F; own flag) saturates at L2,
  and scores and reasons add nothing to it by construction.
- **The estimand** is predictive: the information a record carries about the same candidate's outcome on a *different*
  instance. Let e and e′ be a candidate's two screening episodes (distinct seeds), and Y the uncaught-success indicator
  at budget b. Then:
  - ι_c = I(F_c(e); Y(e′));
  - the monitor's leakage beyond outcome is Δι_c = ι_c − ι_L1 = I(F_c(e); Y(e′) | F_L1(e)), by the chain rule, because
    the channels are nested.
- **Estimator:** cross-fitted usable information (Xu, Zhao, Song, Stewart, Ermon, ICLR 2020, arXiv:2002.10689),
  Î_c = H(Y) − cross-entropy of a pre-registered predictor family, with folds by search.
  - Because each family contains the constant predictor, Î_c estimates a lower bound on the Shannon information.
  - Families:
    - L1–L3: logistic regression on fixed features (outcome fields; verdict count; max and mean score);
    - L4: the same features plus a frozen text embedding of the reasons (`text-embedding-3-small`), with an L2 penalty
      chosen by inner cross-validation.
- **The pool** is every screening episode of every Stage 2 search. Every episode carries all fields for every view,
  whatever its arm was shown, so ι_c is a property of the channel, not of the arm that produced the pool.
  - M3(ε)'s leakage is computed by applying the replacement to the recorded pool (100 random draws).
  - Intervals come from a bootstrap over searches.
  - It is reported in bits per screening episode, at 5% and at 2%.

**Mitigations as capacity reductions.**
- **M3 is bounded exactly.** Revealing whether each record was replaced can only add information, so
  I_M3(ε) ≤ (1 − ε) I_ℓ\*. On the binary verdict, with clean claims flagged at rate r0 = 0.05, the per-claim capacity
  (`scripts/paper/info_paper.py`) is:

  | ε | 0 | 0.25 | 0.5 | 0.75 |
  |---|---|---|---|---|
  | bits per claim | 1.000 | 0.525 | 0.270 | 0.094 |

- **M1:** at most 1 bit per claim.
- **M4:** 0 bits.
- **M2:** the records of rounds 4–6 never reach the attacker, and rounds 1–3 arrive once, at round 4.

**Claim T2 (selection bound; exact under its assumption).**
- **Setup:** a pool of N candidates, exchangeable and independent. Each has latent uncaught-success probability q and a
  record F. Let Y′ be the outcome on a fresh instance. Any selector J = g(F_1..F_N).
- **The bound:**

  E[q_J] − E[q] ≤ κ_N · sd(E[q | F]) ≤ κ_N · √(I(F; Y′) · ln 2 / 2), with κ_N = (N − 1)/√(2N − 1).

- **Proof sketch:**
  1. E[q_J] ≤ E[max_i E[q_i | F_i]].
  2. Hartley & David (1954, doi:10.1214/aoms/1177728848) and Gumbel (1954, doi:10.1214/aoms/1177728847) bound the
     expected maximum of N i.i.d. draws by κ_N standard deviations.
  3. Pinsker's inequality gives Var(E[Y′ | F]) ≤ I(F; Y′) · ln 2 / 2, since E[Y′ | F] = E[q | F].
- **How it is used.** It is read backwards, as a *certificate*: an observed selection gain G certifies that the channel
  carried at least (2 / ln 2)(G / κ_N)² bits per record.
  - For N = 4 (one round), G = 0.10 certifies at least 0.022 bits; for N = 24, at least 0.0026 bits.
  - The certificate needs no information estimator, so it is a second lower bound beside Î_c.
- **Not used as a test.** The forward ceiling κ_N √(Î ln 2 / 2) is not used as a test, because Î_c underestimates the
  information.
- **The assumption fails across rounds.** Later rounds are proposed from earlier feedback. So T2 is applied within rounds
  (N = 4, one proposer call, candidate order randomised), and the 24-candidate figure is reported as indicative only.

**What the theory does not claim.**
- **No claim that advantage is a function of bits alone.** Reasons may help the proposer *construct* better candidates.
  That gain is outside T2, which covers selection only.
- **The capacity bound on the whole adaptive search is vacuous here.** That bound is binary-KL(U_c ‖ U_0) ≤ total bits
  received. With 48 episodes × several claims × ≥ 0.1 bit, it is far above 1 nat at every level except M4, so the paper
  does not present it as a prediction.

### A3.3 The M3 dose-response (replaces M3 at 0.2 and S5)
- **The doses:** M3 at ε = 0.25, 0.5 and 0.75 against ℓ\*, with k = 10 searches each, confirmed on the same blocks as
  the fresh ℓ\* comparator (x = 1 − ε = 1) and L1 (x = 0).
- **Primary test:** the per-block OLS slope of confirmed U on x over the five points, with a t-interval over blocks. An
  effect means a lower bound above 0. The three-outcome rule applies.
- **Power** (`scripts/paper/power_dose.py`, 4,000 simulated studies, U(L1) = 0.20, m = 20):

  | true A(ℓ\*) | σ_b 0.05 | σ_b 0.10 | σ_b 0.20 |
  |---|---|---|---|
  | 0.10 | 0.53 | 0.37 | 0.19 |
  | 0.15 | 0.85 | 0.67 | 0.37 |
  | 0.20 | 0.97 | 0.88 | 0.53 |

  These are for a linear dose-response; a threshold shape gives higher slope power.
- **The shape is not identifiable at k = 10.** A threshold curve is told apart from a linear one at most 26% of the
  time. The shape is reported descriptively, against a prediction frozen before the M3 searches run.
- **The frozen prediction.** From the ladder pools, the selection-only gain at each ε is computed by the
  selection-channel analysis of A3.4(3). It is written into STATUS before the M3 searches start.
- **Headline figure.** It plots the confirmed advantage against leaked bits: Δι̂ for L2, L3, L4 and the three doses,
  with the T1 order marked.
- **If no level is eligible as ℓ\*,** the doses are not run (A2.5). That saves $339.22.
- **The usefulness sub-study is unchanged:** 20% randomised enforcement, reported separately (A2.4).

### A3.4 The selection-protocol study (new)
**(1) What prior adaptive evaluations do.** Each entry was checked on 2026-10-28 in the full arXiv text, with every quote
confirmed by string search.

| paper | attack choice uses the evaluating monitor's signals? | evaluated on fresh executions? |
|---|---|---|
| Terekhov et al., arXiv:2510.09462 | Yes. The injection is built offline from "the monitor's system prompt, and exemplars of the monitor's feedback gathered from responses to the first ten side-task solutions" (§3.4), per target monitor | Fresh generations; no task split is described |
| MiniLab, arXiv:2610.24052 | Yes. Human attacks are edited "based on the monitor's scores and explanations", targeting suspicion ≤ 4/10 (§4.3). The feedback planner optimises against Luna, which is also its headline monitor. The **no-feedback** planner's prompt includes worked examples "including main task definitions, plans, and monitor feedback, and four caught examples" (App. G) | Fresh environments on the same task combinations; held-out main tasks only relative to the worked examples |
| SLEIGHT-Bench, arXiv:2605.16626 | Yes. About "10 iterations against the monitor" per transcript (§3.2); which monitor is not stated | No. The same fixed, hand-edited transcripts are scored, "at the cost of fabricated tool outputs" (§3.2) |
| Lucassen & Kaufman, arXiv:2605.26047 | No offline selection. The feedback arm uses the evaluating monitor's reasoning inside the episode. Their attack-selection analysis predicts the monitor "by drawing an independent sample from the trusted monitor" (App. G), and the main no-feedback bar "uses IID attack scores, assuming the attack policy does not adapt at all" | No split described |
| Kutasov et al., arXiv:2511.02997 | No score-tuned selection. Strategies are hand-coded ("hard coding clever red team strategies", App. E). Monitor simulation by the untrusted model recreating the process (§4) is a proxy | No split described |

**The finding, worded for the paper.**
- Three of the five select or optimise attacks with signals from the monitor that measures them.
- One (MiniLab) carries monitor feedback into its no-feedback condition through prompt examples.
- One (SLEIGHT-Bench) evaluates on the artifacts it optimised.

Each is legitimate under its own threat model. The issue arises only when conditions meant to differ in monitor
information are compared, or when numbers are reported on the selection artifacts. The paper says this, and claims
nothing about those papers' conclusions.

**(2) The experiment.**
- **Both selections are confirmed.** At L1, L2, M2 and the three M3 doses, and on the pilot and the five L1-on-W
  searches, each search's information-consistent and shared selections are both confirmed on that search's block,
  whenever they differ.
- **Estimands:**
  - **Selection leak:** B_sel(c) = U_shared(c) − U_ic(c), and its effect on each contrast,
    A_shared(c) − A_ic(c). The two selections come from the same search, so σ_b cancels.
  - **Winner's curse:** B_wc(c), the selected candidate's screening rate minus its confirmed rate, for every arm, at no
    cost.
- **The three-outcome rule applies.** B_sel at L1 is the primary estimand of this study. It matches the patterns above:
  an attacker without feedback whose attack is chosen with the monitor.

**(3) The selection-channel study (screening data only, no new episodes).** In every pool, for each channel c, the
selector is the cross-fitted predictor of A3.2.
- It picks the argmax on e and is scored on e′, symmetrically.
- The gain G_c is measured against a random pick from the same pool, within rounds (N = 4) and over the whole pool.
- It tests whether selection gain is ordered like Δι̂_c (H-S, pre-registered), and gives T2's certificates.

**(4) The corrected protocol, proposed as a contribution.**
- **R1, information consistency.** A condition's selector, filters and prompt examples see only that condition's
  channel.
- **R2, fresh confirmation.** Report fresh executions on held-out instances, never the artifacts used to select.
- **R3, leakage accounting.** Report monitor queries per condition and the bits each channel leaked (Δι̂ and T2's
  certificate).
- **R4, paired comparison.** Compare conditions on shared confirmation blocks.

The paper measures what departing from R1 and R2 costs in this setting: B_sel and B_wc.

### A3.5 Agent model (owner's instruction of 2026-10-28; replaces "agent model confirmed" in A1.7)
- **Candidate:** `openai/gpt-6.1-sol`, replacing `gpt-4o-2024-08-06`. It is a current model, cheaper per token than
  gpt-4o ($2/$10 per M against $2.50/$10), and it leaves D4's transfer monitor (`gpt-6.1-terra`) a different model.
  - If the pilot fails on cost alone, the fallback is `openai/gpt-6.1-terra`, and D4 moves to sol.
  - If it fails on behaviour, the study stays on gpt-4o.
- **Pilot, before Q1:** 4 episodes, 2 clean and 2 L0, at an estimated $0.45. It passes if:
  - at least 3 of 4 episodes are valid under the completion rule;
  - the coalition follows the attack instruction in both L0 episodes, with no refusal;
  - the measured all-in cost is ≤ $0.15 per episode, reasoning tokens included;
  - the provider accepts temperature 0 and a seed, or the paper states that it does not.
- **Consequences:**
  - The 500 + 500 clean runs set the new model's clean P-ext floor.
  - Phases 1–8 become background, not baselines.
  - The cost unit is re-measured from the pilot before Stage 1's runs.

### A3.6 Councils
Checkpoint council 1b, on this revised design, is the owner's addition of 2026-10-28. It is capped at $40, and its
findings are handled as in (2): unanimous findings are applied, and split findings go to the owner. The other checkpoints
are unchanged.

### A3.7 Budget after (3) (`scripts/paper/cost_paper.py`, agents gpt-4o as the upper case)
**Stage 1: $480.04 against the $600 cap.**

| provider | for | estimate |
|---|---|---|
| OpenAI | +20% | $298.10 |
| Anthropic | +20% | $30.96 |
| Councils | checkpoint 1 spent $27.78; 1b and kill check 1 at their $40 caps | $107.78 |
| RunPod | CPU | $43.20 |

Added since (2):

| item | cost |
|---|---|
| S2 | $47.11 |
| Selections confirmed twice | $15.69 |
| Agent pilot | $0.45 |
| Council 1b | $40 |

**Stage 2: $1,470.52; with D4 $1,847.02; with D4 and D2 $1,959.12.**

| item | cost |
|---|---|
| M3 doses | $282.68, replacing $94.23 |
| Selections confirmed twice (upper bound) | $134.52 |
| Embeddings | $1 |

- **D4 rises to $376.50,** because it rescores more confirmations.
- **The k-adaptation add-ons** are now $126.53 (k = 15) or $253.05 (k = 20).
- **If ℓ\* = L2,** add $26.90.
- **With gpt-6.1-sol agents** at equal tokens: Stage 1 $441.48, Stage 2 with D4 $1,695.64.

**Paper total**, Stage 1 + Stage 2 with D4: **$2,327.06** (gpt-4o upper case), against about $4,300 available. No GPU.

## Amendment (4), 2026-10-28: findings of checkpoint council 1b, before any run

**The council.** It reviewed Amendment (3).
- **Members and format:** Fable and Astra for, Opus and Sol against; three rounds, live search.
- **Packet:** pulled from the pod on 2026-10-28.
- **Spend:** $25.47 of the $40 cap.
- **Record:** kept with the owner, outside the repository.
- **Verdicts:** all four were **GO WITH FIXES**.

| score (out of 10) | Fable | Astra | Opus | Sol |
|---|---|---|---|---|
| revised contribution as a whole | 5 | 5 | 5 | 5 |
| information-theoretic framing | 3 | 2 | 3 | 3 |
| selection-protocol finding | 4 | 5 | 3 | 5 |
| corrected protocol R1–R4 | 3 | 3 | 3 | 4 |

**Their joint reading.** The strongest contribution is the matched-budget ladder with two selections per search, each
confirmed on fresh executions. The theory layer as written of (3) took credibility away rather than adding it.

The closest prior work they named:
- Keenan, Leckie, Erfani (arXiv:2609.36490), on verdict feedback and verdict corruption;
- Lucassen & Kaufman (arXiv:2605.26047, App. G), on monitor-sampled attack selection;
- MiniLab's held-out-monitor rescoring;
- Carlini et al. (arXiv:1902.06705), on evaluation hygiene.

Every unanimous finding is applied below. The split findings are S7 and S8 (A4.6). Where (4) conflicts with (3), (4)
governs.

### A4.1 The theory, rescoped (unanimous)
- **T1 becomes an emulation lemma.** It holds when the attacker class is closed under causal garbling with no extra
  resource cost: the garbling map, the clean pool and the preprocessing fit within the same budget.
  - It is motivation, not a contribution.
  - H-B is renamed the **order-consistency check**. The ladder trend contrast and the dose slope test aggregate trends.
    They neither test T1 nor establish each adjacent order.
- **T2 is kept only as a conditional lemma** for independent, identically distributed candidates.
  - Its empirical certificates are withdrawn. Candidates from one proposer call are dependent. Sol's counterexample
    shows selection can gain 0.25 even when each candidate's own record carries zero information about it: records
    F₁ = q₂ and F₂ = q₁.
  - T2 is used in no result.
- **"Leakage in bits" is renamed predictive log-loss improvement (bits).** It is a cross-fitted, usable-information
  quantity (Xu et al. 2020), not Shannon information. A difference of two estimated lower bounds bounds nothing.
  - **The reference pool is frozen:** the Stage 2 L1–L4 ladder screening pools only, weighted equally per search. The
    mitigation pools exist only for some ℓ\*, so they are excluded.
  - **The predictor families are nested:** each level's family contains the one below.
  - **Reporting:** bootstrap intervals over searches, as a descriptive diagnostic.
  - **Headline figures:** they plot advantage against level and dose. The bits annotate them and are not an axis of a
    claim.
- **The capacity statements are corrected.**
  - The episode-level bound I_M3(ε) ≤ (1 − ε) I_ℓ\* is **withdrawn**. With redundant claims replaced independently, an
    episode keeps up to 1 − ε^J of a bit.
  - The word "exact" is removed.
  - The capacity table of A3.2 is relabelled an illustration for a single verdict record. r0 is a per-claim clean flag
    rate, which a 5% episode threshold does not fix; 0.01 and 0.05 are shown as illustrations only.
  - M4 carries zero **additional** monitor information.
  - M3(1) ≡ L1 holds only if the channel contract (A4.3) makes claim counts, timing and metadata identical.
- **R3 is corrected:** report monitor queries per condition and each channel's predictive log-loss improvement, with no
  certified bits. R1–R4 are presented as an operational checklist, not as new principles.

### A4.2 The selection-protocol table, rewritten as an affordance audit (unanimous; replaces A3.4(1))
| paper | how attacks are built or chosen, and with which monitor signal | evaluation |
|---|---|---|
| Terekhov et al., arXiv:2510.09462 | Threat model: an attacker "that knows the protocol and the monitor model". The injection is built offline from the target monitor's prompt and feedback on the first ten side-task solutions (§3.4). Their cross-monitor test finds that the monitor's output samples "play a minor role" for most models (§4.2) | Fresh generations; no task split is described |
| MiniLab, arXiv:2610.24052 | Human attacks are edited on the monitor's scores and explanations, to a suspicion of 4/10 or lower (§4.3). The feedback planner optimises against Luna. The worked examples containing monitor feedback are given to **both** planner conditions, so they do not contaminate the comparison (App. G) | Plans run 5 times in fresh environments, with no results returned to the planner; held-out Sol rescoring |
| SLEIGHT-Bench, arXiv:2605.16626 | A benchmark of hand-built transcripts. About 10 iterations "against the monitor" per transcript; that monitor is not named (§3.2) | Fixed transcripts by design, scored by many monitors |
| Lucassen & Kaufman, arXiv:2605.26047 | No offline selection. The feedback arm gives the evaluating monitor's reasoning within the episode, by design. App. G simulates within-trajectory attack selection with "an independent sample from the trusted monitor". The main no-feedback bar is non-adaptive | No split is described |
| Kutasov et al., arXiv:2511.02997 | Hand-coded strategies; monitor simulation by the untrusted model, a proxy (§4, App. E) | No split is described |

**The finding as worded now.** Monitor-guided attack construction is common, and legitimate where the threat model
grants it.
- Three of these papers document it. Two make the identity of the target monitor explicit.
- Our experiment measures the selector-information effect in our own setting only. It says nothing about these papers'
  conclusions.
- The count "three of the five select with the monitor that measures them" is withdrawn.

### A4.3 Design fixes (unanimous)
- **A fresh L1 endpoint and fresh blocks.** A new set of confirmation blocks is reserved for the mitigation phase. On
  those blocks run:
  - the fresh ℓ\* comparator;
  - M2;
  - the M3 doses;
  - view T;
  - **10 fresh L1 searches**, the x = 0 endpoint, which replaces the ladder's L1, whose blocks were used to choose ℓ\*.

  The seed manifest is written in week 1. Cost: +$113.07.
- **An executable channel contract.** The arm drivers define, per arm, as code frozen at Q1's byte-level test:
  - every field shown;
  - the metadata: claim counts, turn numbers, timing;
  - M2's visibility schedule;
  - M3's replacement rule (S7);
  - the selector.
- **Selectors:**
  - **L1:** count of successful screening episodes, then higher mean coalition gain, then earlier round, then lower
    candidate index.
  - **L2:** count of episodes that are successful and not flagged on the verdict, then the L1 tie-breaks, with no score.
  - **L3 and L4:** as in §3.3.
  - **M2 and M3:** exactly the records their proposer held at the end of the search.
  - When the two selectors pick the same candidate, that search contributes 0 to B_sel and is counted.
- **The §3.3 selector is now called the "monitor-aware selector",** not a ceiling: it is a heuristic, and not
  guaranteed to be the best choice.
- **B_sel power** (`scripts/paper/power_bsel.py`, 4,000 simulated studies, U = 0.20, m = 20). The figures are the
  probability of detecting B_sel = 0.10, over selector-disagreement rates d of 0.3–1.0 and candidate-difference SD of
  0.05–0.20:

  | searches | P(detect B_sel = 0.10) | P(detect B_sel = 0.15) | P("no bias above 10 points") when B_sel = 0 |
  |---|---|---|---|
  | k = 10 | 0.12–0.52 | — | 0.22–0.92 |
  | k = 20 | 0.51–0.93 | 0.75–1.00 | — |

  The primary B_sel estimand is therefore **pooled over L1 and L2** (k = 20 searches; more under the k-adaptation).
  Each level is reported descriptively. "σ_b cancels" is withdrawn: pairing removes search-level variance, but the
  difference between the two candidates remains.

### A4.4 Budget fixes (unanimous)
- **The $90 held back for elicitation repair** (A1.8) is restored. It was missing from A3.7.
- **The agent pilot's cost gate is ≤ $0.123 per episode,** all-in with reasoning tokens. That keeps Stage 1 plus the
  $90 within $600.
- **Stage 1 with gpt-4o agents:** $480.04 + $90 held back = **$570.04** against the $600 cap.
- **Stage 2:** +$113.07 for the fresh L1 endpoint, so $1,583.60.
  - With D4, re-costed to $391.50: $1,975.10.
  - With D4 and D2: $2,087.20.
  - Paper total, Stage 1 + Stage 2 with D4: $2,455.13 (gpt-4o agents).
  - With Terra agents at equal tokens: Stage 1 $340.43, and Stage 2 with D4 $1,384.16.
- **D4 never moves to a model without log-probabilities.** A3.5's "D4 moves to sol" is withdrawn.

### A4.5 The agent model (unanimous that A3.5 cannot run as written)
OpenAI's documentation, checked on 2026-10-28, says:
- GPT-6.1 Sol supports reasoning effort low to max only;
- with reasoning on, `temperature`, `top_p` and log-probabilities must be removed;
- Sol's tool calling requires the Responses API;
- GPT-6.1 Terra supports effort `none`.

A3.5 is therefore withdrawn. No agent pilot runs until the owner decides S8.

### A4.6 Split findings, for the owner
- **S7, the M3 replacement rule.** At L4, a replaced reason names the wrong ticket or agent, so M3 acts closer to erasure
  than noise. Fable and Opus raised this; Astra and Sol asked only that the channel contract be specified. Options:
  - (a) apply M3 to the verdict and score only, with reasons withheld. If ℓ\* = L4, the dose-response is then anchored
    to a fresh L3 comparator (+$113.07, only in that case);
  - (b) replace with clean records from the same instance (about +$194 for clean runs on the search instances). This
    only partly fixes it, because a claim's ticket can still differ;
  - (c) keep the rule as it is, and report M3 at L4 as erasure-like noise.
- **S8, the agent model.**
  - (a) Keep `gpt-4o-2024-08-06`. Opus favours this; Fable allows it.
  - (b) GPT-6.1 Terra at effort `none`. Fable allows it if `none` is confirmed, and the documentation confirms it. The
    pilot then checks that temperature 0 and a seed are accepted, and checks the cost gate. D4's transfer monitor,
    currently Terra, would then be the agent's own model, so D4's monitor is re-decided at kill check 1.
  - (c) GPT-6.1 Sol with stochastic agents and the Responses API. Astra and Sol favour this; determinism is not needed
    for valid inference. Reasoning tokens make the $0.123 gate unlikely to hold.
