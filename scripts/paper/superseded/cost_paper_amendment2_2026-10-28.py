"""Cost of docs/paper/PLAN.md with Amendment (1) of 2026-10-28 (leakage ladder L0-L4, mitigations M1-M4), per stage and
provider. Prices: control_loop/spend.py, checked in docs/prices_verified_2026-10-21.md; council models from OpenRouter's
/api/v1/models (read 2026-10-28); CPU pod from RunPod list-cpu-types (read 2026-10-28: cpu3c $0.03 per vCPU-hour).
Token use per unit is an upper estimate: cache reads priced at full input. Measured all-in cost per ORBIT episode in
earlier phases: Phase 3 $0.065, Phase 5 $0.066, Phase 7 $0.071."""
P = {"openai/gpt-4o": (2.50, 10.00), "openai/gpt-4o-mini": (0.15, 0.60), "anthropic/claude-opus-5-5": (4.00, 20.00),
     "openai/gpt-6.1-terra": (1.00, 5.00)}
def c(m, i, o): a, b = P[m]; return (i * a + o * b) / 1e6

AG_IN, AG_OUT = 29_000, 1_800      # 4 gpt-4o agents per episode (Phase 5 pins)
CLAIMS, VIEWS = 10, 4              # claims scored per episode (Phase 2: 7.4); views W, L, T, X
J_IN, J_OUT = 3_000, 150           # one judge call
PR_IN, PR_OUT = 25_000, 10_000     # one proposer round call (4 candidates)
ROUNDS, CANDS, SCREEN, CONFIRM = 6, 4, 2, 20
K = 10                             # searches per arm in Stage 2 (PLAN §5)
POD_HR = 4 * 0.03                  # cpu3c, 4 vCPU / 8 GB (D7)
COUNCIL_CAP = 40.0

agent = c("openai/gpt-4o", AG_IN, AG_OUT)
judge = CLAIMS * VIEWS * c("openai/gpt-4o-mini", J_IN, J_OUT)
ep = agent + judge
call = c("anthropic/claude-opus-5-5", PR_IN, PR_OUT)
SE, SC = ROUNDS * CANDS * SCREEN, ROUNDS          # episodes and proposer calls per search
search = SE * ep + SC * call
conf = CONFIRM * ep
print(f"unit: episode ${ep:.4f} (agents {agent:.4f} + 4 views {judge:.4f}); proposer call ${call:.4f}; "
      f"search ${search:.2f} ({SE} eps + {SC} calls); confirmation ${conf:.2f} ({CONFIRM} eps); CPU pod ${POD_HR:.2f}/h")

def stage(name, items, days, councils, contingency=0.20):
    eps = sum(i[1] for i in items); calls = sum(i[2] for i in items)
    oa, an = eps * ep, calls * call
    print(f"\n{name}")
    for label, e, k in items:
        print(f"  {label:66s} {e:5d} eps {k:3d} calls  ${e*ep + k*call:7.2f}")
    pod = days * 24 * POD_HR
    cn = councils * COUNCIL_CAP
    tot = (oa + an) * (1 + contingency) + pod + cn
    print(f"  OpenAI ${oa*(1+contingency):.2f}; Anthropic ${an*(1+contingency):.2f} (both +{contingency:.0%}); "
          f"councils {councils} x ${COUNCIL_CAP:.0f} cap = ${cn:.2f} (Anthropic + OpenAI); RunPod CPU {days} d ${pod:.2f}; "
          f"OpenRouter $0; GPU $0")
    print(f"  total ${tot:.2f}  ({eps} episodes, {calls} proposer calls)")
    return tot, oa * (1 + contingency), an * (1 + contingency), pod, cn

def arm(n_search, n_conf): return n_search * SE + n_conf * CONFIRM, n_search * SC

s1_items = [
    ("Q1 qualification: 10 clean + 10 attack, by-hand check", 20, 2),
    ("C clean: 500 calibration + 500 validation", 1000, 0),
    ("L0 static on 100 confirmation instances", 100, 0),
    ("PC positive control: 5 L4 searches against W + confirmations", *arm(5, 5)),
    ("Pilot: 1 search each of L1, L2, L3, L4 against view L + confirmations", *arm(4, 4)),
]
s1 = stage("Stage 1, 29 Oct - 12 Nov (councils: amended PLAN, kill check 1)", s1_items, days=15, councils=2)
s1_noL2 = stage("Stage 1 without L2 (for comparison only)", s1_items[:-1] + [("Pilot: L1, L3, L4", *arm(3, 3))], days=15, councils=2)

s2_items = [
    (f"Leakage L1-L4 against L: {4*K} searches + confirmations", *arm(4 * K, 4 * K)),
    (f"M2 delayed at the strongest level: {K} searches + confirmations", *arm(K, K)),
    (f"M3 noisy at the strongest level: {K} searches + confirmations", *arm(K, K)),
    ("M1 and M4: read from L2 and L1 under the selection rule of Amendment (2); no new searches", 0, 0),
    (f"Fresh l* comparator searches, concurrent with M2/M3/T (Amendment 2): {K} + confirmations", *arm(K, K)),
    (f"View T as a defense: strongest level against T, {K} searches + confirmations", *arm(K, K)),
    (f"L1's selections for T confirmed: {K} confirmations", *arm(0, K)),
    ("L0 static on the other 100 confirmation instances", 100, 0),
    ("Usefulness: 4 feedback regimes x 100 clean episodes, blocking mode", 400, 0),
]
s2 = stage(f"Stage 2, 14 - 28 Nov (own go at kill check 1; k = {K}; council at kill check 2)", s2_items, days=15, councils=1)

d2 = 1000 * ep
n_conf = 5 + 4 + 4 * K + K + K + K + K + K      # every confirmation of Stages 1 and 2
d4 = 2 * (1000 + n_conf * CONFIRM + 200) * CLAIMS * c("openai/gpt-6.1-terra", J_IN, J_OUT)
print(f"\nD2, decided at kill check 1: 1% extension (+500 +500 clean): ${d2:.2f}")
print(f"D4, yes, in Stage 2: rescoring clean + confirmation episodes with gpt-6.1-terra on views L and T: ${d4:.2f}")
print(f"Stage 2 with D4 ${s2[0] + d4:.2f}; with D4 and D2 ${s2[0] + d4 + d2:.2f}")
print(f"Later: final-draft council ${COUNCIL_CAP:.0f}; CPU pod stopped after the 15 Dec freeze (D5)")
print(f"\nStage 1 ${s1[0]:.2f} (cap $600) + Stage 2 with D4 ${s2[0] + d4:.2f} = ${s1[0] + s2[0] + d4:.2f}")

# Amendment (2): sample-size adaptation for L1 and L4 (frozen rule, set at kill check 1 from pooled sigma_b)
for extra, label in ((5, "k = 15 for L1 and L4"), (10, "k = 20 for L1 and L4")):
    e, kk = arm(2 * extra, 2 * extra)
    print(f"Stage 2 add-on if {label}: ${(e*ep + kk*call)*1.2:.2f}")
# Owner's options from the checkpoint-1 split findings
e, kk = arm(5, 5); print(f"Option: 5 L1 searches against W + confirmations (Stage 1): ${(e*ep + kk*call)*1.2:.2f}")
e, kk = arm(0, 2); print(f"Option: information-consistent selection, pilot L1 and L2 extra confirmations (Stage 1): ${(e*ep + kk*call)*1.2:.2f}")
e, kk = arm(0, 2 * K); print(f"Option: information-consistent selection, Stage 2 L1 and L2 extra confirmations: ${(e*ep + kk*call)*1.2:.2f}")
e, kk = arm(K, K); print(f"Option: second M3 noise level (Stage 2): ${(e*ep + kk*call)*1.2:.2f}")
