# Response to the Phase 4 audits

2026-10-21. Answers every finding of `audit_codex.md` (X1) and `audit_claude.md` (C1–C6), taking the union of both. The two audits do not overlap on any finding and do not disagree on any number: Codex reviewed source only, and Claude re-derived every reported number, label and verdict from the raw logs and found all of them matching. `audit_codex.md` is the cross-family check (static code review); `audit_claude.md` is the numerical check (raw-log re-derivation). Codex could not decode the Zstandard-compressed `.eval` logs in its sandbox, and the owner chose to keep that sandbox as it is. The manager's direction of 2026-10-21 governed the wording of C1–C6 and the audit-status lines; it changes no verdict. No API calls and no paid runs were made, and `../.env` was not opened. Nothing was committed or staged.

Status: **fixed** = the text, number or code is corrected; **disclosed** = the issue stays and is stated in Limits, Known issues or beside the number; **not accepted** = the recommendation was not followed, with the reason. Where part of a finding is fixed and part disclosed, it is counted under its main status and the disclosed part is named in the row.

Counts: **5 fixed, 2 disclosed, 0 not accepted.** One fixed finding carries a disclosed remainder (C1: `sweep.PRIOR_PHASE4`, `qwen3_733/spend.json` and `PLAN.md` §12.12 keep the rounded $2.9035). One fixed finding also leaves a stale PLAN sentence, disclosed (C2: `PLAN.md` §12.1 "The real logs show 56 only"). The suggested remedies for C5 (a PLAN hash in `state.json`, or an owner commit) and C6 (a sidecar log of the proposer's ModelEvents) were not implemented here, because code and commits are outside this response's paths (G3); they are disclosed, not rejected.

Paths: README = `phases/phase4_controlarena/README.md`; RESULTS = `phases/phase4_controlarena/RESULTS.md` ("Corrections" is its appended entry "Corrections after the two Phase 4 audits (2026-10-21)"; earlier entries not edited); pins = `phases/phase4_controlarena/pins.md`; root = the root `README.md`, Phase 4 row; STATUS = `STATUS.md`.

| id | severity | status | what was done | where | merged with |
|---|---|---|---|---|---|
| X1 | major | fixed | Fixed before this response (separate task, 2026-10-21): `sweep.check_secondary` recomputes the primary verdict from the primary cell's `.eval` logs with `recompute` (the fixed metric), never reads `summary.json`, and fails closed on a missing, unreadable or incomplete `state.json` or any recompute error (`control_loop/adapters/controlarena/sweep.py:554-584`). Tests: 3 in `tests/test_controlarena_metric_fix.py` (stale "matched" summary against a recomputed "falsified"; missing or unreadable primary; spend stop after a recomputed match), and `tests/test_controlarena_sweep.py::test_secondary_needs_matched_primary` rewritten for the recompute gate. This response changed no code; the stale text the fix left is C3 | `sweep.py`; tests; README §10 | C3 |
| C1 | minor | fixed (`PRIOR_PHASE4` disclosed) | The exact Phase 4 total from the logs, $5.9747, is carried everywhere this response may write, with "the earlier $5.9739 rounded the 2026-10-20 part" ($0.50 + $0.68 for $0.4996 + $0.6812; exact prior $2.9042, not $2.9035; difference $0.0008). RESULTS' "5.9739" corrected by the appended entry; STATUS's two $5.9739 lines get dated bracket corrections. `sweep.PRIOR_PHASE4`, `qwen3_733/spend.json` and `PLAN.md` §12.12 (line 823) keep the rounded value (code, run files and PLAN outside this response's paths); no gate is affected (stop $16) | README §5, §11; pins (Dates run and spend); RESULTS Corrections; STATUS | |
| C2 | minor | fixed (PLAN §12.1 sentence disclosed) | The judges' format retries reported: over all 9 cell-P logs the 133 judge requests sent seed 56 ×128, 57 ×4 (r0a s3, r0b s7, r2 s3, r3 s5) and 58 ×1 (r0b s7, second retry), temperature 0.0, as `_llm_judge.py:89-92` (`seed + retry_idx`) implies. Replaces "56 (57 on one format retry)", which holds for the check stage only. `PLAN.md` §12.1's "The real logs show 56 only" (line 513), true of the selection logs when written, is named as not true of cell P; PLAN not edited | README §5 (seeds row), §8(a); pins (Seeds table); RESULTS Corrections | |
| C3 | minor | fixed | The statements that the secondary-cell gate reads `summary.json` corrected: RESULTS' metric-fix section ("Not changed, outside this task's paths") by the appended entry; the STATUS open question closed with a dated bracket. The test the auditor flagged was already rewritten with the X1 fix | RESULTS Corrections; STATUS (Open questions); README §10 already correct | X1 |
| C4 | minor | fixed | RESULTS' "Selection: Notes" ("source not traced") corrected by the appended entry: traced to `llm_score`'s default seed (`_llm_judge.py:89-92`), judge calls only (9 Opus 4.1 and 9 Qwen3 OpenRouter judge requests carried 56; no policy request carried a seed or temperature). STATUS's decisions line saying "(untraced)" gets a dated bracket | RESULTS Corrections; STATUS (Decisions log) | |
| C5 | minor | disclosed | R1 timing stated as what each source can show. Git: `PLAN.md`'s last commit `2fb1268` holds §1–§10 only, and the working-tree diff adds and removes nothing in them, so §1–§10 are unchanged since; git cannot date §11–§12. Local transcripts: §11 appended 2026-10-20 20:55:15Z (revised 21:01:00Z); §11.10's owner lines 05:13:04Z, 16 s before the first selection eval; §12 06:03:26Z; §12.12's first five owner lines 09:11:21Z, 12 s before `honest_run1`; afterwards only lines dated post-run and one in-place edit of the post-run "Presentation" line (10:14:29Z = mtime). Limits stated: transcripts are local, unsigned, editable and outside the repo; they date the writing, not the owner's decision; 16 s and 12 s mean written just before, not reviewed. The PLAN hash in `state.json` and the owner commit are not done here (code; G3) | README §7, §9 limit 8 | |
| C6 | minor | disclosed | The proposer's sent settings ("not sent" for seed and temperature, all 7 lines, `sent_source` `ModelEvent.call.request`) are recorded only in the adapter's own `proposer_log.jsonl`; no Inspect log exists for the proposer calls, so no independent record can check them. Agrees with the provider source (X8). The suggested sidecar ModelEvent log is not built here (code) | README §5 (seeds row), §10 (proposer item); pins (Seeds table) | |

## Codex's outstanding checks (not findings)

`audit_codex.md` lists checks it could not finish because it could not decode the logs. Where each now stands:

| Codex item | covered by | result |
|---|---|---|
| R1 (sections written before the paid calls) | `audit_claude.md` C5 | disclosed as C5 above |
| R2 (`R2_CHECK.md` against raw samples) | `audit_claude.md`, rows 1 | every value matches |
| R3 (policy 733 / 0, monitor T 0, judge 56 + retry, proposer) | `audit_claude.md`, rows 2 | match; C2 and C6 above |
| selection table, verdicts, cost, request settings | `audit_claude.md`, rows 3 | match |
| fixed sweep metric, τ, series, safety, S/F/A, validity, verdict | `audit_claude.md`, rows 4 | match |
| budget and cumulative costs | `audit_claude.md`, rows 5 | match; C1 above |
| MANAGER_RULES C1–C5 (path and secret scan, dependency integrity, full test review) | neither audit | not done; stated in README §10. Tests run by this response: 70 passed |

## Tests

`uv run --locked pytest -q tests/`: 70 passed, no API keys used. This response changed no code or test.

## G2

No fix changed a number re-derived from the logs or a pre-registered verdict. C1 moves the recorded total by $0.0008; C2–C6 correct or disclose text.
