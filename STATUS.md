# STATUS  (updated by whichever session finishes a task; read by every session first)

## Where things are
repo: control-loop, main, last commit 63a9ed5 2026-10-20 18:25 +0530, pushed to github.com/HemantBK/control-loop (clean tree)
old clone: ../orbit, branch adaptive-redteam at 019124e (+ uncommitted Phase 2 work, see below); pushed as phase1-orbit-clone? no — pushed as branch `adaptive-redteam` on remote `publish` (HemantBK/control-loop)
.env: ../.env (outside both repos); every paid command passes `--env-file ../.env`
Phase 2 code and results live ONLY in ../orbit/adaptive_control and ../orbit/results/v2; nothing of Phase 2 is in control-loop yet

## Phases
1 orbit_redteam        done, audited x4, written up (README, PLAN §1-15, FINDINGS, audits/)   results/{baselines,prop_*,static_only,...} (v1, seed-733 early block + 42/1049); results/v2/{early,late,claimslast}/...
2 claim_monitor        cells done (114 episodes, $16.49); migration to control-loop, write-up and audit pending   ../orbit/results/v2/{early,late}/{baselines,prop_sonnet55}/733_claim_{time_monitor,rule_monitor}, early-only 733_claim_time_monitor_4o, early/ctm_check{,2}
3 (was protocol)       deferred by Phase 2 result; see Decisions
4 controlarena         not started
5-8                    not started (5 ResearchArena, 6 allocation-level defense, 7 DGM self-modifying agent, 8 non-agentic monitor)

## Results folders (control-loop/results)
v1 layout: baselines, baselines_meta, prop_sonnet55, prop_qwen3, static_only, repro, g0_gpt4o, g0_gpt41mini, noise_gpt4o_t6, noise_gpt4o_t8, summary
v2 layout: v2/<early|late>/{baselines, baselines_meta, prop_sonnet55, prop_qwen3, static_only, greedy, transfer}; v2/early/prop_sonnet55_uninformed; v2/late/greedy_dev0; v2/claimslast/{baselines, baselines_meta, prop_sonnet55, transfer_headline}
kept, enter no table: _superseded_733_single_draw, _damaged, _noise_gpt4o_t6_maxturns10, _noise_gpt4o_t8_maxturns10, 733_llm_monitor_fixed.attempt2.out

## Running now
none

## Uncommitted
control-loop: STATUS.md (this file)
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

## Open questions for Hemant
- Migrate Phase 2 into control-loop now (claim_* presets into control_loop/adapters/orbit/jira_adaptive.py, claim_*.py scripts, results/v2 claim dirs, PLAN §16, FINDINGS entries), or commit it first on ../orbit adaptive-redteam as a record?
- Should the orbit clone's branch be pushed under the name phase1-orbit-clone as the template assumes, or is publish/adaptive-redteam enough?
- CALL_PREP prerequisites before the allocation-level build (two-independent-greedy control on 733 late, score-only AUROC pass of the judge, about $5): run them, or go straight to Phase 6?
- claim_time_monitor_4o was run in the early ordering only; leave it, or finish late before the write-up?
- Phase 2 write-up: new README section plus a fresh-session audit (HANDOFF §5.7), or fold into the Phase 6 write-up?
