"""Power of the M3 dose-response (PLAN Amendment (3)). No data, no model call. Same paired-block model as power_sim.py.
Five arms share confirmation block i: L1 (x = 0), M3 at eps 0.75, 0.5, 0.25 (x = 1 - eps) and the fresh l* comparator
(x = 1). Per-search rate mean p1 + A(x). Per block: OLS slope of rate on x, and the quadratic coefficient of a
centred quadratic; t-intervals over the k blocks. Shapes: linear A(x) = A0 x; threshold A(x) = A0 for x >= 0.5, else 0."""
import numpy as np
from scipy import stats
from scipy.special import expit, logit

rng = np.random.default_rng(20261029)
X = np.array([0.0, 0.25, 0.5, 0.75, 1.0])

def beta_draw(mean, sd, size):
    if sd == 0:
        return np.full(size, mean)
    v = sd ** 2
    c = mean * (1 - mean) / v - 1
    return rng.beta(mean * c, (1 - mean) * c, size)

def simulate(k, m, p1, a0, shape, sigma_b, tau_v=0.5, sims=4000):
    t = stats.t.ppf(0.975, k - 1)
    xc = X - X.mean()
    q = xc ** 2 - (xc ** 2).mean()
    q = q - xc * (q @ xc) / (xc @ xc)
    slope_pos = curve = 0
    for _ in range(sims):
        u = rng.normal(0, tau_v, (k, m))
        rates = []
        for x in X:
            a = a0 * x if shape == "linear" else (a0 if x >= 0.5 else 0.0)
            p = np.clip(beta_draw(p1 + a, sigma_b, k), 1e-4, 1 - 1e-4)
            rates.append((rng.random((k, m)) < expit(logit(p)[:, None] + u)).mean(1))
        r = np.array(rates).T                      # k x 5
        b = r @ xc / (xc @ xc)
        c = r @ q / (q @ q)
        if b.mean() - t * b.std(ddof=1) / np.sqrt(k) > 0:
            slope_pos += 1
        if abs(c.mean()) > t * c.std(ddof=1) / np.sqrt(k):
            curve += 1
    return slope_pos / sims, curve / sims

print("k  m  p1   A0   shape      sigma_b  P(slope > 0)  P(curvature detected)")
for k in (10,):
    for a0 in (0.10, 0.15, 0.20):
        for shape in ("linear", "threshold"):
            for sb in (0.05, 0.10, 0.20):
                s, c = simulate(k, 20, 0.20, a0, shape, sb)
                print(f"{k:2d} 20 0.20 {a0:.2f} {shape:10s} {sb:.2f}     {s:.2f}          {c:.2f}")
