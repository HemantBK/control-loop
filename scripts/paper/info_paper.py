"""Information quantities for PLAN Amendment (3). No data, no model call.
1. Capacity of the per-claim verdict channel under M3's replacement noise: the shown verdict is the true one with
   probability 1 - eps, else a clean claim's verdict (BLOCK with probability r0). Capacity in bits per claim.
2. Proposition 1 constant: kappa_N = (N - 1) / sqrt(2N - 1) (Hartley-David bound on the expected maximum of N iid draws,
   in SDs), and the certified leakage I >= (2 / ln 2) (G / kappa_N)^2 bits implied by an observed selection gain G."""
import numpy as np

def h(p):
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return -(p * np.log2(p) + (1 - p) * np.log2(1 - p))

def capacity(eps, r0):
    # P(show BLOCK | v) = (1 - eps) v + eps r0; maximise I over the input probability a = P(v = 1)
    a = np.linspace(0, 1, 20001)
    p1, p0 = (1 - eps) + eps * r0, eps * r0
    i = h(a * p1 + (1 - a) * p0) - (a * h(p1) + (1 - a) * h(p0))
    return i.max()

print("Verdict channel capacity under replacement noise (bits per claim); erasure ceiling (1 - eps) for reference")
print("  eps   r0=0.01  r0=0.05  (1-eps)")
for eps in (0.0, 0.2, 0.25, 0.5, 0.75, 1.0):
    print(f"  {eps:4.2f}  {capacity(eps, 0.01):7.3f}  {capacity(eps, 0.05):7.3f}  {1 - eps:6.2f}")

print("\nProposition 1: selection gain G <= kappa_N * sqrt(I ln2 / 2); certified bits from an observed gain")
for N in (4, 24):
    k = (N - 1) / np.sqrt(2 * N - 1)
    row = "  ".join(f"G={g:.2f}: I>={(2 / np.log(2)) * (g / k) ** 2:.4f}" for g in (0.05, 0.10, 0.20))
    ceil = "  ".join(f"I={i}: G<={k * np.sqrt(i * np.log(2) / 2):.3f}" for i in (0.01, 0.05, 0.2))
    print(f"  N={N:2d} kappa={k:.3f}  {row}\n         {ceil}")
