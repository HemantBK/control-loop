# Independent SOP check — Phase 7: self-modifying coalition agent (docs/SOP.md §8)

Date: 2026-10-23. Checker: task phase7-sop-independent (Claude). This checker did not write `README.md`, `FINDINGS.md`,
`pins.md` or the tables. In the same task it did edit three things that this check touches, so those parts are not
independent: the two driver tests in `tests/test_self_modifier.py` (item 9), README section 10's test paragraph (item 9, the
only README edit) and `docs/instruments/{self_modifier.md, README.md}` (item 14). The first check
(`audits/sop_check.md`, same date) was read only after every mark below was set. No model call, no paid run, no commit.
`check.py` and `sweep.py` were run only with `--dry-run`. Marks: **PASS**, **FAIL** (the SOP's "gap"), **N/A**.

Read: `docs/SOP.md`; `phases/phase7_dgm_self_modifying/{PLAN.md, README.md, FINDINGS.md, pins.md}`;
`results/phase7_dgm_self_modifying/{sweep_tables.md, sweep_summary.json, refusal_table.md, run.jsonl, sweep_driver_s2.log}`,
the cells' `rounds.jsonl`, `archive.jsonl` and `selfmod_log.jsonl`, and `check/733_allocation_rule_autoallow/CHECK.md`;
`docs/instruments/{README.md, self_modifier.md, proposer.md, allocation_rule.md}`; `STATUS.md`; the root `README.md` row 7.
Commands on the pod (all with the API keys unset): `uv run --frozen python` on a stdlib/Inspect script outside the
repository. It recomputes the clean means and sds from the four baselines' `.eval` logs, the per-cell measures from
`rounds.jsonl`, the episode spend from every `.eval` with `control_loop.spend.log_cost`, and the writer spend from
`rounds.jsonl`. Also run: `python -m control_loop.status results/phase7_dgm_self_modifying`,
`sweep.py --dry-run --s2 --s3`, `check.py --dry-run`, the absolute-path and secret grep, a RECORD-hash check of the
installed `orbit-1.0.3` and `inspect_ai-0.3.263`, `git log` / `git diff` of PLAN.md, and the test suite (item 9).

**Result: 13 PASS, 2 FAIL (items 4 and 13), 0 N/A.** Both FAILs need a short README wording fix and no new run. The item 4
gap is a number (a count of re-derived selections), so under §8 it should be fixed before the audit starts. The item 13 gap
touches only how a pooled figure is labelled, not its value or the verdict.

## Items

### 1. PLAN — **PASS**

- Header "(written 2026-10-21, before any code or run)". §1 Design, §2 DGM (added), §3 predictions §3.4 with the verdict
  rule and falsifier §3.5, §4 Metrics, §5 Budget, §6 Mechanism check, §7 Sweep, §8 decisions D1–D12, §9 threats, §10
  Owner's approval (2026-10-21), §11 owner's amendment (2026-10-21), then dated lines 2026-10-22 (×4) and 2026-10-23 (×2).
- §1–§11 are in commit `dffe520` (2026-10-22 13:34:22 UTC, `git log`). The first paid log is
  `check/.../A0/2026-10-22T17-55-14-…eval` (`check/run.jsonl` tests step 17:55:10Z), so the approval precedes it.
- `git diff` of PLAN.md against `dffe520` has one hunk above the dated lines, a bracketed "[note 2026-10-22: …]" in §5 (the
  Sonnet cache-read price). It is otherwise only appended dated lines. STATUS "phase7-remaining-checks" places the note
  before the check. Git cannot confirm this because it is uncommitted (README limit 13).
- Format notes (no gap): the falsifier is §3.5, not its own section; the amendments are dated lines rather than
  `### Amendment` headings; the §5 note does not say "revised in place before any run".

### 2. FINDINGS — **PASS**

There is an entry for every paid run, each with log paths, UTC and spend. The check is 2026-10-22, with "Nothing below
enters a table". Each sweep cell is 2026-10-22. S2/S3 are 2026-10-23, the same day as the runs. The 2026-10-22 "25 seeded
parent selections" needs a corrections entry; see item 4.

### 3. README sections and headline — **PASS**

All twelve §2.4 sections are present in order. The headline gives "undecided" under the allocation rule, under the
completion rule and combined, in the §3.5 / §11.1 wording. The per-seed denominators are in the table below it (valid A
5/5/5, B 5/5/3; NI-P fails at 1 of 3 seeds). No causal word is used, and post hoc readings are labelled.

### 4. Numbers in README sections 1, 4, 7 and 11 — **FAIL** (one count does not trace; one label is wrong)

Section 1 was checked in full, section 7 in full, and table 4.1, table 4.2, the §4 header paragraph and the §11 spend
table were sampled (see the spot-check table; 26 rows, about 120 values).

- **Gap.** §4 says the independent reader "re-derived all 25 seeded parent selections" (from FINDINGS 2026-10-22). The four
  A archives hold **20** seeded selections (`rule: dgm_sigmoid_children`, 5 per cell). The two A-lin archives hold 10
  `linear_latest` ones, and the four A cells logged 23 writer calls. No log, generated table or PLAN section gives 25.
  - Fix: README §4 should say "all 20 seeded parent selections (and the 10 linear ones of S2)", or cite the reader's own
    count.
  - FINDINGS needs a corrections entry.
- **Label.** "within-run sd" (table 4.1 header and section 6 "within-run sd; run means") prints 13.44 / 15.67 / 14.53 /
  2.40. These values are the population sd of all 16 pooled clean epochs (`control_loop/results.py`,
  `sd=st.pstdev(rewards)`), not a within-run sd.
  - The pooled within-run sd is 12.99 / 14.53 / 14.72 / 2.56 (rule 733 / none 733 / 512 / 101).
  - The values trace to `sweep_tables.md`, which uses the same label. No verdict uses them (K9); §1 calls them "clean sd".
  - Fix: relabel in the README (and in `sweep_table.py` / `sweep_tables.md` by a dated note), or disclose as a known issue.
- **Rounding (note).** The exact measured spend is $5.2448 (episodes $5.083538 + writer $0.161300). The README and pins
  give $5.2449 and $6.2949 because they sum four-decimal cell figures. `control_loop.status`'s sweep row prints 6.2948,
  which the README quotes. A 0.0001 difference.

### 5. Prediction ledger — **PASS**

- README §7 scores predictions 1–8 per cell with the deciding numbers. It also gives the §11.1 verdict per rule and
  combined, the §3.5 falsifier, the §9(1) stop, NI-T, PLAN §6 "Expected" and the ambiguity triggers.
- Recomputed from `rounds.jsonl`: the 3-ticket rounds in the rule cell (A 4/5, B 3/5), P-ext 0/5 in both arms, O4 +13.08
  / +4.52, d_Δ range 14.72 and the 101 clauses (B 0/3, −18.13, d_P −1.00).
- PLAN §3.5's "a prediction among 1–6 not matched … recorded in a dated amendment" is met by the owner's 2026-10-23 line.
  That line also covers 7, which §3.5 does not list (§11.1 added it).

### 6. pins.md — **PASS**

pins.md covers the check, the sweep and S2/S3. Each section has:

- code (revision per eval header, dirty, file sha256, versions);
- texts (brief and payload sha256);
- model strings as passed and as resolved per role;
- seeds and temperature as sent from `call.request` (B: "not sent");
- settings;
- UTC dates and spend per step.

The writers' resolved snapshots are marked "not recorded".

### 7. Evidence layout, names, absolute paths — **PASS** (note)

- The layout follows §3: `check/733_allocation_rule_autoallow/A0…A5` with `CHECK.md`; `early/{baselines, selfmod_gpt4o,
  selfmod_gpt4o_linear, prop_sonnet55, prop_gpt4o}/<seed>_<preset>/A0…A5`; runner `early_*.out` beside them; tables at the
  phase root.
- SOP item 7's absolute-path grep (Mac and pod home prefixes) over `*.md *.py *.json *.jsonl *.log` in the phase directory and its
  results, and over `results/phase7_dgm_self_modifying/*.out`, hits only the grep pattern quoted in `audits/sop_check.md`.
- The `sk-` / `sk-ant-` grep is clean.
- Note: there is one `_`-prefixed directory, `early/baselines/733_none/_run2_meta/` (holds `baseline.json` only). It is
  named in neither `sweep_tables.md` nor `sweep_summary.json`, so it enters no table.

### 8. Limits and known issues — **PASS**

- §8 has 13 numbered limits: seeded draws (2, 3), unsent and unlogged settings (8), effective n (2), cross-session (10).
- §9 has deviations D1–D12 and known issues K1–K12, each with its status.
- Several entries are now stale after this task: D5, K3, K11, K12 (see the README fixes).

### 9. Reproduce — **PASS** (after the 2026-10-23 test fix; this checker edited the test paragraph)

- The two tests in `tests/test_self_modifier.py` that started `check.py` / `sweep.py` without `--dry-run` now check the
  refusal in process. The keys are stripped, the state file is redirected to `tmp_path`, and every run or write path is a
  tripwire. They keep the `--dry-run` subprocess calls.
- `pytest -q tests/test_self_modifier.py` gives 31 passed. The README's Phase 7 command gives **34 passed**.
- The full suite gives **371 passed, 12 skipped, 2 deselected** (3 min, `--frozen`). The two deselected tests are Phase 5's
  `test_phase5_harness.py::test_sweep_dry_run_prints_primary_cells_in_order_and_runs_nothing` and `::test_check_refuses_without_env_file`.
  They start Phase 5's `sweep.py` / `check.py` without `--dry-run` and were not run.
- README §10 now gives both commands and counts (the only README edit by this checker).
- The rest is present and checked:
  - commit and pins, `uv sync --locked`;
  - the mock e2e command;
  - `sweep.py --dry-run --s2 --s3` output as stated (first line "13 cells … $6.29", 14 rows all done or complete, "dry run:
    nothing was run.", `sweep_state.json` mtime unchanged);
  - the four paid commands with directories, runtimes and costs;
  - the table regeneration command with its first lines;
  - what cannot be reproduced.
- Residual: the bare `uv run --locked pytest -q` still starts the two Phase 5 drivers without `--dry-run`, so §6's bare
  command is given with two deselects (task T7i.1).

### 10. Spend — **PASS** (note)

- The README §11 and `pins.md` figures match: measured $5.2449, estimates $1.05, total $6.2949, upper bound $7.6949.
- The STATUS Uncommitted line `phase7-tables S2/S3` matches ($6.2949).
- Recomputed episodes $5.0835 over 74 `.eval` logs and 88 episodes. Writer $0.1613 exact (see item 4 for the rounding).
- Note: the STATUS "Phases" block still has `6,7 not started` and no Phase 7 line (manager, T7i.4).

### 11. Contribution paragraph — **PASS** (note)

The paragraph is 119 words, at the end of §1. It has the question, method, episodes and spend, prediction, falsifier,
result under both rules, mechanism check, two limits, audit state and evidence. Note: the template's "<comparator> gave
<number>" is not explicit. Adding "A P-ext 0/5 against B 3/3 at 101" would give the deciding numbers with denominators.

### 12. Nothing from §7 occurred — **PASS** (with notes)

- **Change after data without an amendment:** none found. The `sweep_table.py` fixes are dated and changed no verdict (D10).
  The (d) reading and the §6(a) gain are dated PLAN lines.
- **Number without a source:** see item 4 ("25").
- **Conclusion outside the pre-registration:** none; post hoc is labelled.
- **Paid run before approval, check or budget:** none. The approval is dated 2026-10-21, the check finished 17:57:11Z and
  the sweep started 18:15:11Z (`run.jsonl`).
- **Log edited or table by hand:** none. Notes: `sweep_state.json` was repaired, but it is driver state with a backup
  (D2). `refusal_table.md` comes from an out-of-repository reader (K7). `round_table_crosscheck.md`'s appended section
  (K8).
- **Framework source modified:** none. The installed files of `orbit-1.0.3` (487) and `inspect_ai-0.3.263` (840) all match
  their wheel RECORD sha256.
- **Secret, absolute path or AI-tooling file:** none in the phase or its results (item 7). `git ls-files` shows no tooling
  config; the `audit_claude.md` files are audit reports.
- **Commit by an agent:** none by this task.
- **Cross-session presented as within-session:** no; labelled in §6 and limit 10.
- **Estimate as measured:** no.
- **Logged event used where the raw request was available:** no; (c) and (d) read `call.request`.
- **Owner's rule:** "check.py only with --dry-run" was broken by a test run (D5). Closed in code by this task.

### 13. Statistical validity — **FAIL** (label)

- The headline rests on the three-seed none replicate, and every pooled figure has its per-seed values and spread beside
  it.
- **Gap.** README §1 pools NI-R as "pooled A 3/10 against B 4/10" over seeds 733 and 512 only. That is a
  fraction from two distinct draws per arm, which §4 does not allow as a rate. It appears under "The rate basis of the
  verdict is the three seeds".
  - NI-R being evaluated on two seeds is pre-registered (§3.2, §11.1), and the verdict does not change.
  - Fix: label it "two seeds, two draws per arm, not a rate", or give only the per-seed d_R.
  - The first check passed this item.

### 14. Instrument documents — **PASS** (note; this checker updated `self_modifier.md` in the same task)

- `self_modifier.md`, `proposer.md` and `allocation_rule.md` exist, are listed in `docs/instruments/README.md` and are
  linked from README §3.
- `self_modifier.md` and its index row gained a dated 2026-10-23 entry for the check, the sweep and S2 (A-lin), with the
  measured biases. This closes T7.4 / K11.
- Note: `proposer.md` has no dated entry for its Phase 7 use, as arm B and as S3's B-4o with a gpt-4o writer (new model
  string, seed and T sent, usage not logged). `allocation_rule.md` still says "planned for Phase 7", as does its index row
  "7 (planned)". Task T7i.3.

### 15. Run log, status, mock end-to-end — **PASS**

- There are 17 `run.jsonl` files, and every directory holding `.eval` logs has one in itself or in its cell directory.
- `control_loop.status` lists 17 rows with costs (total $11.4353 over 14 leaf runs, over-counted as K1 says; the sweep row
  is 6.2948).
- `tests/test_e2e_self_modifier.py` exists and passes (3 tests).

## Spot-check of README numbers (independent recomputation)

Sources: `.eval` = the logs read with `inspect_ai.log.read_eval_log` (coalition = dev_0 + dev_1 `per_agent_reward`);
`rounds` = the cell's `rounds.jsonl`; P-ext recomputed from `final_owner` against the cell's reference allocation.

| # | README place | README value | recomputed | source | match |
|---|---|---|---|---|---|
| 1 | §6, 4.1 none 733 clean | 88.81 / 25.34, run means 96.6 / 81.0 | 88.81 / 25.34, 96.6 / 81.0 | `early/baselines/733_none/run{1,2}` .eval | yes |
| 2 | §6 rule 733 clean | 64.57 / 50.14, 58.8 / 70.3 | 64.57 / 50.14, 58.8 / 70.3 | Phase 3 run{1,2} .eval | yes |
| 3 | §6 512 / 101 clean | 66.70 / 24.15; 49.29 / 41.69 | same | v2 run{1,2} .eval | yes |
| 4 | §1, 4.1, §6 clean sd | 15.67, 13.44, 14.53, 2.40 ("within-run sd") | pstdev over 16 epochs 15.67, 13.44, 14.53, 2.40; pooled within-run 14.53, 12.99, 14.72, 2.56 | .eval | value yes, **label no** |
| 5 | 4.1 O4, 12 cells | +13.08, +4.52, +3.36, +0.80, −1.02, −14.39, −0.86, −18.13, +14.50, +14.78, +8.61, +8.75 | identical | rounds + .eval means | yes |
| 6 | 4.1 valid | 5/5 everywhere, B 101 3/5 | same (B 101 r3, r4 invalid under both rules) | rounds | yes |
| 7 | 4.1 / §1 P-ext | A 3, B 2 (733); 5, 4 (512); 0, 3 (101); rule 0, 0; A-lin / B-4o 4, 4 none, 0, 0 rule | identical | rounds `final_owner` | yes |
| 8 | 4.1 / §1 O1 | 4, 3, 3, 2, 0, 2, 1, 0, 4, 4, 3, 3 | identical | rounds | yes |
| 9 | §1 d_Δ | +2.56 / +13.38 / +17.28, mean +11.07 | 2.5600 / 13.3760 / 17.2767, mean 11.07 | rounds + .eval | yes |
| 10 | §1 d_P | +0.20 / +0.20 / −1.00 | same | rounds | yes |
| 11 | §1 pooled P-ext | A 8/15, B 9/13 | 8/15, 9/13 | rounds | yes |
| 12 | §1 B 101 P-ext rounds | Δcoal −25.09, −10.16, −19.16 | −25.09, −10.16, −19.16 (r1, r2, r5) | rounds | yes |
| 13 | §7 pred. 3 | 3 tickets A 4/5, B 3/5; blocks 0–2 | 4/5, 3/5; 1–2 (A), 0–2 (B) | rounds | yes |
| 14 | header, contribution | 74 `.eval` logs, 88 episodes | 74, 88 | `find`, eval headers | yes |
| 15 | §11 episodes | $5.0835; check $0.1815 | $5.0835; $0.1815 | `log_cost` over every .eval | yes |
| 16 | §11 writer logged | $0.1614 | $0.1613 (0.161300); sum of 4-dp cell figures 0.1614 | rounds `proposer.cost_usd` | rounding only |
| 17 | §11 measured / total | $5.2449 / $6.2949 | $5.2448 / $6.2948 (`status` sweep row 6.2948) | as above | rounding only |
| 18 | pins / §11 S2 | A-lin episodes $0.3245 / $0.3781 | same | .eval | yes |
| 19 | pins A none 101, B-4o none | $0.3998, $0.3120 | same | .eval | yes |
| 20 | §1, 4.2 writer calls | 23 (6, 6, 5, 6); A-lin 5 + 5 | same | `selfmod_log.jsonl` lines | yes |
| 21 | 4.2 parents | 0,1,2,2,3; 0,1,2,2,3; 0,1,2,1,3; 0,1,1,3,0 | same; A-lin 0,1,2,3,4 | `archive.jsonl` | yes |
| 22 | §4 header | "all 25 seeded parent selections" | 20 seeded + 10 linear | `archive.jsonl` `selection.rule` | **no** |
| 23 | K1 | status $11.4353 over 14 leaf runs, sweep row 6.2948 | same | `control_loop.status` | yes |
| 24 | §10 dry run | "13 cells … $6.29", 14 rows done/complete | same | `sweep.py --dry-run --s2 --s3` | yes |
| 25 | §10 runtimes | check 17:55:10–17:57:11; sweep 18:15:11–18:50:04; S2 05:43:01–05:52:47; S3 05:43:12–05:52:27 | same, except S2 start 05:43:02Z in the stream `run.jsonl` (no repository file has 05:43:01) | `check/run.jsonl`, `run.jsonl` | S2 start off by 1 s |
| 26 | §5, contribution | 156 of 156; 119 words | `CHECK.md` "156 of 156"; 119 words | file; word count | yes |

**Mismatches:**

- **#22:** 25 against 20. This one is substantive.
- **#4:** label only.
- **#16 and #17:** a 0.0001 rounding difference.
- **#25:** a 1-second difference.

## Proposed README fixes (not made here; only the §10 test paragraph was edited)

1. §4 header: "25 seeded parent selections" becomes "20 seeded (and the 10 S2 linear) parent selections". Add a FINDINGS
   corrections entry for the 2026-10-22 "25".
2. §1 NI-R bullet: label "pooled A 3/10 against B 4/10" as two seeds, two draws per arm,
   not a rate.
3. Table 4.1 and §6: "within-run sd" becomes "sd over the 16 clean epochs", or disclose the label as a known issue.
4. D5 and K3: closed 2026-10-23 (the tests check the gates in process). K11 is closed (instrument doc dated entry).
   K12 is closed (STATUS decisions line 2026-10-23). Note that the bare suite still starts two Phase 5 drivers.
5. Optional:
   - give exact measured $5.2448 / total $6.2948, or say the four-decimal figures are sums of rounded cells;
   - S2 start 05:43:02 (stream `run.jsonl`) or cite the job log for 05:43:01;
   - add the comparator number "A 0/5 against B 3/3" to the contribution paragraph.

## Task list

| id | item | what | status |
|---|---|---|---|
| T7.3 | 9 | make the two Phase 7 driver tests safe; state the counts in README §10 | **fixed** 2026-10-23 (this task) |
| T7.4 | 14 | dated entry in `self_modifier.md` and its index row | **fixed** 2026-10-23 (this task) |
| T7.5 | – | independent re-run of the SOP check | **done** (this file) |
| T7.6 | – | owner's 2026-10-23 rulings into the STATUS decisions log | **fixed** (decisions line 2026-10-23); D12 council question stays with the owner |
| T7i.1 | 9 | `tests/test_phase5_harness.py`: two tests start Phase 5's `sweep.py` / `check.py` without `--dry-run` | open, code (not Phase 7) |
| T7i.2 | 4, 13 | README fixes 1–3 above and the FINDINGS corrections entry | open, writer |
| T7i.3 | 14 | dated Phase 7 entries in `proposer.md` (B, B-4o) and `allocation_rule.md`; their index rows | open, documentation |
| T7i.4 | 10 | STATUS "Phases" block: Phase 7 line (it still reads `6,7 not started`) | open, manager |

## Differences from the first check (`audits/sop_check.md`)

| item | first check | this check | why |
|---|---|---|---|
| 4 | PASS (after T7.1) | **FAIL** | "25 seeded parent selections" does not match the archives (20). The token search passed it because "25" occurs in FINDINGS. "within-run sd" is a pooled 16-epoch population sd. |
| 7 | PASS, "No `_`-prefixed directory" | PASS with note | `early/baselines/733_none/_run2_meta/` exists (enters no table) |
| 9 | FAIL (T7.3 open) | PASS | tests fixed and counts stated by this task; residual Phase 5 tests listed (T7i.1) |
| 10 | PASS | PASS with note | STATUS "Phases" block stale for Phase 7; $0.0001 rounding |
| 11 | PASS | PASS with note | comparator number not explicit |
| 12 | PASS | PASS | adds the RECORD-hash check of ORBIT and Inspect; D5 now closed in code |
| 13 | PASS ("no rate from fewer than 3 draws") | **FAIL** | NI-R pooled 3/10 vs 4/10 is from two seeds |
| 14 | PASS, note T7.4 | PASS, note T7i.3 | T7.4 fixed here; `proposer.md` and `allocation_rule.md` also lack Phase 7 entries |
| 1, 2, 3, 5, 6, 8, 15 | PASS | PASS | same evidence found independently |

Overall: the first check gave 14 PASS / 1 FAIL (item 9). This check gives 13 PASS / 2 FAIL (items 4 and 13). Item 9 is now
PASS.

## Note 2026-10-23 (task phase7-writeup, the README's writer; verdicts above unchanged)

- **Item 4, fixed.** README §4 now says "all 20 seeded parent selections (5 per A cell) and the 10 linear ones of S2"
  (recomputed from the six `archive.jsonl`); FINDINGS corrections entry of 2026-10-23. The clean sds are relabelled in README
  §1, table 4.1, §6 and K13: 13.44 / 15.67 / 14.53 / 2.40 as the sd of the 16 pooled epochs, with the pooled within-run sd
  12.99 / 14.53 / 14.72 / 2.56 beside them in §6 (recomputed from the `.eval` logs; `pins.md` "Write-up figures").
  `sweep_tables.md` keeps its generated label (README K13; it contains no "25").
- **Item 13, fixed.** README §1's NI-R bullet gives the per-seed d_R first and labels the pooled A 3/10 vs B 4/10 as two
  draws per arm, an exhibit and not a rate.
- **Notes taken up.** Spend now recomputed from the logs with the rounding rule stated (measured $5.2448, writer $0.1613,
  total $6.2948, upper $7.6948) in README §11 and `pins.md`; S2 start 05:43:02 (stream `run.jsonl`) in README D1 and §10;
  "A P-ext 0/5 vs B 3/3" in the contribution paragraph (119 words); D5, K3, K11, K12 closed in README §9.

**Note 2026-10-23 (task phase7-sop-independent, owner's ruling).** Item 9's driver tests: the owner accepted the in-process gate tests provided a test hits a launch path and asserts the tripwire raises. Added `test_tripwire_fires_on_the_check_launch_path` and `test_tripwire_fires_on_the_sweep_launch_path` (dummy keys, tmp paths, tripwire raises on the `control_loop.loop` subprocess; both fail with the inert toggle `P7_TRIPWIRE_INERT=1`). Counts now: Phase 7 tests 37 passed; full suite 374 passed, 12 skipped, 2 deselected (the two Phase 5 driver tests). README §10 updated; FINDINGS 2026-10-23 "tripwire tests".
