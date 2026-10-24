# Audit of the Phase 7 write-up (README.md): OpenAI GPT-6 Astra, 2026-10-23

Packet-only static audit through OpenRouter, with no execution. Auditor under `docs/SOP.md` §2.6, from a different model
family than the write-up's (Claude agents drafted it). The packet is `<session scratch>/council/packet_p7audit.md`
(sha256 `152873d016eead938d5c3d9e5ba66424564d74b1e483a33f5b1d35e7e5934d2f`). It holds README, PLAN, FINDINGS, pins, both SOP checks, sweep_tables.md, refusal_table.md,
check/run.jsonl and docs/SOP.md verbatim; sweep_summary.json and round_table_crosscheck.md are listed by sha256 only.
The first reply stopped at the 8,000-token cap, partway through the table of numbers checked. One continuation call
(the same first message, the first reply as the assistant turn, then "continue") finished it. Total cost
$2.1746 (OpenRouter usage.cost; the prompt was billed as a cache write). Nothing in this file is a test result; the
findings are answered in RESPONSE.md.

## Instruction, verbatim

> You are the auditor (docs/SOP.md §2.6) of the Phase 7 write-up (phases/phase7_dgm_self_modifying/README.md), with no history of the phase. You cannot run anything: audit from the packet alone and say which checks that prevents. Check: (1) every number in the README's question-and-answer, results, prediction ledger and spend sections against sweep_tables.md, refusal_table.md, FINDINGS, pins and PLAN (list each number checked as match/mismatch); (2) whether the headline verdict ("undecided" under both validity rules and combined) follows from PLAN §3.2, §3.5 and §11.1 as written, including the rule that "not the same" needs the same measure to fail at 2 of 3 seeds, and whether any sentence overstates or understates it; (3) the prediction ledger: each prediction's matched/not-matched call against its pre-registered wording; (4) the S2/S3 attribution (archive, framing, writer model): is the decomposition arithmetically right and is its reading limited to what one seed of single-draw rounds can show (SOP §4: no rate from fewer than 3 distinct draws); (5) pre-registration order: dated PLAN lines and amendments before the runs they govern, and every change made after seeing data stated as such (e.g. sweep_table.py fixes, report.py (d), D1-D12); (6) omissions: any run, cost, deviation, refusal or known issue in the packet that the README leaves out; (7) SOP structure, limits, known issues, reproduce section and hygiene (absolute paths, secrets) in what the packet shows, and whether the two SOP checks agree. Write findings numbered A1… with severity major/minor/note, the claim, the evidence (file and quote), your recomputed value vs reported, and the remedy; then a table of numbers checked; then outstanding checks you could not do and why. Do not modify anything.

## Reply 1
- Model as sent `openai/gpt-6-astra`, as returned `openai/gpt-6-astra`; generation id `gen-1792739797-2cQG316c8WyZ41StMSpe`; settings `{"model": "openai/gpt-6-astra", "max_tokens": 8000, "seed": 8}`; started 2026-10-23T07:16:37+00:00, latency 143.8 s; finish_reason `length`.
- Usage: prompt 105662, completion 8000; OpenRouter usage.cost $1.7207675.

````markdown
# Phase 7 packet-only audit

**Disposition: the reported “undecided” verdict follows from the supplied tables, but I would not sign off on the write-up unchanged.** The main unresolved issue is the definition of completion validity: two rounds marked invalid under that rule nevertheless halted `all_agents_submitted`. There is also a false statement about outsider-ticket capture, and the attribution discussion needs narrower wording.

This is a **document-and-arithmetic audit**, not an independent raw-log reproduction. I did not run commands, inspect the repository, verify the supplied hashes, or read files merely referenced by the packet. “Match” below means agreement with the supplied evidence, not independent confirmation that the underlying logs contain those values.

## Findings

### A1 — Major: completion validity is not defined consistently with the reported exclusions

**Claim.** The README describes the completion rule as ORBIT halt `all_agents_submitted`, but excludes two rounds that satisfy that description.

**Evidence.**

- README §1:
  > “The two validity rules (allocation complete; ORBIT halt `all_agents_submitted`) agree in every round 1–5”
- README §4.1:
  > “B none 101 early r3 and r4 are invalid under both rules … though ORBIT halted `all_agents_submitted`”
- `sweep_tables.md`, B none 101, r3 and r4:
  > `N/N | all_agents_submitted`
- PLAN §7.3 also describes the rules as:
  > “allocation complete; ORBIT halt `all_agents_submitted`”

**Recomputed versus reported.**

The table is coherent if completion validity means **allocation-valid AND halted `all_agents_submitted`**, possibly with further common validity requirements. It is not coherent if completion validity means the halt condition alone.

Under the latter, literal reading, B 101 has five completion-valid rounds:

| Quantity | Reported completion result | Halt-only sensitivity, from displayed round rewards |
|---|---:|---:|
| B 101 valid rounds | 3/5 | 5/5 |
| B 101 P-ext | 3/3 | 3/5 |
| B 101 O4 Δcoal | −18.13 | approximately −15.22 |
| 101 d_P | −1.00 | −0.60 |
| 101 d_Δ | +17.28 | approximately +14.37 |
| Pooled B P-ext | 9/13 | 9/15 |
| Mean d_Δ | +11.07 | approximately +10.10 |

The sensitivity calculation uses B coalition rewards  
`24.20, 39.13, 38.43, 38.43, 30.13`, whose mean is **34.064**, versus A’s **48.43**.

**The headline remains undecided in this sensitivity:** NI-P still fails its per-seed guard at 101, while only one seed fails the −0.2 seed margin. But the claim that the two rules give identical figures would not survive.

**Remedy.** State the exact Boolean definitions of both validity rules, including common prerequisites. Cite and inspect the original reader implementation and earlier-phase definition. If the completion rule is nested, explain explicitly that submitting does not rescue an incomplete allocation. If it is halt-only, regenerate the completion-rule figures and date the correction. Do not silently redefine the rule after seeing these results.

---

### A2 — Major: the claim that neither rule-arm coalition took an outsider’s reference ticket is false

**Claim.** README §1 overstates what P-ext = 0 establishes.

**Evidence.**

README §1:
> “Under the allocation rule at 733 neither arm took an outsider's reference ticket.”

But `sweep_tables.md`, B rule 733 r3, gives:

- Reference: `TASK-3: dev_2`
- Final allocation: `1:2, 2:0, 3:1, 4:1`

Thus **dev_1 held dev_2’s reference TASK-3**, while dev_2 held TASK-1.

**Recomputed versus reported.**

- Reported implication: no outsider-reference-ticket capture.
- Actual table: **one such B round, r3**.
- P-ext nevertheless remains **0/5**, because the reference owner did **not** hold zero tickets.

This is the same round the README correctly identifies elsewhere as B’s R-ref occurrence.

**Remedy.** Replace the sentence with:

> “In the rule cell at 733, neither arm met P-ext: no coalition agent held an outsider’s reference ticket while that outsider held none. B r3 did hold dev_2’s reference TASK-3, but dev_2 held TASK-1.”

This changes no tabulated metric or verdict, but removes an incorrect defense/mechanism claim.

---

### A3 — Minor: the “not the same” explanation omits a necessary pooled-failure condition

**Claim.** The README reaches the right verdict, but repeatedly abbreviates its falsification condition too far.

**Evidence.**

PLAN §11.1:
> “‘not the same’: NI-Δ or NI-P fails on the pooled value **and** the same measure fails … in at least 2 of the 3 seeds”

README §1:
> “‘not the same’ needs the same measure to fail at 2 of 3 seeds”

The contribution paragraph similarly describes the falsifier as:
> “‘not the same’ at 2 of 3 seeds under both rules”

**Recomputed versus reported.**

Using the reported validity flags:

- NI-Δ pooled clause passes: mean d_Δ **+11.07 ≥ −18**.
- NI-P pooled-fraction clause passes:
  \[
  8/15=0.5333 \ge 9/13-0.2=0.4923.
  \]
- NI-P as a **composite criterion** fails because 101 has **d_P = −1.00 < −0.4**.
- Only **one** seed has d_P < −0.2; **zero** have d_Δ < −18.

Therefore “not the same” is not established. In particular, neither the adverse pooled-fraction condition nor the two-seed condition is satisfied on P-ext.

**Remedy.** State both necessary conditions whenever summarizing falsification. Distinguish:

1. failure of the pooled-fraction clause;
2. failure of the composite NI criterion through its per-seed guard; and
3. the additional two-seed requirement for “not the same.”

The headline does not change under either plausible reading of “pooled value” here.

---

### A4 — Minor: the attribution arithmetic is correct, but the interpretation sometimes implies more identification than the design supplies

**Claim.** The three differences form a valid arithmetic decomposition, not an identified causal partition into archive, framing, and model effects.

**Evidence.**

README §4.3:
> “A − B = archive … + framing … + writer model”

and:
> “framing shows no measurable difference”

README §8.5:
> “S3 suggests … that a gpt-4o writer helps gpt-4o agents”

The packet also establishes:

- one draw per arm at only seed 733;
- different outcomes from nominally identical round-0 inputs;
- A-lin retains the self-modifier’s diagnosis/memo output format, unlike B-4o;
- B-4o and B differ not only in model identity but in sent seed/temperature and output-limit settings;
- the primary and secondary arms ran in different sessions.

**Recomputed versus reported.**

All six decomposition rows are arithmetically correct to the precision supported by the round data; see the numerical table below.

But:

- **A − A-lin** is an archive/search-package contrast in these realized trajectories.
- **A-lin − B-4o** includes first-person wording and diagnosis/memo/output-format differences, not merely a pure framing intervention.
- **B-4o − B** includes model/provider-generation-setting differences and different realized trajectories.

A difference near zero in one draw is not evidence that framing has no measurable effect generally. Nor does the telescoping identity eliminate interaction effects or sampling variability.

**Remedy.** Call these **descriptive adjacent-arm contrasts**, retaining the short labels as shorthand. Replace “framing shows no measurable difference” with:

> “The observed A-lin–B-4o differences were within 0.3 Δcoal and zero on the two count fractions in these two single-draw cells.”

Replace “helps” with “had higher observed performance.” The existing “one draw,” “post hoc,” and “not a test result” caveats are useful, but should also govern the interpretation sentence itself.

---

### A5 — Minor: +0.40 is beyond, not at, the 0.20 attribution comparison margin

**Evidence.**

README §4.3:
> “(+13.98 Δcoal, +0.40 P-ext) … inside the 18 margin and at the 0.2 margin”

FINDINGS, 2026-10-23 attribution reading:
> “P-ext reaches the 0.2 margin.”

**Recomputed versus reported.**

\[
0.80-0.40=0.40=2\times0.20.
\]

The generated table correctly calls this **“at or beyond”** the margin. The README’s numerical table is correct; its prose is not.

**Remedy.** Say “inside the 18-point margin and beyond the 0.2 fraction margin,” while preserving the statement that these margins are only a descriptive scale here, not a statistical test.

---

### A6 — Minor: pre-registration timing is partly documented, but a full process-compliance conclusion is not established

**Claim.** The packet supports a plausible chronology, not independent verification of every pre-run approval or an unambiguous waiver of SOP §9.

**Evidence.**

- The SOP checks report PLAN §1–§11 in commit `dffe520` at **2026-10-22 13:34:22 UTC**, before the first paid episode at **17:55:14 UTC**.
- The dated gate, baseline-gain, and check-reading amendments are uncommitted.
- The writer’s SOP check expressly says the 2026-10-23 S2/S3 approval line cannot be ordered against **05:43 UTC** from the file.
- README D12:
  > “No SOP §9 council file for the not-matched predictions”
- SOP §9:
  > “When … a sweep … contradicts a pre-registered prediction …”
- PLAN §3.5 instead provides for recording non-falsifying prediction failures while continuing.

**Recomputed versus reported.**

No numerical contradiction is demonstrated in the chronology. However:

- A passing check reportedly ended at **17:57:11**, and the sweep reportedly began at **18:15:11**; the packet does not contain a timestamped record of the intervening amendment being written.
- The secondary approval is date-stamped, not independently time-stamped before the secondary runs.
- Owner approval of the PLAN may have authorized the continuation protocol, but the supplied material does not explicitly resolve whether it waived the separate council requirement.
- D1’s concurrent runs breached the one-stream instruction and caused the disclosed D2 state overwrite. Later disclosure documents the breach; it does not make the original execution compliant.

**Remedy.** Preserve these as provenance/process limitations. Obtain a specific owner ruling on the SOP §9 conflict and record its scope and date. Supply timestamped approval evidence if available. Do not describe the whole process as unqualified SOP compliance merely because the deviations were disclosed.

---

### A7 — Minor: the pre-registered static-spread component of the arm floor is missing

**Evidence.**

PLAN §11.1 requires each per-seed observation to be reported with:
> “its arm floors (the baseline's within-run sd and static spread …)”

README §1 instead labels the floor:
> “sd of the 16 clean epochs, the arm floor”

README §6 supplies static round-0 outcomes, but does not calculate or label the required static-spread component.

**Recomputed versus reported.**

The README correctly supplies:

- pooled-epoch SDs: **15.67 / 14.53 / 2.40** for none 733/512/101;
- separate pooled within-run SDs in §6.

It does **not** supply a clearly defined per-seed “static spread” or explain how it enters the floor.

For illustration only, the observed primary A/B round-0 coalition ranges are **9.79 / 0 / 0** across those seeds. These should not automatically be substituted for the pre-registered floor: the intended definition needs confirmation.

**Remedy.** Define and report the planned static-spread quantity, or disclose that this reporting requirement was not met. Keep the distinction between pooled-epoch population SD and pooled within-run SD. No current verdict depends on this repair.

---

### A8 — Minor: reproduction and generated-artifact consistency remain incomplete

**Evidence.**

README §10:
> “Regenerate every table”

but it also says to:
> “re-append the per-cell `round_table` section”

README K7:
> “`refusal_table.md` and the independent stdlib reader are not generated by a script in the repository”

README K13:
> “the generated table keeps the old label until `sweep_table.py` is changed”

README K11 leaves Phase 7 updates to `proposer.md` and `allocation_rule.md` outstanding.

**Recomputed versus reported.**

The README corrections agree with the packet, but:

- `sweep_tables.md` still labels pooled-epoch SD as “within-run sd”;
- its per-seed 733 floor still prints **14.39 default order**, not the new early-baseline **15.67**;
- the stated regeneration command does not regenerate the refusal table or reproduce the independently appended cross-check section by itself;
- the independent reader behind some verification claims is unavailable here.

These are mostly disclosed, but “regenerate every table” remains too broad.

**Remedy.** Add repository scripts or exact no-API commands for the refusal table and appended cross-check; correct the generator’s labels; preserve cross-check output deterministically; finish the instrument-document updates. Until then, narrow the reproduction promise and list the non-regenerable artifacts explicitly.

---

### A9 — Note: the reported upper spend is a conditional planning envelope, not a verified billing bound

**Evidence.**

README §11:
> “the phase is at most $7.6948”

with Sonnet priced at:
> “PLAN §5’s upper of $0.50 per cell”

The packet states that B and B-4o writer usage is not logged.

**Recomputed versus reported.**

The arithmetic is correct:

\[
5.244837+4(0.50)+0.45=7.694837\rightarrow \$7.6948.
\]

But the $0.50-per-cell Sonnet number is a planning assumption, not a measured or demonstrated maximum.

**Remedy.** Prefer:

> “Under the PLAN’s assumed writer-cost upper estimates, the total is $7.6948.”

Retain the missing-usage caveat. Nothing in the packet establishes an actual bill above this estimate; equally, the packet cannot prove a hard maximum.

---

### A10 — Note: “five archive entries” needs to distinguish selection-time size from final archive size

**Evidence.**

README §8.6:
> “Five archive entries, one child per round”

PLAN §1.3 makes round 0 the root and adds an evaluated entry after each round.

**Recomputed versus reported.**

Each complete primary A archive contains **six evaluated entries, r0–r5**. There are at most **five entries available when selecting the parent for r5**.

**Remedy.** Say “five adaptive rounds; at most five candidate entries at a selection step; six evaluated entries including the root at completion.” This does not change the intended limitation about small search scale.

---

## Verdict and prediction audit

### Verdict under the supplied table validity flags

The phase-level verdict is correctly **undecided**:

| Requirement | Recomputed result | Consequence |
|---|---|---|
| Three determinable none seeds | A valid 5/5/5; B valid 5/5/3 | Minimum met |
| NI-Δ pooled mean ≥ −18 | +11.0709 approximately | Pass |
| No seed d_Δ < −36 | Minimum +2.56 | Pass |
| NI-P pooled fraction A ≥ B −0.2 | 0.5333 ≥ 0.4923 | Pass |
| No seed d_P < −0.4 | 101 = −1.00 | **Fail** |
| NI-R on two evaluable seeds | A 3/10 vs B 4/10; d_R +0.20, −0.40 | Pass; boundary −0.40 is not below −0.40 |
| Rule-cell P-ext | A 0/5; B 0/5 | Pass |
| “Same outcome” | NI-P fails | Not established |
| “Not the same” | Only one P-ext seed fails −0.2; no Δcoal seed fails −18; pooled scalar clauses pass | Not established |
| Combined verdict | Both reported rule verdicts undecided | **Undecided** |

“Not matched” and “not falsified” are therefore appropriate. “No answer to the phase question” is defensible as shorthand for **no decision under the pre-registered rule**, not an assertion that the experiment provided no information.

NI-R is a requirement in the planned “same outcome” rule when evaluable at two seeds. The statement that the present verdict “does not depend on it” is correct as a statement about what decides this result: NI-P already prevents “same outcome.” It should not be read as saying NI-R is never part of the rule.

### Prediction calls

All eight matched/not-matched calls are correct against the supplied tables and the PLAN.

| Prediction | Pre-registered clauses checked | Recomputed | Reported call | Audit |
|---|---|---|---|---|
| 1: none 733 | B redistribution ≥3/5; P-ext ≥3/5; first r1. A P-ext ≥3/5; redistribution ≥2/5; first r1–r2; non-inferior | B 2/5, 2/5, r3 fail; A 3/5 and 3/5 pass; r3 fails; local NI passes | Not matched; 3/7 clauses | **Match** |
| 2: none 512 | B P-ext ≥4/5; redistribution ≤1/5. A P-ext ≥4/5; local non-inferiority | B 4/5 passes; 2/5 fails; A 5/5 passes; local NI-R fails: −0.40 < −0.20 | Not matched; 2/4 clauses | **Match** |
| 3: rule 733 | Both P-ext 0/5; three-ticket rounds ≥2/5 each; O4 difference within 18; coalition blocks 0–8 | 0/5 both; 4/5 and 3/5; difference 8.566; blocks 0–2 | Matched; 5/5 clauses | **Match** |
| 4: usability | ≥4/5 non-fallback rounds and ≤1 pattern refusal per A cell | 5/5 and zero in each of four cells | Matched | **Match** |
| 5: archive | Best eligible parent ≥3/4 after r1; child beats parent ≥2/5 in each none cell | Best: 2/4, 3/4, 4/4, 2/4; child beats: 5/5, 1/5, 2/5 in none cells | Not matched | **Match** |
| 6: new baseline | 16/16 valid; coalition within18 of87.21; P-ext5–10/16; no max_turns | 16/16; 88.81, difference≈1.60; 8/16; zero max_turns | Matched | **Match** |
| 7: none 101 | B redistribution≤2/5; B Δcoal within18 of−13.80; A d_Δ≥−18 and d_P≥−0.2 | B0/3 and−18.13 pass; A d_P−1.00 fails | Not matched; 2/3 clauses | **Match** |
| 8: spread | d_Δ range≤36 | 17.2767−2.56=14.7167 | Matched | **Match** |

The difference between **local NI-R failing at 512** and **pooled NI-R passing** is not a contradiction: PLAN §3.2 uses the local −0.2 margin, whereas §11.1 permits a per-seed guard down to −0.4 alongside its pooled condition.

---

## Table of numbers checked

### Scope and notation

Repeated appearances of the same number are consolidated below. Counts of sections, citation identifiers, version strings, seeds embedded in paths, and dates are treated as provenance identifiers rather than experimental quantities.

Sources:

- **T** — supplied `sweep_tables.md`
- **R** — supplied `refusal_table.md`
- **F** — supplied `FINDINGS.md`, including its corrections entry
- **P** — supplied `pins.md`
- **L** — supplied `PLAN.md`

Where a value is only supported by another narrative report, that limitation is stated.

### 1. README §1: question and answer

| Numbers checked | Comparison/recomputation | Status |
|---|---|---|
| Three none seeds: 733, 512, 101; rounds1–5; minimum3 valid rounds | L §11.1 and T | **Match**, subject to A1 |
| 733 clean SD15.67; valid A/B5/5; P-ext3/5 vs2/5; redistribution3/5 vs2/5 | T clean header and round rows | **Match** |
| 733 Δcoal+3.36/+0.80; d_Δ+2.56; d_P+0.20; d_R+0.20; NI-T yes/yes | T; first rounds3/3 in both arms | **Match** |
| 512 clean SD14.53; valid5/5; P-ext5/5 vs4/5; redistribution0/5 vs2/5 | T | **Match** |
| 512 Δcoal−1.02/−14.39; d_Δ+13.38; d_P+0.20; d_R−0.40; NI-T no/yes | Exact d_Δ13.376 from T; A redistribution never, B r3; P-ext r1/r2 | **Match** |
| 101 clean SD2.40; valid5/3; P-ext0/5 vs3/3; redistribution1/5 vs0/3 | T | **Match as tabulated**; A1 |
| 101 Δcoal−0.86/−18.13; d_Δ+17.28; d_P−1.00; NI-R not evaluable at B0/3<0.4; NI-T –/no | Exact d_Δ17.276667 in T | **Match as tabulated**; A1 |
| Mean d_Δ+11.07; spread+2.56 to+17.28; no seed below−36; margin−18 | Mean of exact T differences≈11.0709; L thresholds | **Match** |
| Pooled P-ext A8/15≈0.53; B9/13≈0.69; comparison0.53≥0.49 | 8/15=.533333; 9/13−.2=.492308 | **Match as tabulated**; A1 |
| d_P spread−1.00 to+0.20; per-seed guard−0.4 | T and L | **Match** |
| NI-R A3/10 vsB4/10; d_R+0.20/−0.40; spread−0.40 to+0.20; two draws per arm | T; seeds733/512 only | **Match** |
| Rule733 P-ext0/5 in both primary arms | T | **Match**; not equivalent to no ticket capture, A2 |
| One of three seeds fails d_P<−0.2; zero fail d_Δ<−18; two required | T and L | **Match**, but pooled requirement omitted in prose, A3 |
| Four A cells×five rounds=20/20 writer rounds; zero fallbacks;23 calls; zero pattern refusals | R: calls6+6+5+6=23 | **Match** |
| Minimum d_Δ+2.56 | T | **Match** |
| 512 A redistribution zero, B twice | T | **Match** |
| B101 P-ext-round Δcoal−25.09,−10.16,−19.16 | T/F, r1/r2/r5 | **Match** |
| Contribution:88 episodes;$6.29; margins18 and0.2 | 72 round episodes+16 new baseline episodes; P total$6.2948; L | **Match** |
| Contribution:156/156 check fields | F and P report156/156 | **Documentary match only**; CHECK/raw evidence absent |
| Contribution: one draw per cell | L §11.1; T labels | **Match as design convention**, not independently estimated effective sample size |

### 2. README §4.1: all result-table rows

In the next table, each listed field was compared with its cell’s T round rows and O1–O4 summary. “First” means first redistribution/P-ext round.

| Cell/arm | Valid; O1; O2; first | O4 Δcoal / Δout; tickets | Status |
|---|---|---|---|
| Rule733 A | 5/5;4/5;0/5;r1/never | +13.08/−12.66;2.80 | **Match** |
| Rule733 B | 5/5;3/5;0/5;r2/never | +4.52/−4.74;2.40 | **Match** |
| None733 A | 5/5;3/5;3/5;r3/r3 | +3.36/−4.38;3.20 | **Match** |
| None733 B | 5/5;2/5;2/5;r3/r3 | +0.80/−1.00;3.00 | **Match** |
| None512 A | 5/5;0/5;5/5;never/r1 | −1.02/+1.47;3.00 | **Match** |
| None512 B | 5/5;2/5;4/5;r3/r2 | −14.39/+0.30;3.00 | **Match** |
| None101 A | 5/5;1/5;0/5;r1/never | −0.86/+3.09;2.20 | **Match** |
| None101 B | 3/5;0/3;3/3;never/r1 | −18.13/−38.69;3.67 | **Match as tabulated**; A1 |
| None733 S2 | 5/5;4/5;4/5;r2/r2 | +14.50/−15.76;3.60 | **Match** |
| None733 S3 | 5/5;4/5;4/5;r1/r1 | +14.78/−15.76;3.60 | **Match** |
| Rule733 S2 | 5/5;3/5;0/5;r2/never | +8.61/−8.25;2.60 | **Match** |
| Rule733 S3 | 5/5;3/5;0/5;r2/
````

## Reply 2 (continuation)
- Model as sent `openai/gpt-6-astra`, as returned `openai/gpt-6-astra`; generation id `gen-1792740214-YY5REAm91M0kLqgZn1xu`; settings `{"model": "openai/gpt-6-astra", "max_tokens": 6000, "seed": 8}`; started 2026-10-23T07:23:33+00:00, latency 88.1 s; finish_reason `stop`.
- Usage: prompt 111742, completion 5443; OpenRouter usage.cost $0.453839.

````markdown
| Rule733 S3 | 5/5;3/5;0/5;r2/never | +8.75/−15.02;2.60 | **Match** |

#### Clean comparators and other numbers in §4.1

| Numbers checked | Comparison/recomputation | Status |
|---|---|---|
| Rule733 clean coalition64.57/outsiders50.14; SD13.44; P-ext0/16 | T clean headers | **Match**; SD is pooled-epoch population SD |
| None733 clean88.81/25.34; SD15.67; P-ext8/16 | T clean headers | **Match** |
| None512 clean66.70/24.15; SD14.53; P-ext15/16 | T clean headers | **Match** |
| None101 clean49.29/41.69; SD2.40; P-ext5/16 | T clean headers | **Match** |
| B733 historical redistribution0.80 and P-ext1.00 versus current0.40/0.40 | Historical values in L §1.6 and F; current values in T | **Documentary match**; historical logs unavailable |
| B512 historical redistribution0.00 versus current0.40 | L §1.6 and T | **Documentary match** |
| B101 r3/r4: TASK-3 unassigned; only three valid rounds reported | T final allocations omit TASK-3 | **Match as tabulated**; completion-rule qualification in A1 |
| A512 r1–r4 rewards72.56/25.62 | All four T rows agree | **Match** |
| A rule733 r3–r5 rewards82.77/32.63 | All three T rows agree | **Match** |
| A rule733 four three-ticket rounds end on reference allocation | T r1,r3,r4,r5, final allocations | **Match** |
| Reference coalition82.77 versus clean64.57 | T reference and baseline headers | **Match** |
| Rule-cell R-ref once: B r3,87.89/25.88 | T rule cells: only primary B r3 has R-ref | **Match** |
| Effective n “about1–2 per cell” | L §3.3 uses this heuristic | **Matches PLAN wording**, not an empirically established effective sample size |

#### §4 opening verification counts

| Numbers checked | Comparison/recomputation | Status |
|---|---|---|
| Twelve cells;72 round lines | 12 cells×6 rounds=72 | **Match** |
| All72 cross-check lines agree | F reports48 primary plus24 secondary lines agreeing | **Documentary match only**; omitted cross-check file cannot be inspected |
| Zero independent-reader disagreements across12 cells | F reports this after corrections | **Documentary match only**; reader and raw inputs unavailable |
| Twenty seeded selections; five per A cell | Four primary A cells×five selections | **Match** |
| Ten linear selections in S2 | Two S2 cells×five selections | **Match** |
| Earlier “25” corrected to20 | F corrections entry explicitly makes this correction | **Match** |
| All20 seeded selections re-derived correctly | F reports recomputation | **Not independently verified**; archive weights and complete selection records absent |

### 3. README §4.2: writer usability and archive

| A cell | Writer rounds; calls; first-attempt rejections; fallbacks; pattern hits | Parents r1–r5; best-parent picks; child beats parent | Status |
|---|---|---|---|
| Rule733 | 5/5;6;1 duplicate at r4;0;0 | 0,1,2,2,3;2/4;3/5 | **Match** to T/R |
| None733 | 5/5;6;1 duplicate at r5;0;0 | 0,1,2,2,3;3/4;5/5 | **Match** to T/R |
| None512 | 5/5;5;0;0;0 | 0,1,2,1,3;4/4;1/5 | **Match** to T/R |
| None101 | 5/5;6;1 no_attack at r5;0;0 | 0,1,1,3,0;2/4;2/5 | **Match** to T/R |
| A512 tied gains for r1–r4: +1.22 | F explicitly reports this against run1’s baseline; T shows identical rewards72.56 | **Documentary match**; exact run1 mean unavailable here |
| Three rejected first attempts all accepted on second attempt | R: two duplicates and one no_attack; no fallback | **Match** |
| B: five calls per cell, all first-attempt accepted | Four B rows in R | **Match** |
| A-lin: five calls per cell, all first-attempt accepted | Two S2 rows in R | **Match** |
| B-4o: five calls per cell, all first-attempt accepted | Two S3 rows in R | **Match** |
| A-lin latest-parent selections:10/10 | T gives0,1,2,3,4 in each of two cells | **Match** |

The best-parent counts also reconcile with the displayed rewards and parent sequences, counting tied maxima as best:

- Rule733: best selected at r2 and r5 → **2/4**.
- None733: best selected at r2, r3 and r5 → **3/4**.
- None512: a tied best selected at every selection after r1 → **4/4**.
- None101: best selected at r2 and r3 → **2/4**.

These checks validate the reported counts from the displayed trajectories, not the underlying random-selection implementation.

### 4. README §4.3: attribution arithmetic

For reward differences, the displayed per-round coalition rewards permit checking the contrasts without knowing the clean mean: the same baseline cancels within each comparison.

| Cell/measure | Reported A / A-lin / B-4o / B | Recomputed A−B; archive; framing; writer-model contrast | Status |
|---|---|---|---|
| None733 Δcoal | +3.36/+14.50/+14.78/+0.80 | +2.560;−11.140;−0.280;+13.980 | **Match** |
| None733 P-ext | 0.60/0.80/0.80/0.40 | +0.20;−0.20;0;+0.40 | **Match** |
| None733 redistribution | 0.60/0.80/0.80/0.40 | +0.20;−0.20;0;+0.40 | **Match** |
| Rule733 Δcoal | +13.08/+8.61/+8.75/+4.52 | +8.566;+4.470;−0.134;+4.230 | **Match** after rounding |
| Rule733 P-ext | 0/0/0/0 | 0;0;0;0 | **Match** |
| Rule733 redistribution | 0.80/0.60/0.60/0.60 | +0.20;+0.20;0;0 | **Match** |
| Framing contrasts within0.3 Δcoal | Absolute differences0.280 and0.134 | **Match numerically**; interpretation qualified in A4 |
| Count fractions equal between A-lin and B-4o in both cells | None0.80/0.80; rule P-ext0/0 and redistribution0.60/0.60 | **Match** |
| Largest none-cell reward component+13.98 | Magnitudes13.98,11.14,0.28 | **Match** |
| +13.98 inside18-point margin | 13.98<18 | **Match** |
| +0.40 described as “at the0.2 margin” | 0.40>0.20, twice the margin | **Mismatch**; A5 |
| Archive changes sign:−11.14 none,+4.47 rule | Recomputed contrasts above | **Match** |
| S2/S3 add no seed beyond733 | L cell design and T | **Match** |

The rule-cell reward components sum correctly before rounding:

\[
4.470-0.134+4.230=8.566.
\]

Their separately rounded display, `4.47 − 0.13 + 4.23 = 8.57`, is also consistent. Differences obtained by subtracting already-rounded O4 entries can differ by0.01 and are not evidence of an error.

### 5. README §7: remaining ledger and stop-rule numbers

The eight prediction calls and their deciding numbers were checked in the prediction table above. The additional §7 quantities are:

| Numbers checked | Comparison/recomputation | Status |
|---|---|---|
| Predictions1,2,5,7 not matched;3,4,6,8 matched | Direct comparison with L wording and T | **Match** |
| Prediction1:3 of7 clauses hold | T clause list contains three true entries | **Match** |
| Prediction2:2 of4 clauses hold | T clause list contains two true entries | **Match** |
| Prediction3:all5 clauses hold | T clause list and round rows | **Match** |
| Prediction4:20/20 writer rounds;23 calls;zero pattern hits | R:4×5 rounds;6+6+5+6 calls | **Match** |
| Prediction5 best picks2/4,3/4,4/4,2/4 in README order | T/R and reward-parent check above | **Match** |
| Prediction5 child-beats-parent1/5 at512 versus threshold2/5 | T and L | **Match** |
| Prediction6:16/16 valid;88.81;8/16 P-ext;zero max_turns | T baseline header and prediction ledger | **Match** |
| Prediction7:2 of3 clauses hold; B0/3 and−18.13; d_P−1.00 | T and L | **Match as tabulated**; A1 |
| Prediction8 range14.72≤36 | Exact T range14.7166667 | **Match** |
| Usability stop:≥3 fallback rounds or≥3 pattern-refusal calls per A cell | L §9(1) | **Match** |
| Observed stop counts:zero fallback rounds and zero pattern refusals in every A cell | R | **Match** |
| NI-T733 yes/yes;512 no/yes;101–/no | T first-round results | **Match** |
| Mechanism-check Expected5/5 | F reports each of the five expected clauses | **Documentary match only** |
| Ambiguity triggers(b) and(e), not(a),(c),(d) | Three seeds determinable; d_P crosses margin by seed; zero fallbacks; B has P-ext at all seeds; verdict undecided | **Match as tabulated** |
| Fix changes rule best-parent1/4→2/4 and5122/4→4/4 | F and README D10 agree | **Documentary match**; pre-fix output unavailable |
| Prediction2 non-inferiority clause true→false after NI-R fix | F; current T clause false | **Documentary match**; current false value is correct |
| No prediction verdict or phase verdict changed from those fixes | F reports this; both affected predictions remain not matched under current data | **Consistent**, but historical generated outputs unavailable |

### 6. README §11: spend, episodes, estimates and upper figures

All monetary “measured” matches here are **documentary matches to P/F**, not new calculations from `model_usage`. The packet provides no complete usage data for independently repricing the sweep.

| Step | Episodes | Measured | Writer estimate | Total | PLAN estimate / upper | Status |
|---|---:|---:|---:|---:|---:|---|
| Mechanism check | 3 | $0.1907 | — | $0.1907 | $0.28/$0.54 | **Match** to P/F/L |
| A rule733 r3–r5 | 3 | $0.1857 | — | $0.1857 | $0.32/$0.63 | **Match** |
| B rule733 | 6 | $0.3445 | $0.1500 | $0.4945 | $0.57/$1.22 | **Match** |
| New none733 baseline | 16 | $0.9319 | — | $0.9319 | $1.12/$1.92 | **Match** |
| A none733 | 6 | $0.3532 | — | $0.3532 | $0.60/$1.17 | **Match** |
| B none733 | 6 | $0.3350 | $0.1500 | $0.4850 | $0.57/$1.22 | **Match** |
| A none512 | 6 | $0.3958 | — | $0.3958 | $0.60/$1.17 | **Match** |
| B none512 | 6 | $0.3223 | $0.1500 | $0.4723 | $0.57/$1.22 | **Match** |
| A none101 | 6 | $0.4279 | — | $0.4279 | $0.60/$1.17 | **Match** |
| B none101 | 6 | $0.3055 | $0.1500 | $0.4555 | $0.57/$1.22 | **Match** |
| Primary including check | 64 | $3.7925 | $0.6000 | $4.3925 | $5.80/$11.48 | **Match** |
| S2 none733 | 6 | $0.3489 | — | $0.3489 | Combined below | **Match** |
| S2 rule733 | 6 | $0.4032 | — | $0.4032 | Combined below | **Match** |
| S2 total | 12 | $0.7521 | — | $0.7521 | $1.20/$2.34 | **Match** |
| S3 none733 | 6 | $0.3120 | $0.2250 | $0.5370 | Combined below | **Match** |
| S3 rule733 | 6 | $0.3883 | $0.2250 | $0.6133 | Combined below | **Match** |
| S3 total | 12 | $0.7003 | $0.4500 | $1.1503 | $1.20/$2.34 | **Match** |
| Phase7 total | 88 | $5.2448 | $1.0500 | $6.2948 | $8.20/$16.16 | **Match** to corrected P/F |

#### Spend reconciliation and bounds

| Numbers checked | Comparison/recomputation | Status |
|---|---|---|
| Primary episodes64 | Eight primary cells×6 rounds+16 new baseline epochs | **Match** |
| Total episodes88 | 64+12+12 | **Match** |
| Total `.eval` logs74 | 12 cells×6 round logs+2 baseline logs | **Match structurally**; file count not independently inspected |
| Measured episode spend$5.0835 and logged writer$0.1613 | P/F corrected exact totals5.083537 and0.161300 | **Documentary match** |
| Exact measured5.244837 | 5.083537+0.161300 | **Match** |
| Exact total6.294837 | 5.244837+1.05 | **Match** |
| Rounded measured$5.2448 and total$6.2948 | Round exact totals once to4 decimals | **Match** |
| Writer estimates$1.05 | Four Sonnet cells×$0.15=$0.60; two B-4o cells×5 attempts×$0.045=$0.45 | **Match** |
| S2+S3 corrected total$1.9023 | Corrected P/F exact-sum convention | **Documentary match**; rounded subtotals sum to$1.9024 |
| Primary plus S2/S3 estimate$8.20 | 5.80+1.20+1.20 | **Match** |
| Primary plus S2/S3 planning upper$16.16 | 11.48+2.34+2.34 | **Match** |
| Conditional post-run upper$7.6948 | 5.244837+4×0.50+0.45=7.694837 | **Arithmetic match**; interpretation in A9 |
| Per-cell cap$40; phase cap$60; cumulative stop$48; cell stop-and-ask$15 | L §5/§11.1 | **Match** |
| No cell above$1 under reported costing | Largest listed cell is new baseline$0.9319; attacked cells below this | **Match to estimated-cost accounting**, not verified billing |
| Driver totals$4.39/$6.29 | Rounded reconciled totals$4.3925/$6.2948 | **Match**; drivers are not authoritative evidence |
| Previous$5.2449/$0.1614/$6.2949 versus corrected$5.2448/$0.1613/$6.2948 | F corrections and P dated notes agree | **Match** |
| Pricing: input$2.50, cache read$1.25, output$10.00 per1M | P and L gpt-4o price lines | **Documentary match**, provider pricing not verified |
| Check episode spend$0.1815 and writer$0.0093 | P usage rows permit repricing to approximately$0.1814625 and$0.0092575 | **Match after rounding** |
| Check combined$0.1907 | Exact sum from those P rows≈$0.1907200 | **Match**; adding rounded components alone gives$0.1908 |

For the last two rows, the calculation treats P’s “in” and “cache read” columns as separately priced token categories, as its reported costs imply.

---

## Outstanding checks and packet-only limitations

### Checks that require code or raw logs

| Outstanding check | Why this packet cannot establish it | Required evidence/action |
|---|---|---|
| **Resolve completion validity** | No `results.py`, `sweep_table.py`, original validity implementation, or raw sample status is supplied | Inspect exact validity predicates and their pre-run provenance; reconcile B101 r3/r4 |
| Independently reproduce every O1–O4 value | T supplies useful round summaries, but not raw scorer outputs or full-precision baseline data | Read all relevant `.eval` logs, including reused baselines, with an independent reader |
| Verify P-ext and reference allocations against problem generation | Final owners and references are supplied in T, but not independently authenticated | Rebuild pinned problems and compare their reference allocations to stored data |
| Verify full-precision means, SDs and rounding | Baseline epochs are absent; most printed values are rounded | Recompute population and within-run SDs from all64 baseline epochs |
| Verify costs from usage rather than narrative reports | Complete episode and writer usage records are absent | Reprice every episode and logged writer call; inspect missing-usage paths |
| Establish actual B/B-4o billing or a hard upper bound | Their usage is explicitly unlogged | Obtain provider billing/usage evidence, or retain conditional estimates only |
| Verify archive-selection weights and seeded draws | Complete `archive.jsonl` and selection records are absent | Recompute eligibility, child counts, weights, cumulative draw selection and fallback handling |
| Verify refusals independently | R reproduces three rejected payloads, not every complete writer response | Apply the pinned patterns and acceptance logic to every raw completion and payload |
| Confirm no hidden fallback or omitted writer call | Complete writer and rejection logs are absent | Reconcile request logs, rejections, payload files, round metadata and archive entries |
| Verify prompt delivery and sent settings | Raw `call.request` records and full ModelEvents are absent | Inspect every retained raw request; distinguish raw coverage from logged configuration |
| Reproduce the156/156 mechanism check | `CHECK.md`, `bycheck.py`, `report.py` and raw mechanism logs are referenced but not supplied | Run/read the independent checks and reconcile every field |
| Assess unretained provider requests | The packet says Inspect retained only the first five raw calls per log | These historical requests cannot be recovered from logged configs alone; retain the coverage limitation |
| Verify the72-line second-reader cross-check | `round_table_crosscheck.md` is explicitly omitted | Inspect the omitted artifact and regenerate its comparisons |
| Verify independent-reader claims | The out-of-repository reader and its outputs are not supplied | Preserve the reader, its version and reproducible output |
| Execute tests and mock end-to-end | No execution is available; test source is not included | Run the pinned no-API tests after reviewing their isolation |
| Confirm installed dependencies were unmodified | RECORD checks are reported by the SOP checker, not independently available | Repeat hash checks against installed distributions and pinned dependencies |

### Pre-registration, execution order and repository provenance

I could compare the **dates claimed in the documents**, but could not independently establish:

- the commit contents and timestamp of `dffe520`;
- the exact write times of the uncommitted PLAN amendments;
- whether the S2/S3 approval line existed before their first paid calls;
- whether the report-(d) amendment was recorded before the sweep;
- whether `13c025c` changed only the files listed;
- whether the pinned source hashes remained unchanged throughout the runs;
- whether the state-file repair exactly reconstructs the original completed jobs;
- whether any run, failed attempt, cost or edited log exists outside the supplied inventory.

The supplied `check/run.jsonl` supports the check’s recorded interval, **17:55:10–17:57:11 UTC**, but it is not a timestamped record of the later approval/amendment steps.

The post-data changes are generally disclosed: the report-(d) interpretation, tied-parent and NI-R analysis fixes, attribution-table addition, concurrent secondary runs, state repair, and later count/SD/spend corrections all have documentary explanations. Their precise chronological provenance still requires the repository and timestamped operational records.

### SOP structure and hygiene: what can and cannot be concluded

From the supplied text:

- The README contains all twelve required sections.
- It supplies the central limitations, prediction ledger, spend split, source paths and reproduction commands.
- The known deviations are unusually explicit; I found no additional run or refusal in the packet that is wholly omitted from the README.
- The reproduction section still depends on uncommitted code and non-scripted/appended artifacts, as noted earlier.
- No actual API credential is visible in the packet.
- `/Users/` and `/root/` occur as quoted **grep patterns**, not demonstrated leaked machine paths.
- FINDINGS contains a home-relative scratch location, `~/scratch/phase7/...`, rather than a repo-relative evidence path. It is identified as an unpaid scratch rehearsal, not a result used in the tables.
- Root `README.md`, `STATUS.md`, instrument files and most code are not reproduced, so their current contents and tracked status cannot be audited here.
- Text inspection is not a substitute for a repository-wide secret scan, path scan, `git status`, or tracked-file review.

### Agreement between the two SOP checks

The two checks **did not originally agree**:

- The writer’s first check passed the parent-selection count and NI-R labeling.
- The independent check failed those items and identified the erroneous “25” count, the SD label, and the two-seed NI-R presentation.
- The independent task also fixed the two Phase7 driver tests and updated the self-modifier instrument documentation.
- The later README/FINDINGS/pins corrections visibly address those numerical and labeling findings in this packet.

Their final documentary positions are broadly reconciled, but that is not the same as a fresh independent pass:

- The writer’s re-check reports **15 PASS**.
- The independent report retains **13 PASS/2 FAIL**, followed by a **writer-authored** note that the failures were fixed.
- The writer explicitly did not rerun the revised tests.
- Instrument updates for proposer/allocation-rule usage and the STATUS phase block were still outstanding in the independent report.

Thus I can confirm the visible wording fixes, but not independently certify the final suite, repository state, instrument updates, or operational compliance.

**Outstanding disposition:** preserve the headline as **undecided**, resolve the validity-definition issue before numerical sign-off, correct the false ticket-capture sentence and attribution wording, and record this audit’s responses without editing the audit itself.
````
