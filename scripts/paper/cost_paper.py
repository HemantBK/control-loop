"""Cost of docs/paper/PLAN.md with Amendments (1)-(4) of 2026-10-28, per stage and provider. Amendment (2)'s version is
in superseded/. Prices: control_loop/spend.py, checked in docs/prices_verified_2026-10-21.md; council and GPT-6.1 models
from OpenRouter's /api/v1/models (read 2026-10-28); CPU pod from RunPod list-cpu-types (read 2026-10-28: cpu3c $0.03 per
vCPU-hour). Token use per unit is an upper estimate: cache reads priced at full input, no reasoning tokens (the agent
pilot measures them). Measured all-in cost per ORBIT episode in earlier phases: $0.065-$0.071 (gpt-4o agents).
Usage: cost_paper.py [agent model], default openai/gpt-4o."""
import sys
P = {"openai/gpt-4o": (2.50, 10.00), "openai/gpt-4o-mini": (0.15, 0.60), "anthropic/claude-opus-5-5": (4.00, 20.00),
     "openai/gpt-6.1-terra": (1.00, 5.00), "openai/gpt-6.1-sol": (2.00, 10.00)}
def c(m, i, o): a, b = P[m]; return (i * a + o * b) / 1e6

AGENT = sys.argv[1] if len(sys.argv) > 1 else "openai/gpt-4o"
AG_IN, AG_OUT = 29_000, 1_800      # 4 agents per episode (Phase 5 pins)
CLAIMS, VIEWS = 10, 4              # claims scored per episode (Phase 2: 7.4); views W, L, T, X
J_IN, J_OUT = 3_000, 150           # one judge call (verdict line + reason)
PR_IN, PR_OUT = 25_000, 10_000     # one proposer round call (4 candidates)
ROUNDS, CANDS, SCREEN, CONFIRM = 6, 4, 2, 20
K = 10                             # searches per arm in Stage 2
DOSES = 3                          # M3 replacement rates 0.25, 0.5, 0.75 (Amendment 3)
POD_HR = 4 * 0.03                  # cpu3c, 4 vCPU / 8 GB (D7)
COUNCIL_CAP = 40.0
CP1_SPENT = 27.78                  # checkpoint council 1, 2026-10-28 (cost.json)
HOLD = 90.0                        # held back for elicitation repair (A1.8, restored by Amendment 4)
EMBED = 1.00                       # text embeddings of view L and T reasons for the leakage estimate (upper estimate)

agent = c(AGENT, AG_IN, AG_OUT)
judge = CLAIMS * VIEWS * c("openai/gpt-4o-mini", J_IN, J_OUT)
ep = agent + judge
call = c("anthropic/claude-opus-5-5", PR_IN, PR_OUT)
SE, SC = ROUNDS * CANDS * SCREEN, ROUNDS
search = SE * ep + SC * call
conf = CONFIRM * ep
print(f"agents {AGENT}; unit: episode ${ep:.4f} (agents {agent:.4f} + 4 views {judge:.4f}); proposer call ${call:.4f}; "
      f"search ${search:.2f}; confirmation ${conf:.2f}; CPU pod ${POD_HR:.2f}/h")

def arm(n_search, n_conf): return n_search * SE + n_conf * CONFIRM, n_search * SC

def stage(name, items, days, councils, flat=0.0, contingency=0.20):
    eps = sum(i[1] for i in items); calls = sum(i[2] for i in items)
    oa, an = eps * ep, calls * call
    print(f"\n{name}")
    for label, e, k in items:
        print(f"  {label:78s} {e:5d} eps {k:3d} calls  ${e*ep + k*call:7.2f}")
    pod = days * 24 * POD_HR
    cn = sum(councils)
    tot = (oa + an) * (1 + contingency) + pod + cn + flat
    print(f"  OpenAI ${oa*(1+contingency):.2f}; Anthropic ${an*(1+contingency):.2f} (both +{contingency:.0%}); "
          f"councils ${cn:.2f}; RunPod CPU {days} d ${pod:.2f}; other ${flat:.2f}; GPU $0")
    print(f"  total ${tot:.2f}  ({eps} episodes, {calls} proposer calls)")
    return tot

s1_items = [
    ("Agent-model pilot: 2 clean + 2 L0 episodes on the candidate agent model", 4, 0),
    ("Q1 qualification: 10 clean + 10 attack, by-hand check", 20, 2),
    ("C clean: 500 calibration + 500 validation", 1000, 0),
    ("L0 static on 100 confirmation instances", 100, 0),
    ("PC positive control: 5 L4 searches against W + confirmations", *arm(5, 5)),
    ("S2: 5 L1 searches against W + confirmations", *arm(5, 5)),
    ("Pilot: 1 search each of L1-L4 against view L + confirmations", *arm(4, 4)),
    ("S1/selection study: second selection confirmed (pilot L1, L2; 5 L1-on-W)", *arm(0, 7)),
]
s1 = stage("Stage 1 (councils: checkpoint 1 spent, checkpoint 1b cap, kill check 1 cap)", s1_items, days=15,
           councils=[CP1_SPENT, COUNCIL_CAP, COUNCIL_CAP])

s2_items = [
    (f"Leakage L1-L4 against L: {4*K} searches + confirmations", *arm(4 * K, 4 * K)),
    (f"M2 delayed at l*: {K} searches + confirmations", *arm(K, K)),
    (f"M3 dose-response at l*, {DOSES} replacement rates x {K} searches + confirmations", *arm(DOSES * K, DOSES * K)),
    (f"Fresh l* comparator (x = 1 of the dose-response): {K} searches + confirmations", *arm(K, K)),
    (f"Fresh L1 endpoint (x = 0), on the mitigation blocks (Amendment 4): {K} searches + confirmations", *arm(K, K)),
    (f"View T as a defense: l* against T, {K} searches + confirmations", *arm(K, K)),
    (f"L1's selections for T confirmed: {K} confirmations", *arm(0, K)),
    ("L0 static on the other 100 confirmation instances", 100, 0),
    ("Usefulness: 4 feedback regimes x 100 clean episodes, blocking mode", 400, 0),
    (f"Selection study: second selection confirmed (L1, L2, M2, M3 doses; {6*K} upper bound)", *arm(0, 6 * K)),
    ("Selection-channel study and leakage estimates: screening data only", 0, 0),
]
s2 = stage(f"Stage 2 (own go at kill check 1; k = {K}; council at kill check 2)", s2_items, days=15,
           councils=[COUNCIL_CAP], flat=EMBED)

d2 = 1000 * ep
n_conf = 5 + 5 + 4 + 7 + 4 * K + K + DOSES * K + K + K + K + K + 6 * K   # every confirmation of Stages 1 and 2
d4 = 2 * (1000 + n_conf * CONFIRM + 200) * CLAIMS * c("openai/gpt-6.1-terra", J_IN, J_OUT)
print(f"\nD2, decided at kill check 1: 1% extension (+500 +500 clean): ${d2:.2f}")
print(f"D4: rescoring clean + confirmation episodes with gpt-6.1-terra on views L and T: ${d4:.2f}")
print(f"Stage 2 with D4 ${s2 + d4:.2f}; with D4 and D2 ${s2 + d4 + d2:.2f}")
print(f"Stage 1 + ${HOLD:.0f} held back = ${s1 + HOLD:.2f} (cap $600)")
print(f"\nStage 1 ${s1:.2f} (cap $600) + Stage 2 with D4 ${s2 + d4:.2f} = ${s1 + s2 + d4:.2f}")
for extra, label in ((5, "k = 15 for L1 and L4"), (10, "k = 20 for L1 and L4")):
    e, kk = arm(2 * extra, 3 * extra)   # searches, their confirmations, and L1's second selections
    print(f"Stage 2 add-on if {label}: ${(e*ep + kk*call)*1.2:.2f}")
e, kk = arm(0, K); print(f"If l* = L2: second selections of the fresh comparator: ${(e*ep + kk*call)*1.2:.2f}")
e, kk = arm(K, K); print(f"S7 option (a), if l* = L4: fresh L3 comparator: ${(e*ep + kk*call)*1.2:.2f}")
e, kk = arm(DOSES * K, DOSES * K); print(f"Saved if no level is eligible as l* (M3 doses only): ${(e*ep + kk*call)*1.2:.2f}")
