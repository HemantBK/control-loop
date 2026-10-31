"""Cost of the paper experiments per provider (OpenRouter listed prices read 2026-10-27; per-episode token use from
Phases 5 and 8 and cell 733). Prints the tables used in docs/paper/PLAN.md §6."""
P = {  # $ per 1M tokens: input, output (OpenRouter /api/v1/models, 2026-10-27)
 "openai/gpt-4o": (2.5, 10), "openai/gpt-6-luna": (0.1, 0.5), "openai/gpt-6.1-terra": (1.0, 5.0), "openai/gpt-6.1-sol": (2.0, 10.0),
 "anthropic/claude-haiku-5.5": (0.1, 0.5), "anthropic/claude-sonnet-5.5": (2.0, 10.0), "anthropic/claude-opus-5.5": (4.0, 20.0),
 "anthropic/claude-fable-5.1": (10.0, 50.0), "google/gemini-3.8-flash": (0.825, 4.125), "z-ai/glm-5.1": (0.966, 3.036),
}
AG_IN, AG_OUT = 29_000, 1_800          # ORBIT, 4 gpt-4o agents per episode, input incl. cache reads at full price (Phase 5 pins)
MON_IN, MON_OUT = 4_800, 1_500         # transcript monitor per episode (Phase 8: 4.8k in; output raised from 0.5k for reasoning models)
PROP_IN, PROP_OUT = 12_000, 4_000      # proposer call with history and monitor reasoning (Phase 5 calls were ~4k/1k; richer feedback)
def c(m, i, o): a, b = P[m]; return (i * a + o * b) / 1e6
agent = c("openai/gpt-4o", AG_IN, AG_OUT)
MONS = {"weak": "openai/gpt-6-luna", "mid": "openai/gpt-6.1-terra", "strong": "openai/gpt-6.1-sol"}
ENS = ["openai/gpt-6.1-terra", "anthropic/claude-sonnet-5.5", "google/gemini-3.8-flash"]
mon = {k: c(m, MON_IN, MON_OUT) for k, m in MONS.items()}
mon["ensemble"] = sum(c(m, MON_IN, MON_OUT) for m in ENS)
all_scorers = mon["weak"] + mon["mid"] + mon["strong"] + c("anthropic/claude-sonnet-5.5", MON_IN, MON_OUT) + c("google/gemini-3.8-flash", MON_IN, MON_OUT)
prop = c("anthropic/claude-opus-5.5", PROP_IN, PROP_OUT)
print(f"per episode: agents ${agent:.4f}; monitors {{k: round(v,4) for k,v in mon.items()}} -> {', '.join(f'{k} ${v:.4f}' for k,v in mon.items())}; all five scorers ${all_scorers:.4f}; proposer call ${prop:.4f}")
# E1: ORBIT core
n_mon = 4; reps = 3; B = 32; screen = 2; levels = 6; confirm = 16
eps = dict(clean=200, static=50, search=n_mon * reps * B * screen, confirm=n_mon * reps * levels * confirm)
calls = n_mon * reps * B
E1 = dict(agents=sum(eps.values()) * agent, monitors=sum(eps.values()) * all_scorers, proposer=calls * prop)
print("E1 episodes", eps, "total", sum(eps.values()), "proposer calls", calls, {k: round(v, 2) for k, v in E1.items()}, "sum", round(sum(E1.values()), 2))
# E2: defenses (3 defenses with adaptive re-search at B=32 plus confirmation; randomized prompts rescore with K=5 variants)
d = 3; eps2 = d * reps * B * screen + d * reps * levels * confirm
rescore_rand = (eps["confirm"] + eps2 + eps["clean"]) * 4 * mon["mid"]   # 4 extra prompt variants of the mid monitor
E2 = dict(agents=eps2 * agent, monitors=eps2 * all_scorers + rescore_rand, proposer=d * reps * B * prop)
print("E2 episodes", eps2, {k: round(v, 2) for k, v in E2.items()}, "sum", round(sum(E2.values()), 2))
# by provider (E1 + E2)
prov = {"OpenAI (agents gpt-4o + monitors Luna/Terra/Sol)": (sum(eps.values()) + eps2) * (agent + mon["weak"] + mon["mid"] + mon["strong"]) + rescore_rand,
        "Anthropic (proposer Opus 5.5 + Sonnet 5.5 in the ensemble)": (calls + d * reps * B) * prop + (sum(eps.values()) + eps2) * c("anthropic/claude-sonnet-5.5", MON_IN, MON_OUT),
        "Google (Gemini 3.8 Flash in the ensemble)": (sum(eps.values()) + eps2) * c("google/gemini-3.8-flash", MON_IN, MON_OUT)}
for k, v in prov.items(): print(f"  {k}: ${v:.2f}")
print("E1+E2", round(sum(E1.values()) + sum(E2.values()), 2), "check", round(sum(prov.values()), 2))
# variants
print("agents on gpt-6.1-terra instead of gpt-4o, per episode", round(c("openai/gpt-6.1-terra", AG_IN, AG_OUT), 4))
print("proposer Fable 5.1 instead of Opus 5.5, per call", round(c("anthropic/claude-fable-5.1", PROP_IN, PROP_OUT), 4), "E1+E2 delta", round((calls + d*reps*B) * (c("anthropic/claude-fable-5.1", PROP_IN, PROP_OUT) - prop), 2))
# E3b: ResearchArena curves at smaller scale (cell 733 unit costs, change 10)
ep1h = 4.63 + 0.39 + 1.97 + 0.252     # GPU (2/pod) + agent + monitor, one-hour episode
scr = 1.97 + 0.78 + 0.66 + 0.12       # 20-minute screening, 1/pod
Bs = [1, 4, 16]; mons3 = 2            # Sonnet 4.6 M∅ (as 6b) and one stronger monitor
E3b = dict(search=mons3 * 16 * scr, confirm=mons3 * len(Bs) * 8 * ep1h, rescore=(mons3 * len(Bs) * 8 + 32) * 0.30)
print("E3b", {k: round(v, 2) for k, v in E3b.items()}, "sum", round(sum(E3b.values()), 2), "x1.05", round(sum(E3b.values()) * 1.05, 2))
