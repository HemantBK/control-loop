"""Power of the selection-leak estimand B_sel (PLAN Amendment (4), checkpoint council 1b). No data, no model call.
Per search: with probability d the information-consistent and monitor-aware selectors pick different candidates; else
the difference is exactly 0. When they differ, both are confirmed on the search's block of m instances (shared instance
logit shift u ~ N(0, tau_v)); candidate rates p_ic ~ Beta(p1, 0.10) and p_sh = p_ic + delta_i, delta_i ~ N(B / d, sd_d)
so that the mean difference over all searches is B. Estimate: mean over the k searches of (rate_sh - rate_ic), zeros
included; paired t-interval (df k - 1). Decisions as in A2.5: effect = lower bound > 0; no-bias-above-10 = upper < 0.10."""
import numpy as np
from scipy import stats
from scipy.special import expit, logit

rng = np.random.default_rng(20261030)

def beta_draw(mean, sd, size):
    v = sd ** 2
    c = mean * (1 - mean) / v - 1
    return rng.beta(mean * c, (1 - mean) * c, size)

def simulate(k, m, p1, b, d, sd_d, tau_v=0.5, sims=4000):
    t = stats.t.ppf(0.975, k - 1)
    eff = small = 0
    for _ in range(sims):
        diff = rng.random(k) < d
        u = rng.normal(0, tau_v, (k, m))
        p_ic = np.clip(beta_draw(p1, 0.10, k), 1e-4, 1 - 1e-4)
        p_sh = np.clip(p_ic + rng.normal(b / d, sd_d, k), 1e-4, 1 - 1e-4)
        y_ic = (rng.random((k, m)) < expit(logit(p_ic)[:, None] + u)).mean(1)
        y_sh = (rng.random((k, m)) < expit(logit(p_sh)[:, None] + u)).mean(1)
        x = np.where(diff, y_sh - y_ic, 0.0)
        if x.std(ddof=1) == 0:
            small += b < 0.10
            continue
        se = x.std(ddof=1) / np.sqrt(k)
        lo, hi = x.mean() - t * se, x.mean() + t * se
        eff += lo > 0
        small += (lo <= 0) and (hi < 0.10)
    return eff / sims, small / sims

print("k   d    sd_d   B=0: P(effect) P(no bias>10) | B=0.05 effect | B=0.10 effect | B=0.15 effect")
for k in (10, 20):
    for d in (0.3, 0.6, 1.0):
        for sd_d in (0.05, 0.10, 0.20):
            r = [simulate(k, 20, 0.20, b, d, sd_d) for b in (0.0, 0.05, 0.10, 0.15)]
            print(f"{k:2d} {d:.1f}  {sd_d:.2f}      {r[0][0]:.2f}        {r[0][1]:.2f}      |     {r[1][0]:.2f}      |"
                  f"     {r[2][0]:.2f}      |     {r[3][0]:.2f}")
