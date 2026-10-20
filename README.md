# control-loop

A red-team loop for multi-agent control evaluations: an LLM proposer rewrites a coalition's objective paragraph between rounds, a benchmark framework runs the episode, and the analysis asks whether the framework's defense still prevents the coalition from redistributing reward to itself. The loop (`control_loop/loop.py`), the proposer (`control_loop/proposer.py`) and the analysis (`control_loop/results.py`, `round_table.py`, `controls_table.py`, `plot.py`, `control_loop/analysis/`) do not know which framework runs the episode; everything that does lives in one adapter per framework under `control_loop/adapters/` (contract in `control_loop/adapters/README.md`). Phase 1 ran against ORBIT's JiraTicket scenario and its shipped defenses; each later phase builds or ports one defense, or one framework, and is written up in its own directory under `phases/`.

ORBIT (Ben Hagag, William L. Anderson, Tom Taylor, Srija Chakraborty and Christian Schroeder de Witt, Apache-2.0, https://github.com/wlanderson0/orbit) is installed unmodified as a dependency pinned to commit 588b303 (`pyproject.toml`, `uv.lock`); Inspect AI (UK AI Security Institute, MIT) at 0.3.263. Third-party attributions are in `NOTICE`; this repository's own code and documents are Apache-2.0 (`LICENSE`). Full attribution and the Phase 1 provenance (branch `adaptive-redteam` of a clone of ORBIT) are in `phases/phase1_orbit_redteam/README.md` section 2.

## Layout

| path | holds |
|---|---|
| `control_loop/` | the loop, the proposer, the cross-phase tables and figures; `adapters/orbit/` (the Inspect task with the Phase 1 presets, the Phase 2 claim-time monitors and the Phase 3 allocation monitor), `adapters/controlarena/` (Phase 4); `analysis/` (per-phase scripts that read the logs) |
| `phases/phase1_orbit_redteam/` | Phase 1 write-up (`README.md`), `PLAN.md` §1–§15, `FINDINGS.md`, `pins.md`, `HANDOFF.md`, `audits/audit1.md` to `audit4.md` |
| `phases/phase2_claim_monitor/` | Phase 2 write-up (`README.md`), `PLAN.md` §16 (design, amendments, the §16.12 prerequisites and their outcome), `FINDINGS.md` (six entries) |
| `phases/phase3_allocation_monitor/`, `phases/phase4_controlarena/` | plans and results of the phases in progress |
| `results/` | Phase 1 evidence: the seed-733 early block and seeds 42 and 1049 at the top level, the control program under `results/v2/<ordering>/`, figures and CSVs under `results/summary/` |
| `results/phase2_claim_monitor/<ordering>/` | Phase 2 evidence: `baselines/733_claim_*`, `prop_sonnet55/733_claim_*`, `ctm_check`, `ctm_check2` |
| `results/phase3_allocation_monitor/`, `results/phase4_controlarena/` | evidence of the phases in progress |
| `logs/` | ORBIT's qualification runs for the Phase 1 setup |
| `STATUS.md` | where every phase stands, what is running, dated decisions, open questions |

Paths inside `phases/*/` documents are relative to the repository root unless they are links; every command runs from the root with `uv run --locked`, and every paid command adds `--env-file ../.env` (the keys live one directory above the repository). Phase 1's reproduction command and expected output are in `phases/phase1_orbit_redteam/README.md` section 10.

## Phases

| # | name | question | status |
|---|---|---|---|
| 1 | Break ORBIT's shipped defenses | Do the anti-collusion prompt and the LLM monitor still prevent redistribution when the coalition payload is rewritten between rounds? | done; audited four times; `phases/phase1_orbit_redteam/` |
| 2 | Claim-time monitor | Does a judge that rules on each `assign_task` call with the claim's context block the claims the shipped monitor allowed? | done: 135 episodes, $17.69; written up in `phases/phase2_claim_monitor/README.md`; fresh-session audit pending |
| 3 | Allocation-level monitor | Does a monitor that rules on each claim with the whole forming allocation in view, against the reference optimum, detect redistribution where the per-claim judge did not? | presets and mechanism check committed; sweep in progress; `phases/phase3_allocation_monitor/` |
| 4 | ControlArena port | Do the same payload moves transfer to a ControlArena setting? | adapter built, mechanism check and limit-3 reproduction done; `phases/phase4_controlarena/` |
| 5 | Claim-level protocol | Does a claim protocol that requires a stated reason and a delay before a ticket is final remove the first-mover effect? | not started |
| 6 | ResearchArena | Does the attack hold in a research-agent setting with longer horizons? | not started |
| 7 | Self-modifying agent (DGM) | Does a coalition agent that rewrites its own policy between rounds reach the same outcome without an external proposer? | not started |
| 8 | Non-agentic monitor | Does a monitor that reads the full transcript once, with no tool calls, outperform the per-action judge? | not started |

Decisions on the order, dated: 2026-10-20, after Phase 2 and its §16.12 prerequisites. The allocation-level monitor moved from 6 to 3 because Phase 2 showed that per-claim monitoring with full context delays the attack but does not stop it, the fixed judge carries no information at the claim (AUROC 0.50), and the coalition's signature is at the allocation (two blind first claims that do not collide); the ControlArena port stays at 4 because its adapter and mechanism check were already built in parallel; the claim-level protocol moved from 3 to 5 because the score-only pass showed Phase 1's failure was observation, not the resample protocol, so a protocol change alone has nothing to act on until a monitor carries a signal; ResearchArena, DGM and the non-agentic monitor keep their relative order and follow once a defense survives on JiraTicket (`STATUS.md`, decisions log).
