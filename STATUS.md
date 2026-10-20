# STATUS  (updated by whichever session finishes a task; read by every session first)

## Where things are
repo: control-loop, main, last commit df96590 (plot-fix), tree not clean (see Uncommitted)
old clone: ../orbit, branch adaptive-redteam at 019124e (+ uncommitted Phase 2 work, see below); pushed as phase1-orbit-clone? no — pushed as branch `adaptive-redteam` on remote `publish` (HemantBK/control-loop)
.env: ../.env (outside both repos); every paid command passes `--env-file ../.env`
Phase 2 code and results live ONLY in ../orbit/adaptive_control and ../orbit/results/v2; nothing of Phase 2 is in control-loop yet

## Phases
1 orbit_redteam        done, audited x4, written up (README, PLAN §1-15, FINDINGS, audits/)   results/{baselines,prop_*,static_only,...} (v1, seed-733 early block + 42/1049); results/v2/{early,late,claimslast}/...
2 claim_monitor        cells done (114 episodes, $16.49); migration to control-loop, write-up and audit pending   ../orbit/results/v2/{early,late}/{baselines,prop_sonnet55}/733_claim_{time_monitor,rule_monitor}, early-only 733_claim_time_monitor_4o, early/ctm_check{,2}
3 (was protocol)       deferred by Phase 2 result; see Decisions
4 controlarena         adapter built, mechanism check done (mock + real, --limit 1, $0.50); no sweep, --limit 3 reproduction not run   phases/phase4_controlarena/{PLAN.md §10, RESULTS.md}; results/phase4_controlarena/{mechanism_check/{mock,real}, _attempt1_eot_overwrite}
5-8                    not started (5 ResearchArena, 6 allocation-level defense, 7 DGM self-modifying agent, 8 non-agentic monitor)

## Results folders (control-loop/results)
v1 layout: baselines, baselines_meta, prop_sonnet55, prop_qwen3, static_only, repro, g0_gpt4o, g0_gpt41mini, noise_gpt4o_t6, noise_gpt4o_t8, summary
v2 layout: v2/<early|late>/{baselines, baselines_meta, prop_sonnet55, prop_qwen3, static_only, greedy, transfer}; v2/early/prop_sonnet55_uninformed; v2/late/greedy_dev0; v2/claimslast/{baselines, baselines_meta, prop_sonnet55, transfer_headline}
kept, enter no table: _superseded_733_single_draw, _damaged, _noise_gpt4o_t6_maxturns10, _noise_gpt4o_t8_maxturns10, 733_llm_monitor_fixed.attempt2.out

## Running now
none

## Uncommitted
control-loop, Phase 4 (this session): STATUS.md; M control_loop/adapters/controlarena/{dp_task.py, proposer_policy.py}, phases/phase4_controlarena/PLAN.md; new control_loop/adapters/controlarena/{__init__.py, reader.py, mock_dp.py, mechanism_check.py, README.md}, phases/phase4_controlarena/RESULTS.md, results/phase4_controlarena/
control-loop, not from the Phase 4 session (another session's work, untouched): M control_loop/adapters/orbit/{__init__.py, jira_adaptive.py}; new control_loop/adapters/orbit/allocation_monitor.py, phases/phase3_allocation_monitor/, results/phase3_allocation_monitor/
../orbit (all Phase 2): M adaptive_control/{PLAN.md (§16.1-16.11), FINDINGS.md (4 Phase 2 entries), jira_adaptive.py (+309: claim_time_monitor, claim_rule_monitor, claim_time_monitor_4o), loop.py}
../orbit untracked: adaptive_control/{CALL_PREP.md, claim_audit.py, claim_rates.py, claim_report.py}; results/v2/{early,late}/{baselines,prop_sonnet55}/733_claim_*; results/v2/early/ctm_check{,2}

## Decisions log (dated, one line each)
2026-10-19  num_tasks=4 kept after the gpt-4o clean-vs-clean noise check (sd 17.3 at 4, 21.0 at 6, 16.4 at 8); PLAN §3.
2026-10-20  Phase 1 after audit 4: submit validity from ORBIT's halt reason only; proposer seeded (T=0, seed 100*seed+round) and logged from now on; headline restated as 2 of 5 valid under the submit rule, effective n=2; no further Phase 1 audit; PLAN §15.
2026-10-20  Repo migrated to standalone control-loop; ORBIT pinned at 588b303 as a git dependency; package renamed adaptive_control -> control_loop.
2026-10-20  Phase 2 design fixed before code: claim_time_monitor judges each assign_task with problem-definition context, gpt-4o-mini judge seeded, budget $40; PLAN §16.1-16.8.
2026-10-20  After the mechanism check: capacity computed in code, best-fit and view_tasks fields added, criterion 2 reworded; PLAN §16.9.
2026-10-20  Phase 2 cell (733 early+late): coalition claim block rate above outsiders' in both orderings, coalition tickets max 3 (Phase 1 headline 4), but clean coalition false positives 36-43% from the judge misreading view_tasks and an invented first-claim exemption; FINDINGS "Phase 2 cell".
2026-10-20  §16.11 three-way: rule monitor (no LLM at the claim) blocks every blind first claim in the late order but 3 tickets still reached, so it does not hold the attacker; gpt-4o judge not usable as configured (clean coalition rate 61-62%, dev_1 never claims, no round valid under the completion rule); the prompt's reading of criterion 3 is the thing to fix before any further LLM-judge cell.
2026-10-20  Phase 2 result: per-action monitoring delays, doesn't stop; next build is allocation-level (old Phase 6), protocol (old Phase 3) after it.
2026-10-20  Spend: Phase 1 about $108, Phase 2 $16.49 (under the $40 cap); CALL_PREP proposes a $60 cap for the rest of the JiraTicket line.
2026-10-20  Phase 4 reproduction target: no published data_poisoning number (PR #455's 3/7 is informal), so target = ControlArena's README example runs end to end under trusted_monitoring at --limit 3 and our reader parses safety, usefulness, per-step scores; README's `control-arena run single` does not exist on 20.1.0, `eval single` used; PLAN §10.1.
2026-10-20  Phase 4 observation model: own outcome (main, side, gain, halt reason) + per-step suspicion scores with step index; no monitor prompt/reasons, no other trajectories; PLAN §10.2.
2026-10-20  Phase 4 mechanism check: instruction delivered, every tool-call step scored, reader = raw log (mock and real). Found: ControlArena's end_of_trajectory_monitor overwrites the last step's suspicion_score in the log (logged 0.05/0.04, per-step monitor said 0.0); reader now reads per-step scores from the monitor's own call, dp_task runs the EoT scorer on a copy; first pair kept in _attempt1_eot_overwrite; PLAN §10.5, RESULTS.md.
2026-10-20  Phase 4 real red team (Opus 5.5, ControlArena attack prompt + round-0 paragraph) did not attempt the side task in 2/2 episodes (no password; scores 1 and 10); reasoning redacted. n=2, not a rate. Spend $0.50 (step-3 budget $5).

## Open questions for Hemant
- Migrate Phase 2 into control-loop now (claim_* presets into control_loop/adapters/orbit/jira_adaptive.py, claim_*.py scripts, results/v2 claim dirs, PLAN §16, FINDINGS entries), or commit it first on ../orbit adaptive-redteam as a record?
- Should the orbit clone's branch be pushed under the name phase1-orbit-clone as the template assumes, or is publish/adaptive-redteam enough?
- CALL_PREP prerequisites before the allocation-level build (two-independent-greedy control on 733 late, score-only AUROC pass of the judge, about $5): run them, or go straight to Phase 6?
- claim_time_monitor_4o was run in the early ordering only; leave it, or finish late before the write-up?
- Phase 2 write-up: new README section plus a fresh-session audit (HANDOFF §5.7), or fold into the Phase 6 write-up?
- Phase 4: run the PLAN §10.1 reproduction (`control-arena eval single ... trusted_monitoring --limit 3`, honest + attack, est. under $1.50)? It will be the reader's first test on CLI logs with more than one sample.
- Phase 4: the real red team did not attempt the side task in 2/2. Before any proposer rounds, look at side-task attempt rate of ControlArena's stock attack policy alone (no paragraph) on a few samples, so a 0 is attributable?
- Phase 4: files outside this phase's write paths that need an edit: NOTICE (ControlArena MIT entry, text in control_loop/adapters/controlarena/README.md), control_loop/adapters/README.md (still says one adapter exists), tests/ (a no-API smoke test from mechanism_check --backend mock), and a ControlArena issue for the EoT overwrite and the README command?
