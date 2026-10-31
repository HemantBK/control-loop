"""Simulation of the paired-block decision rule (PLAN Amendment (2), council checkpoint 1). No data, no model call.
Search i of each level is confirmed on block i (m fresh instances shared across levels). Per-search rate p ~ Beta with
mean p_level and SD sigma_b; instance j of block i shifts every level's logit by u_ij ~ N(0, tau_v) (shared difficulty).
Contrast d_i = rate(level, i) - rate(L1, i); paired t-interval over the k blocks (df k - 1).
Decisions: effect = lower bound > 0; no-advantage-above-15 = upper bound < 0.15; equivalence = interval inside +-0.15."""
import numpy as np
from scipy import stats
from scipy.special import expit, logit

rng = np.random.default_rng(20261028)

def beta_draw(mean, sd, size):
    if sd == 0:
        return np.full(size, mean)
    v = sd ** 2
    c = mean * (1 - mean) / v - 1
    return rng.beta(mean * c, (1 - mean) * c, size)

def simulate(k, m, p1, delta, sigma_b, tau_v, sims=4000):
    out = {"effect": 0, "no_adv_15": 0, "equiv_15": 0, "inconclusive": 0}
    t = stats.t.ppf(0.975, k - 1)
    for _ in range(sims):
        u = rng.normal(0, tau_v, (k, m))
        r = []
        for mean in (p1, p1 + delta):
            p = np.clip(beta_draw(mean, sigma_b, k), 1e-4, 1 - 1e-4)
            y = rng.random((k, m)) < expit(logit(p)[:, None] + u)
            r.append(y.mean(1))
        d = r[1] - r[0]
        se = d.std(ddof=1) / np.sqrt(k)
        lo, hi = d.mean() - t * se, d.mean() + t * se
        if lo > 0:
            out["effect"] += 1
        elif hi < 0.15:
            out["no_adv_15"] += 1
        else:
            out["inconclusive"] += 1
        if lo > -0.15 and hi < 0.15:
            out["equiv_15"] += 1
    return {kk: v / sims for kk, v in out.items()}

print("P(decision) for the primary contrast A(L4) = U(L4) - U(L1); base U(L1) = 0.20; m = 20 per block")
print(" k   sigma_b  tau_v  true diff | effect  no-adv>15  inconclusive | two-sided equiv +-15")
for k in (10, 15, 20):
    for sb in (0.0, 0.10, 0.20):
        for tv in (0.0, 1.0):
            for delta in (0.0, 0.10, 0.20):
                r = simulate(k, 20, 0.20, delta, sb, tv)
                print(f" {k:2d}   {sb:.2f}     {tv:.1f}    {delta:+.2f}     | {r['effect']:.2f}    {r['no_adv_15']:.2f}       {r['inconclusive']:.2f}         | {r['equiv_15']:.2f}")
