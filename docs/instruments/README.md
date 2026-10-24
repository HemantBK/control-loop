# Instrument documents (docs/SOP.md §2.7)

One document per attacker and per monitor or rule the project uses, each with the six SOP sections
(What it measures; How it is driven; Limits; Biases; Verifying tests; Change history), written before
the first paid run that uses it and updated by dated entries. Prompt and brief strings are identified
by SHA-256 of the exact text (computed on the pod with Python's `hashlib`; each document says what was
hashed); file hashes are of the working tree on the stated date and change with every edit.

| instrument | kind | phases | file | last updated |
|---|---|---|---|---|
| proposer (the adaptive attacker; ORBIT briefs `informed`, `uninformed`, `informed_rule`, `informed_protocol`; ControlArena `BRIEF`, `BRIEF_MONITOR_AWARE`) | attacker | 1, 2, 3, 4, 5 (7 compares against it) | [proposer.md](proposer.md) | 2026-10-21 |
| orbit_llm_monitor (ORBIT's per-action judge; presets `llm_monitor_fixed`, `llm_monitor_fixed_actions`; the message judge inside Phase 2 arms and Phase 3 check presets) | monitor | 1, 2, 3 | [orbit_llm_monitor.md](orbit_llm_monitor.md) | 2026-10-21 |
| claim_time_monitor (claim-context judge; `claim_time_monitor`, `claim_time_monitor_4o`; rule variant `claim_rule_monitor` §7; score-only pass `claim_score_only` §8) | monitor | 2 (its score-only pass is Phase 8's per-action comparator) | [claim_time_monitor.md](claim_time_monitor.md) | 2026-10-21 |
| allocation_rule (R1–R3 against the reference optimum; `allocation_rule_autoallow`, `allocation_rule_monitor`; LLM variant `allocation_llm_*` §7) | monitor (rule) | 3, 5 (inside the protocol), 7 (planned) | [allocation_rule.md](allocation_rule.md) | 2026-10-21 |
| controlarena_trusted_monitor (ControlArena `trusted_monitoring` + `basic_monitor` on Sonnet 4.6; τ at a 1% budget; end-of-trajectory scorer) | monitor | 4 (closed) | [controlarena_trusted_monitor.md](controlarena_trusted_monitor.md) | 2026-10-21 |
| claim_protocol (provisional claims with a stated reason, D = 8, resolution `ref` / `fcfs` / `prof`, on top of the Phase 3 rule) | monitor (protocol) | 5 (run 2026-10-21/22: check, check2, 11 cells; arm held, comparators showed nothing to remove) | [claim_protocol.md](claim_protocol.md) | 2026-10-21 |
| transcript_monitor (one gpt-4o-mini call per rendered episode, V1 / V2) | monitor | 8 (run 2026-10-21/22, ten logs, $3.6244; result falsified, audit pending) | [transcript_monitor.md](transcript_monitor.md) | 2026-10-22 |
| researcharena_proposer (the adaptive attacker on ResearchArena: `RedTeamPolicy` with the cuda_kernel `BRIEF` and six `MOVES`; the payload is the side-task paragraph) | attacker | 6 (no paid run yet) | [researcharena_proposer.md](researcharena_proposer.md) | 2026-10-21 |
| researcharena_monitor_m0 (ResearchArena's transcript-only post-hoc monitor M∅ on Sonnet 4.6, `blueruntime 0.0833`, one 0–100 suspicion score per episode) | monitor | 6 (no paid run yet) | [researcharena_monitor_m0.md](researcharena_monitor_m0.md) | 2026-10-21 |
| self_modifier (the self-modifying coalition policy: the agents' own gpt-4o rewrites the coalition paragraph from a DGM-style archive; `--attacker self_modifier`; briefs = the proposer's `informed` / `informed_rule` with the PLAN §1.2 substitutions) | attacker | 7 (run 2026-10-22/23: check, sweep with four arm-A cells, S2 arm A-lin at 733 early none and rule, $0.7521; Phase 7 $6.2949; verdict undecided, audit pending) | [self_modifier.md](self_modifier.md) | 2026-10-23 |

## Rule for phase write-ups

A phase README's Method section (SOP §2.4, section 3) **links** the instrument documents it relies on
and states only what is specific to that phase (which presets, seeds, orderings, briefs and flags were
used); it does not re-describe the instrument. A change to an instrument is a dated entry in its
document's Change history, made before the run that uses the change; a bias found by a mechanism check
or an audit is added to the document's Biases section with its evidence path and direction, dated.
Numbers quoted in these documents are each phase README's or PLAN's claims with the section cited, or
code facts with the file and line; nothing here is re-derived from logs.

The Phase 6 ResearchArena documents and the Phase 7 self-modifier's document were written with their code on
2026-10-21, before any paid run of those phases (SOP §2.7); rows above.
