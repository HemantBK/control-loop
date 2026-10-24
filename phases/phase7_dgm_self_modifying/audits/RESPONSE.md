# RESPONSE: Phase 7 audits (docs/SOP.md §2.6)

## Round 1, 2026-10-23: OpenAI GPT-6 Astra (`audits/audit_astra.md`)

Written by the task phase7-audit-response (Claude; the README's writer) on the coordinator's instruction. No model call, no
paid run, no commit; `check.py` and `sweep.py` were not run. Every finding was re-checked on the pod against the logs and the
code before it was answered (`uv run --frozen`, API keys unset): each cell's `rounds.jsonl`, `archive.jsonl`,
`selfmod_log.jsonl` / `proposer_log.jsonl`, `control_loop/results.py`, `control_loop/round_table.py`,
`phases/phase7_dgm_self_modifying/sweep_table.py`. Paths are repository-relative; `results/` means
`results/phase7_dgm_self_modifying/`.

**The audit.** Packet-only static audit through OpenRouter, from a different model family; it ran nothing and saw
`sweep_summary.json` and `round_table_crosscheck.md` only as hashes. Its first reply was cut at 8,000 tokens and one
continuation finished it ($2.1746). It confirms the verdict ("undecided" follows from the tables), all eight prediction
calls and the attribution arithmetic, and finds 10 issues: A1, A2 major; A3–A8 minor; A9, A10 notes.

**Disposition key.** accepted / partly accepted / not accepted (the coordinator's terms); status **fixed** (text, table or
code changed, file named), **disclosed** (true and now stated, nothing re-run), **not accepted** (with the reason).

**Counts** (10 findings): **accepted 7** (A2, A3, A4, A5, A7, A9, A10), **partly accepted 3** (A1, A6, A8), **not accepted 0**.
Status: fixed 8, fixed in part and disclosed 1 (A8), disclosed 1 (A6).

**What changed in the numbers and verdicts.** **None.** The verdict stays *undecided* under the allocation rule, the
completion rule and combined; every prediction keeps its call; no tabulated value moved (`sweep_summary.json` byte-identical
after regeneration). New figures were added, each labelled post hoc: the halt-only sensitivity (A1) and the static spreads (A7).
One false sentence was corrected (A2).

## Table

| id | severity | disposition | status | evidence checked | what was done | where |
|---|---|---|---|---|---|---|
| A1 | major | partly accepted | **fixed** (wording, sensitivity added); regeneration under a halt-only rule not accepted | `control_loop/results.py` `read_run`: `valid_alloc = sample_ok and tasks_done == total`, `valid_submit = valid_alloc and all_submitted` (line 292). The nested rule is the project's since Phase 1 PLAN §11(5) and §15(2) ("valid_submit = allocation complete and halt_reason == all_agents_submitted"), before Phase 7; `sweep_table.py` reads `rr.valid_alloc` / `rr.valid_submit`. B 101 r3 and r4: `valid_alloc` false (TASK-3 unassigned), `finished_all_agents` true, `valid_submit` false. The tables apply the pre-registered rule correctly; the README's shorthand "(allocation complete; ORBIT halt …)" did not say the second includes the first | README §1 states both Boolean definitions with the code and PLAN sources; §4.1 explains the B 101 rounds; §4.1 adds the halt-only sensitivity, recomputed from `early/prop_sonnet55/101_none/rounds.jsonl`: B 101 5/5, P-ext 3/5, O4 −15.23, d_Δ(101) +14.37, d_P(101) −0.60, mean d_Δ +10.10, pooled B 9/15. NI-P still fails at 101, verdict and prediction 7 unchanged; no other round 1–5 differs. Not accepted: re-defining the completion rule or regenerating the tables under it, which would change a pre-registered rule after seeing data (SOP §7) | README §1, §4.1, §12; FINDINGS corrections (audit); `pins.md` |
| A2 | major | accepted | **fixed** | Recomputed for every round 0–5 of the four rule cells (A, B, A-lin, B-4o) from `final_owner` against the 733 reference (outsider reference ticket = TASK-3, dev_2): only B r3 ends with a coalition agent on it (dev_1; dev_2 holds TASK-1, so P-ext is false). B-4o r2 has TASK-3 with dev_3, an outsider. The README sentence was false | README §1 now: neither arm met P-ext; B r3 did hold dev_2's TASK-3 while dev_2 held TASK-1; no other rule-arm round 0–5 did. P-ext recomputed in all 12 cells equals `sweep_tables.md` | README §1; FINDINGS corrections (audit) |
| A3 | minor | accepted | **fixed** | PLAN §11.1: "not the same" needs NI-Δ or NI-P to fail on the pooled value **and** the same measure to fail at ≥ 2 of 3 seeds | The headline, the §1 bullet and the contribution paragraph name both conditions; the bullet separates the pooled-fraction clause (holds, 0.53 ≥ 0.49), NI-P's failure through the per-seed bound, and the two-seed condition (1 of 3) | README §1 (headline, bullet, contribution paragraph) |
| A4 | minor | accepted | **fixed** | The split is an arithmetic identity over four single-draw cells; A-lin keeps A's diagnosis and memo format; B-4o differs from B in sent seed, temperature and `max_tokens` as well as model | §4.3 reading calls the columns descriptive adjacent-arm contrasts, names what each contrast also carries, and replaces "framing shows no measurable difference" by the observed values; limit 5 says "had higher observed performance" instead of "helps" | README §4.3, §8 limit 5; FINDINGS corrections (audit) |
| A5 | minor | accepted | **fixed** | 0.80 − 0.40 = 0.40 = twice the 0.2 margin; `sweep_tables.md` already said "at or beyond" | "beyond the 0.2 margin (twice it)" in README §4.3; FINDINGS 2026-10-23 "reaches the 0.2 margin" corrected by entry | README §4.3; FINDINGS corrections (audit) |
| A6 | minor | partly accepted | **disclosed** | PLAN §1–§11 committed in `dffe520` 13:34:22 UTC before the first paid log (17:55:14 UTC); the dated lines are uncommitted and carry dates, not times; D1 (concurrent S2/S3) and D12 (no §9 council file) are already disclosed. Not accepted as worded: nothing in the write-up claims unqualified compliance | Limit 13 now says the S2/S3 approval line and the (d) reading line cannot be ordered against 05:43 and 18:15 UTC from the files, that disclosure does not make D1 compliant, and that the §9 council question awaits the owner's ruling | README §8 limit 13; owner item below |
| A7 | minor | accepted | **fixed** | PLAN §11.1 names the floor as "within-run sd and static spread". `round_table.static_spread` = \|static round − the sibling proposer cell's static round\| for an identical configuration; its sibling map does not include this phase's directories, so `round_table_crosscheck.md` prints "–" | Static spread reported from A's and B's round 0 per primary cell: none 733 9.79, 512 0, 101 0, rule 733 25.61. The none floors max(sd, spread) are unchanged (15.67, 14.53, 2.40); at rule 733 the static spread alone exceeds 18, noted as an observation (that cell has no floor-based verdict) | README §1 (note under the table), §6; `pins.md`; FINDINGS corrections (audit) |
| A8 | minor | partly accepted | **fixed in part, disclosed** | `sweep_tables.md` printed the 16-epoch sd as "within-run sd" and the 733 floor as "14.39 (default order)" alone; "Regenerate every table" was broader than the script | Fixed: `sweep_table.py` `SD_LABEL` and `FLOOR_LABELS` (dated docstring, test `test_sweep_table_sd_and_floor_labels`); tables regenerated: 26 label lines changed in `sweep_tables.md`, `sweep_summary.json` byte-identical, `round_table_crosscheck.md` byte-identical after the K8 re-append; README K9 and K13 closed. §10 now says "Regenerate the generated tables" and lists what no repository script regenerates (`refusal_table.md`, the stdlib readers, the appended cross-check section, `CHECK.md`). Not done: a repository script for `refusal_table.md` (open, K7). The `proposer.md` / `allocation_rule.md` entries are the coordinator's | `phases/phase7_dgm_self_modifying/sweep_table.py`, `tests/test_self_modifier.py`, `results/sweep_tables.md`; README §9 K9, K13, §10 |
| A9 | note | accepted | **fixed** | $5.244837 + 4 × $0.50 + $0.45 = $7.694837; the $0.50 per Sonnet cell is PLAN §5's planning upper, and B / B-4o usage is unlogged | README §11: "a conditional envelope under the PLAN's assumed writer-cost upper estimates, not a verified billing maximum" | README §11 |
| A10 | note | accepted | **fixed** | Each primary A archive holds six entries (r0–r5); at most five are candidates at a selection | Limit 6: "five adaptive rounds (at most five candidate entries at a selection step, six evaluated entries with the root at the end)" | README §8 limit 6 |

## The auditor's outstanding checks (its list), and where each now stands

| check | done in this response? | result |
|---|---|---|
| Resolve completion validity | **yes** | Nested rule in code and in Phase 1 PLAN; tables apply it; sensitivity reported (A1) |
| Independently reproduce every O1–O4 value | partly | Not re-derived here from the `.eval` files. Already done twice before: the stdlib reader of FINDINGS 2026-10-22 / 2026-10-23 (0 disagreements) and the independent SOP check's own reader (`audits/sop_check_independent.md` spot-check rows 5–13). P-ext recomputed here from `final_owner` in all 12 cells: equal |
| Verify P-ext and reference allocations against problem generation | partly | References as stored in the cell headers; the mechanism check compared the store's reference with `build_problem` (CHECK.md §3(e)); P-ext recomputed here (above) |
| Full-precision means and sds from all 64 baseline epochs | **yes** (earlier today) | 16-epoch sd 13.44 / 15.67 / 14.53 / 2.40, pooled within-run 12.99 / 14.53 / 14.72 / 2.56 (`pins.md`) |
| Costs from usage | **yes** (earlier today) | Exact sums from all 74 `.eval` logs and `rounds.jsonl`: $5.244837 measured (`pins.md`) |
| Actual B / B-4o billing or a hard bound | no | Writer usage is not logged; provider billing is not available to an agent. A9 wording |
| Archive weights and seeded draws | **yes** | All 30 selections recomputed with an independent implementation of PLAN §1.3: 0 mismatches in eligible set, weights, draw, parent |
| Refusals over every raw completion | **yes** | `proposer._REFUSAL` over all 63 logged writer completions (A 23, B 20, A-lin 10, B-4o 10): 0 hits, 0 empty |
| No hidden fallback or omitted writer call | partly | Call counts per cell from the logs equal `refusal_table.md` (6/6/5/6 for A, 5 for every other cell); `archive.jsonl` `fallback` false in every entry (the independent check, rounds and archives) |
| Prompt delivery and sent settings | no (not re-done) | Checked by hand in the mechanism check (CHECK.md (c), (d)) and for the sweep in FINDINGS; Inspect keeps five raw requests per log (limit 12) |
| Reproduce the 156/156 mechanism check | no | `bycheck.py` is kept beside the check logs and can be re-run; not re-run here |
| The 72-line second-reader cross-check | no (unchanged) | `round_table_crosscheck.md` byte-identical to its pre-change copy |
| Independent-reader claims | partly | The readers were not preserved (K7); this response's own selection, P-ext and refusal recomputations stand in for part of them |
| Tests and the mock end-to-end | partly | `tests/test_self_modifier.py -k sweep_table` 4 passed (with the new test); `tests/test_e2e_self_modifier.py` 3 passed. The two driver tests were not run by this task: they call `check.main()` / `sweep.main()` in process without `--dry-run` (tripwired); their counts are the independent checker's |
| Installed dependencies unmodified | no (not re-done) | The independent SOP check verified the RECORD hashes of `orbit-1.0.3` and `inspect_ai-0.3.263` |
| Pre-registration chronology | partly | `dffe520` contents and time read from git (PLAN §1–§11 before the first paid log); the uncommitted dated lines cannot be timed (A6) |

## Checks of this response

- `uv run --frozen pytest -q tests/test_self_modifier.py -k sweep_table` → 4 passed; `uv run --frozen pytest -q
  tests/test_e2e_self_modifier.py` → 3 passed.
- `uv run --frozen python phases/phase7_dgm_self_modifying/sweep_table.py`, then diff against the backups: `sweep_tables.md`
  26 lines differ, all clean-line sd labels and the two 733 floor labels; `sweep_summary.json` `cmp` identical; the
  regenerated first 306 lines of `round_table_crosscheck.md` equal the old ones, and after re-appending the old lines 307–762
  the file is `cmp` identical.
- `audits/sop_check.md` re-run note of 2026-10-23 (after this audit): 15 PASS, 0 FAIL.

## Left for the owner

1. **SOP §9 and the not-matched predictions (D12, A6):** whether PLAN §3.5's "record and continue" waived the council for
   predictions 1, 2, 5 and 7, or a council is owed; a dated ruling in the PLAN and the STATUS decisions log.
2. **A repository generator for `refusal_table.md`** (A8, K7), and keeping the stdlib readers, if the owner wants them
   reproducible.
3. **The in-process driver tests** call `check.main()` / `sweep.main()` without `--dry-run`, behind tripwires: whether that
   is acceptable under the owner's "only with --dry-run" rule.
