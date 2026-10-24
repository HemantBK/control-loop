# SOP check — Phase 7: self-modifying coalition agent (docs/SOP.md §8)

Date: 2026-10-23. Checker: task phase7-writeup (Claude). **This checker also wrote `README.md`**, by the task's assignment;
`docs/SOP.md` §8 asks for "an agent other than the writer", so this check should be re-run by another agent before the
audit starts. SOP version: `docs/SOP.md` with the change-log entries of 2026-10-21. No model call, no paid run, no commit;
`check.py` and `sweep.py` were run only with `--dry-run`. Marks: **PASS**, **FAIL** (the SOP's "gap"), **N/A**.

Files read: `docs/SOP.md`; `phases/phase7_dgm_self_modifying/{PLAN.md, FINDINGS.md, pins.md, README.md, audits/build_check.md}`;
`results/phase7_dgm_self_modifying/{sweep_tables.md, sweep_summary.json, round_table_crosscheck.md, refusal_table.md,
sweep_driver.log, sweep_driver_s2.log, sweep_driver_s3.log, run.jsonl, check/733_allocation_rule_autoallow/CHECK.md}`;
`docs/instruments/{README.md, self_modifier.md}`; root `README.md`; `STATUS.md`; `git log`, `git diff` of the Phase 7 files.
Commands run on the pod: `python -m control_loop.status results/phase7_dgm_self_modifying`; `sweep.py --dry-run --s2 --s3`;
the Phase 7 tests with the two driver-starting tests deselected (32 passed, 2 deselected); `find … -name run.jsonl`; the
absolute-path grep of item 7.

**Re-run of the affected items, 2026-10-23 (after `audits/sop_check_independent.md`): 15 PASS, 0 FAIL, 0 N/A.** The
independent check found two gaps this check had passed (item 4: "25" parent selections and the "within-run sd" label; item
13: NI-R pooled over two seeds) and closed item 9 by fixing the two tests. Items 4, 7, 9, 10, 11, 13 and 14 below carry a
dated re-run note; the rest are unchanged. Checker for the re-run: the same writer (T7.5 was met by the independent check).

First run, same date: **14 PASS, 1 FAIL, 0 N/A** (after the fixes below). First pass: 12 PASS, 3 FAIL (items 4, 9, 10). Items 4 and 10
were write-up fixes, made and re-checked (task list, T7.1–T7.2). Item 9 needs code and stays open (T7.3); it touches no
number, verdict or pre-registration, so under §8 it may be listed and disclosed while the audit starts.

## Items

### 1. PLAN — **PASS**

- `PLAN.md` header "(written 2026-10-21, before any code or run)". Sections §1 Design, §2 the DGM (added), §3 predictions
  (§3.4) with the verdict rule and falsifier (§3.5), §4 Metrics, §5 Budget, §6 Mechanism check, §7 Sweep protocol, §8
  decisions (D1–D12, with the ambiguity trigger D9 and the per-cell stop D10), §9 threats, §10 Owner's approval, §11 the
  owner's amendment of 2026-10-21; then dated lines (2026-10-22 ×4, 2026-10-23 ×2).
- Approval before the first paid call: §10's line of 2026-10-21; the first paid log is
  `check/733_allocation_rule_autoallow/A0/2026-10-22T17-55-14-…eval`. §1–§11 are in commit `dffe520` (2026-10-22 13:34:22
  UTC). `git diff dffe520` on PLAN.md: one dated in-place note in §5 (build check, before the first paid call) and the
  appended dated lines; nothing above §11 changed after the first paid call.
- Notes (no gap): the header lacks the `# PLAN — Phase N:` prefix and the falsifier sits in §3.5 rather than its own §3, so
  the numbering differs from §2.2's template while every element is present; amendments are "dated lines", not `### Amendment`
  headings. PLAN §7.1 asks for a dated line before S2/S3 run; the owner's 2026-10-23 line exists, but its write time cannot be
  ordered against 05:43 UTC from the file (PLAN.md mtime 06:26 UTC is the later correction line).

### 2. FINDINGS — **PASS**

Entries for the build checks and mechanism check (2026-10-22; "Nothing below enters a table"), every sweep cell (2026-10-22,
log paths, UTC, spend), the verdict and ledger (2026-10-22), S2/S3 (2026-10-23, the same day as the runs) and the attribution
and totals (2026-10-23). The `sweep_table.py` fix is recorded in the verdict entry; the concurrency and state-file repair in
the S2/S3 entry. No earlier entry is now known to be wrong (the 2026-10-22 "None was run" and "$4.3925" were true at the time
and are superseded by the 2026-10-23 entries).

### 3. README sections and headline — **PASS**

`README.md` has sections 1–12 in the §2.4 order (12 = "none yet", audit pending). Headline (section 1): "**undecided** under
the allocation rule, **undecided** under the completion rule, combined **undecided**", in the §3.5 / §11.1 wording, with the
seed count (NI-P fails at 1 of 3 seeds; "not the same" needs 2 of 3), the per-seed denominators (A 5/5/5, B 5/5/3 valid) in
the table under it, and both validity rules. No causal word; post hoc readings are labelled.

### 4. Numbers in README sections 1, 4, 7 and 11 — **PASS** (re-run 2026-10-23, after T7.7; first run passed it wrongly)

- **Re-run 2026-10-23.** The token search had passed "25" because the value occurs in FINDINGS. Recomputed from the six
  `archive.jsonl`: 20 seeded selections (`dgm_sigmoid_children`, 5 per A cell) and 10 linear (S2). README §4 now says so;
  FINDINGS corrections entry of 2026-10-23. Recomputed from the four baselines' `.eval` logs: 13.44 / 15.67 / 14.53 / 2.40
  is the population sd of the 16 pooled clean epochs; the pooled within-run sd is 12.99 / 14.53 / 14.72 / 2.56; README §1,
  4.1, 6 and K13 label them so, and `pins.md` holds both. Spend recomputed from all 74 `.eval` logs and `rounds.jsonl`:
  measured $5.2448, writer $0.1613, total $6.2948, upper $7.6948; README §11 and `pins.md` now use these, with the rounding
  rule. S2 start 05:43:02 from the stream `run.jsonl`. Each re-checked value is now in README, `pins.md` and FINDINGS.

First run:

- Method: every numeric token of sections 1, 4, 7 and 11 (182 distinct values, sign ignored) was searched for in the Phase 7
  source files listed above (Phase 5 and Phase 8 files excluded); after T7.1 all are found except "20/20", which is 4 × 5/5
  from `sweep_tables.md` and says so. Presence is not context, so then by hand, at least: all of section 1 (per-seed table against `sweep_tables.md` "Non-inferiority per
  seed and pooled"; pooled 8/15, 9/13, 3/10, 4/10 and the spreads against FINDINGS 2026-10-22 "Pooled"; the 101 loss rounds
  against FINDINGS B 101), all of section 7 (against `sweep_tables.md` "Prediction ledger" clause lists and the owner's PLAN
  line of 2026-10-23), the twelve rows of table 4.1 (against each cell's O-lines), table 4.2 (against `refusal_table.md` and
  the archive lines), table 4.3 (against "Attribution"), and the spend table (against `pins.md`).
- First-pass FAIL: three figures in section 11 had no file behind them: S2 $0.7521 and S3 $1.1503 (sums of `pins.md` cells)
  and the upper bound $7.6949 (new). "20/20" in section 7 is 4 × 5/5 from `sweep_tables.md`; the derivation was added.
- Fix T7.1: `pins.md` section "Write-up figures (2026-10-23)" now holds the three figures with their arithmetic. Re-check:
  all three now trace to `pins.md`. PASS.

### 5. Prediction ledger — **PASS**

README section 7 scores predictions 1–8 per cell with the deciding numbers, the §11.1 verdict per rule and combined, the §3.5
falsifier, the §9(1) stop, NI-T (reported), PLAN §6 "Expected" (5 of 5) and the ambiguity triggers; all equal
`sweep_tables.md` and the owner's PLAN line of 2026-10-23.

### 6. pins.md — **PASS**

Tables for code (package revision per eval header, dirty, uncommitted files; inspect-ai, Python, uv, SDK; file sha256),
texts (brief and payload hashes), model strings as passed and resolved per role, seeds and temperature as sent from
`call.request` (B: "not sent"), settings (loop flags, task options, Inspect flags, clean baselines), dates (UTC) and spend
per step, for the check, the sweep and S2/S3. The writers' response snapshots are recorded as "not recorded".

### 7. Evidence layout, names, absolute paths — **PASS**

- `results/phase7_dgm_self_modifying/check/733_allocation_rule_autoallow/{A0…A5}` (the check cell continued with `--resume`
  for r3–r5, as PLAN §7.1 pre-registered; no clean episode in the check because the rule baseline is reused, PLAN §6),
  `early/baselines/733_none/run{1,2}`, `early/{selfmod_gpt4o, selfmod_gpt4o_linear, prop_sonnet55, prop_gpt4o}/<seed>_<preset>/`
  with `A0…A5`, `payload_r*.txt`, `rounds.jsonl`, `archive.jsonl` / `selfmod_log.jsonl` or `proposer_log.jsonl`; runner
  output `early_*.out` beside them; tables at the phase root. No `_`-prefixed directory.
- `grep -rln "/Users/\|/root/" --include=*.md --include=*.py --include=*.json` over `phases/phase7_dgm_self_modifying`,
  `results/phase7_dgm_self_modifying` and `docs/instruments/self_modifier.md`: no file. The same grep over the `.out` and
  `.log` files: no file.
- Note: `sweep_state.json` was repaired by hand (driver state, not a log; backup `sweep_state.json.bak-2026-10-23`; README D2).
- Re-run 2026-10-23: "No `_`-prefixed directory" above was wrong: `early/baselines/733_none/_run2_meta/` exists (the loop's
  `baseline.json` for run2). It is named in no table. PASS stands.

### 8. Limits and known issues — **PASS**

README section 8 (13 numbered limits, including the seeded-draw caveat 2–3, unsent and unlogged writer settings 8, effective
n 2, privileged and cross-session comparators 9–10) and section 9 (deviations D1–D12 in one list, known issues K1–K13 (K13 added 2026-10-23), each
open or closed and where disclosed).

### 9. Reproduce — **PASS** (re-run 2026-10-23; first run FAIL, T7.3)

- **Re-run 2026-10-23.** T7.3 was fixed by the independent check's task: the two tests now start `check.py` / `sweep.py` as
  subprocesses only with `--dry-run`, and check the refusal gates by calling `check.main()` / `sweep.main()` in process with
  the keys stripped and tripwires on every run, write and subprocess path (read in `tests/test_self_modifier.py`). README
  §10 now gives `34 passed` for the Phase 7 tests and `371 passed, 12 skipped, 2 deselected` for the full suite (the two
  deselected are Phase 5's driver tests). **Those counts are the independent checker's; this re-run did not execute the
  tests**, because the in-process gate checks call the drivers' `main()` without `--dry-run`, which this task's rules forbid.

First run:

Present: commit and pins, `uv sync --locked`, a Phase 7 test command with its expected output (`32 passed, 2 deselected`),
the mock end-to-end command and the dry-run output, the four paid commands as run with log directories, runtime and cost, the
table-regeneration command with its expected first lines, and what cannot be reproduced (B unseeded; round 0 not
deterministic; routing). Missing: §6's "test command (`uv run --locked pytest -q`) with the expected pass count". The bare
suite cannot be given, because `tests/test_self_modifier.py::test_check_refuses_without_env_file_and_dry_run_prints_the_command`
starts `check.py` without `--dry-run` and `::test_sweep_dry_run_lists_cells_and_runs_nothing_and_gates_hold` would start
`sweep.py` without it (and now fails on the existing `sweep_state.json`). This needs a code change to those two tests (README
K3); not fixed here. Touches no number or verdict.

### 10. Spend — **PASS** (re-run 2026-10-23: values now recomputed from the logs, see item 4; first run FAIL, then T7.2)

- Measured $5.2449 (episodes $5.0835 + logged writer $0.1614), estimates $1.05, total $6.2949 in `pins.md` "S2 and S3" table,
  README section 11 and STATUS (`phase7-tables S2/S3` line: "$6.2949 ($5.2449 measured + $1.05 writer estimates)"): match.
  The drivers' printed $4.39 / $6.29 are not used as the source.
- First-pass FAIL: no upper bound in `pins.md` or the README (SOP §4 asks for one where an estimate enters).
- Fix T7.2: `pins.md` "Write-up figures" and README section 11 now give the upper bound $7.6949 (Sonnet at PLAN §5's $0.50
  per cell upper, B-4o at its per-attempt upper), and say that no cache-at-full-price bound was computed. Re-check: present in
  both, consistent. PASS.

### 11. Contribution paragraph — **PASS** (re-run 2026-10-23: now names "A P-ext 0/5 vs B 3/3"; 119 words)

At the end of README section 1, 119 words (≤ 120), following the §5 template (question, method, episodes and spend,
prediction and falsifier, result with the deciding numbers and validity rules, mechanism check, two limits, audit state,
evidence paths).

### 12. Nothing from §7 occurred — **PASS** (with disclosures)

- Change after data without a dated amendment: none found. The `sweep_table.py` fixes (tied parents; NI-R in predictions 1–2)
  are analysis fixes to match the PLAN's wording, dated in the docstring and FINDINGS, and changed no verdict; the
  attribution table is labelled post hoc beyond the pre-registered split; the (d) reading and the §6(a) gain definition are
  dated PLAN lines (README D7, D9, D10).
- Number without a source: none after T7.1 (item 4).
- Conclusion outside the pre-registration: none; the headline is the §11.1 verdict.
- Paid run before approval, check or budget: approval 2026-10-21; check PASS at 17:57 UTC before the sweep at 18:15 UTC;
  budget lines in PLAN §5 / §11.1; S2/S3 under the owner's 2026-10-23 line (item 1 note on its time).
- Log edited, moved or deleted; table edited by hand: no `.eval` or log line edited; `sweep_state.json` (state) repaired with
  a backup (D2); tables regenerated by `sweep_table.py`. `refusal_table.md` was written by an offline reader, not by hand
  and not by a repository script (README K7).
- Framework source modified: none (ORBIT pinned `588b303`, unmodified per `pins.md`; no DGM or Inspect file in the diff).
- Secret, absolute path or AI-tooling file in a tracked file: absolute-path grep clean (item 7); `.env` not opened by this task.
- Commit or push by an agent: none by this task; the Phase 7 commit `dffe520` and `13c025c` carry the owner's identity.
- Audit answered by editing the audit: N/A (no audit yet).
- Cross-session comparator as within-session: the reused baselines and historical proposer cells are labelled "other
  session" / "across sessions" (README section 6).
- Estimate as measured: the $1.05 writer estimate is labelled everywhere it appears.
- Mechanism claim from the logged event when the raw request existed: the check read every kept `call.request` (CHECK.md (d)).
- Outside §7, disclosed: a test run started `check.py` without `--dry-run` (it refused, no call; README D5); no §9 council file
  for the not-matched predictions (README D12).

### 13. Statistical validity — **PASS** (re-run 2026-10-23, after T7.8; first run passed it wrongly)

- **Re-run 2026-10-23.** README §1's NI-R bullet pooled A 3/10 against B 4/10 under "The rate basis of the verdict is the three
  seeds"; it is two seeds, two draws per arm. It is now labelled "two draws per arm, an exhibit and not a rate" with the
  per-seed d_R first (NI-R on the evaluable seeds is pre-registered, §3.2 / §11.1; no verdict changes). FINDINGS
  corrections entry of 2026-10-23.

First run:

The headline is the three-seed none replicate (733, 512, 101; PLAN §11.1). Every pooled figure in the README has its per-seed
values and min–max beside it (d_Δ, d_P, NI-R). Every per-cell count, the rule cell and S2/S3 are labelled one draw, an
exhibit; clean-baseline x/16 counts are labelled base-rate exhibits of one seed; no rate is drawn from fewer than 3 draws.

### 14. Instrument documents — **PASS** (re-run 2026-10-23: T7.4 fixed by the independent check's task; `proposer.md` and
`allocation_rule.md` Phase 7 entries left to the coordinator)

`docs/instruments/self_modifier.md` (all six §2.7 sections), `proposer.md` and `allocation_rule.md` exist, are listed in
`docs/instruments/README.md`, and are linked from README section 3. Note: `self_modifier.md` §5 still says "Mechanism checks
on real logs: none yet" and the index row says "no paid run yet"; no dated entry since the check (README K11; task T7.4).

### 15. Run log, status, mock end-to-end — **PASS**

`run.jsonl` exists in all 17 run directories (stream, check, check cell, 733 none baseline cell and its two runs, 11 sweep
cells); `python -m control_loop.status results/phase7_dgm_self_modifying` lists 17 rows with costs (its total over-counts,
README K1). `tests/test_e2e_self_modifier.py` (the §2.8 test for this phase's attacker on the ORBIT adapter) exists and
passes (3 tests, within the 32 above).

## Task list

| id | item | what | status |
|---|---|---|---|
| T7.1 | 4 | add the S2 / S3 subtotals and the upper bound to `pins.md` with their arithmetic; derivation of "20/20" in README §7 | **fixed** 2026-10-23, re-checked |
| T7.2 | 10 | upper bound in `pins.md` and README §11 | **fixed** 2026-10-23, re-checked |
| T7.3 | 9 | make the two driver-starting tests in `tests/test_self_modifier.py` safe (dry-run only, or a temporary results root), then state the full-suite count in README §10 | **fixed** 2026-10-23 by the independent check's task |
| T7.4 | 14 (note) | dated entry in `docs/instruments/self_modifier.md` (§5 check tables by path; change history for the check, sweep and S2/S3) and the index row | **fixed** 2026-10-23 by the independent check's task |
| T7.5 | – | re-run this check by an agent other than the README's writer (§8) | **done**: `audits/sop_check_independent.md` |
| T7.6 | – | owner's 2026-10-23 Phase 7 rulings into the STATUS decisions log (README K12); decide whether SOP §9 needed a council for predictions 1, 2, 5, 7 (README D12) | STATUS line **done**; council question open, owner |
| T7.7 | 4 | "25" → 20 seeded + 10 linear selections; "within-run sd" relabelled; spend and S2 start recomputed from the logs; FINDINGS corrections entry; `pins.md` agrees | **fixed** 2026-10-23 |
| T7.8 | 13 | NI-R pooled over two seeds labelled two draws per arm, an exhibit | **fixed** 2026-10-23 |
| T7.9 | – | `sweep_table.py` still prints the 16-epoch sd as "within-run sd" (README K13) | open, code (no number or verdict) |

## Re-run after the cross-family audit, 2026-10-23 (task phase7-audit-response, the README's writer)

Rows touched by the response to `audits/audit_astra.md` (`audits/RESPONSE.md`); the others are unchanged.

- **3 (README sections and headline): PASS.** The headline keeps "undecided" under both rules and combined; its "not the same"
  clause now names both conditions (pooled failure and 2 of 3 seeds, A3). Section 12 is filled for audit round 1.
- **4 (numbers): PASS.** New figures (halt-only sensitivity, static spreads, the rule-cell capture fact) trace to FINDINGS
  "corrections after the cross-family audit" and `pins.md` "Write-up figures"; each was recomputed from `rounds.jsonl`. No
  earlier number changed.
- **5 (ledger): PASS.** No prediction call changed; prediction 7 also holds as "not matched" under the halt-only sensitivity.
- **8 (limits and known issues): PASS.** Limit 13 adds the process qualification (A6); K9 and K13 closed.
- **9 (reproduce): PASS.** §10 says "Regenerate the generated tables" and lists the artifacts no repository script regenerates (A8).
- **12 (§7): PASS.** `sweep_tables.md` changed only by regeneration from the edited `sweep_table.py` (26 label lines);
  no table edited by hand; `sweep_summary.json` and `round_table_crosscheck.md` byte-identical after the re-append.
- **13 (statistical validity): PASS.** The sensitivity and static-spread figures are labelled post hoc; the attribution reading
  now calls the columns descriptive contrasts of single draws (A4).
- **T7.9 fixed** (`SD_LABEL`, `FLOOR_LABELS`, test `test_sweep_table_sd_and_floor_labels`).

Result after this re-run: 15 PASS, 0 FAIL, 0 N/A.

**Note 2026-10-23 (task phase7-sop-independent, owner's ruling).** Item 9's driver tests: the owner accepted the in-process gate tests provided a test hits a launch path and asserts the tripwire raises. Added `test_tripwire_fires_on_the_check_launch_path` and `test_tripwire_fires_on_the_sweep_launch_path` (dummy keys, tmp paths, tripwire raises on the `control_loop.loop` subprocess; both fail with the inert toggle `P7_TRIPWIRE_INERT=1`). Counts now: Phase 7 tests 37 passed; full suite 374 passed, 12 skipped, 2 deselected (the two Phase 5 driver tests). README §10 updated; FINDINGS 2026-10-23 "tripwire tests".
