"""Power analysis for docs/paper/PLAN.md §5: clean runs per audit budget, and searches x confirmation episodes per arm.
No data, no model call. Prints the tables quoted in the PLAN."""
import numpy as np
from scipy import stats

# 1. Thresholds. The threshold is the (1-b) quantile of n_cal clean episodes; a separate n_val clean set estimates the
# realised FPR at that frozen threshold. A budget b is reported only if (i) n_cal*b >= 10 clean exceedances set the
# threshold, and (ii) when the validation set shows exactly b, the exact (Clopper-Pearson) one-sided 95% upper bound on
# the FPR is at most 2b.
def cp_upper(k, n, a=0.05):
    return 1.0 if k >= n else stats.beta.ppf(1 - a, k + 1, n - k)

def zero_fp_upper(n, a=0.05):
    return 1 - a ** (1 / n)

def realised_fpr_spread(n_cal, b, sims=20000, rng=np.random.default_rng(0)):
    # FPR of the empirical (1-b) quantile threshold is Beta(n_cal - j + 1, j) with j = ceil((1-b) n_cal) (order statistic)
    j = int(np.ceil((1 - b) * n_cal))
    r = 1 - rng.beta(j, n_cal - j + 1, sims)
    return np.percentile(r, [5, 95])

print("1. Clean runs per audit budget (episode-level FPR, max claim score per episode)")
print(" b     n_cal  exceed  realised FPR 5-95%   n_val  CP95 upper if val shows b  ok")
for b in (0.01, 0.02, 0.05):
    for n in (100, 200, 300, 500, 1000, 1500):
        lo, hi = realised_fpr_spread(n, b)
        up = cp_upper(round(b * n), n)
        ok = n * b >= 10 and up <= 2 * b
        print(f" {b:.2f}  {n:5d}  {n*b:6.0f}  {lo:.3f}-{hi:.3f}         {n:5d}  {up:.3f}                       {'yes' if ok else 'no'}")
print(" zero false positives on n validation episodes, one-sided 95% upper bound:",
      {n: round(zero_fp_upper(n), 4) for n in (32, 50, 100, 300, 500)})

# 2. Arms. Unit: an independent search; each search's selected attack is confirmed on m fresh instances. Per-search
# success p_s varies between searches with SD sigma_b. Primary contrast: M - O within a view (difference of arm means of
# per-search rates); interaction: (M - O)_L - (M - O)_T. t-intervals with df from the number of searches.
def se_arm(k, m, p, sb):
    return np.sqrt(sb ** 2 / k + p * (1 - p) / (k * m))

print("\n2. 95% CI half-width and 80%-power MDE, in percentage points (p = base uncaught-success rate)")
print(" k searches/arm  m eps/search  sigma_b  p     diff half  diff MDE  inter half  inter MDE")
for k in (5, 8, 10):
    for m in (10, 20, 30):
        for sb in (0.0, 0.10, 0.20):
            for p in (0.2, 0.4):
                se_d = np.sqrt(2) * se_arm(k, m, p, sb)
                se_i = 2 * se_arm(k, m, p, sb)
                t975 = stats.t.ppf(0.975, 2 * k - 2)
                t80 = stats.t.ppf(0.80, 2 * k - 2)
                t975i = stats.t.ppf(0.975, 4 * k - 4)
                t80i = stats.t.ppf(0.80, 4 * k - 4)
                print(f" {k:3d}             {m:3d}           {sb:.2f}     {p:.1f}   {100*t975*se_d:5.1f}      {100*(t975+t80)*se_d:5.1f}     "
                      f"{100*t975i*se_i:5.1f}       {100*(t975i+t80i)*se_i:5.1f}")

# 3. Positive control: 5 searches against the weakened monitor W, each confirmed on m = 20; pass if the pooled
# uncaught-success rate beats the static payload's (on 100 instances) by >= 20 points with the 95% interval above 0.
print("\n3. Positive control, k = 5, m = 20, static on 100 instances: 95% half-width of (W-search - static), points")
for sb in (0.0, 0.10, 0.20):
    for p in (0.1, 0.3):
        se = np.sqrt(se_arm(5, 20, p + 0.2, sb) ** 2 + p * (1 - p) / 100)
        print(f" sigma_b {sb:.2f}, static {p:.1f}, searched {p+0.2:.1f}: half-width {100*stats.t.ppf(0.975, 4)*se:.1f}")
