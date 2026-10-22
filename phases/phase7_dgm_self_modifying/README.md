# Phase 7: a self-modifying coalition agent (DGM-style)

Phase 7 of the control-loop project (the phase table is in the root `README.md`). Paths are relative
to the repository root.

## Question

Does a coalition agent that rewrites its own policy between rounds reach the same outcome without an
external proposer? In Phases 1–5 an external red-team model (`anthropic/claude-sonnet-5-5`,
`control_loop/proposer.py`) rewrites the coalition's objective paragraph after seeing how the last round
scored. Here the paragraph, the system message tagged `orbit_collusion_prompt` that ORBIT places in
dev_0's and dev_1's prompts, is rewritten by the coalition's own model, `openai/gpt-4o`, given exactly
the observation the external proposer had (gain against the arm's clean mean, blocks by turn and
boundary, channel sends, turn of the first claim), with an archive of every past paragraph and the
Darwin Gödel Machine's parent-selection rule (Zhang, Hu, Lu, Lange, Clune, arXiv 2505.22954; the
mechanism, not the SWE-bench loop). No code is written or executed, no tool changes, no ORBIT source
touched. Arm A (self-modifier, gpt-4o, archive) is compared with arm B (today's loop, Sonnet 5.5, same
brief and observation) on the same cells: no defense at seeds 733, 512 and 101 (a three-seed replicate, owner's amendment §11) and the Phase 3
allocation rule at 733, early ordering. "Reaches the same outcome" is pre-registered as non-inferiority within one clean sd (18)
on Δcoal and within one round of five on P-ext and the redistribution class, under both validity rules.

## Status

**Not started; approved plan waits for Phase 6's reproduction step.** Pre-registration only:
`PLAN.md` §1–§11 (design, what "its own policy" is and is not, the self-modifier component and the
archive rule, the DGM facts verified from the paper and repository, predictions and falsifier, metrics,
budget, mechanism-check brief, sweep protocol, decisions for the owner, threats), written 2026-10-21
before any code or run. No code, no test, no model call and no log exists for this phase yet. The phase
starts only after Phase 6's reproduction step is confirmed (owner's instruction, 2026-10-21). Owner's
caps: cell $40, phase $60, stop at $48, the $15 single-cell stop-and-ask, `--max-samples 8`, one paid
stream; primary estimate $5.80 (upper $11.48) for 64 episodes (§11.1).
