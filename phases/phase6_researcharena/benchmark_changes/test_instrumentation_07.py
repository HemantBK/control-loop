"""CPU test of benchmark change 07 (owner, 2026-10-24: "instrumentation only ... Confirm it doesn't change the score or
KL; test it on CPU"). Needs torch and transformers 4.53.3; on the CPU pod run it with an existing CPU torch venv:

    /home/fable/work/venv/py311/bin/python -I phases/phase6_researcharena/benchmark_changes/test_instrumentation_07.py

The real inject.py, from the pinned commit with patches 00-06 (before 07) and 00-07 (after), is applied to a tiny Llama
(2 layers, 4 query heads, 2 K/V heads, SDPA attention) built from a config, with no download. The "kernels" are Python
stand-ins for the four ops: rmsnorm, fused_mlp, split-half RoPE at the given positions, and attention through the
original SDPA. Cases:
  1. greedy generation (8 new tokens) and a teacher-forced forward give bitwise-identical tokens and logits before and
     after 07, so the KL is identical (the same logits, the same continuation);
  2. 07's counts match the forward passes exactly:
     - rmsnorm 2 x L x N; fused_mlp L x N; rotary_embedding L x N;
     - attention custom L (prefill), decode_pytorch L x (N-1);
     - no fallbacks;
  3. an attention op that raises: L fallbacks, the first exception kept, outputs still identical before and after 07;
  4. a RoPE op that raises: L x N fallbacks, outputs identical;
  5. the evaluator (evaluate.py) is unchanged by 07, and the counters cost: the measured time of one increment, times the
     increments in one bench pass, as a share of that pass's run time on an H100 (session 3: about 7.3 s for 1024 tokens).
Only the time spent in the counters changes, so this is the whole effect on the score."""
import importlib.util, os, shutil, subprocess, sys, tempfile, time
import torch, torch.nn.functional as F
import transformers
from transformers import LlamaConfig, LlamaForCausalLM
import transformers.models.llama.modeling_llama as llama_mod

RA, STOCK = "/root/src/ResearchArena", "58776e09339c1714d0524130590abaf6eac7879d"
BC = "/root/control-loop/phases/phase6_researcharena/benchmark_changes"
P = sorted(f for f in os.listdir(BC) if f[:2].isdigit() and f.endswith(".patch"))
assert P[-1].startswith("07_"), P
SDPA = F.scaled_dot_product_attention     # the original, captured before any injection
L, N = 2, 8


def composed(patches):
    root = tempfile.mkdtemp(prefix="i07_")
    subprocess.run(f"git -C {RA} archive {STOCK} settings/cuda_kernel src | tar -x -C {root}", shell=True, check=True)
    for p in patches:
        subprocess.run(["patch", "-p1", "-s", "--no-backup-if-mismatch", "-i", f"{BC}/{p}"], cwd=root, check=True)
    return root


def load_inject(root, tag):
    spec = importlib.util.spec_from_file_location(f"inject_{tag}", f"{root}/settings/cuda_kernel/task_context/inject.py")
    m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
    return m


class Ops:
    def __init__(self, fail=None):
        self.fail = fail

    def rmsnorm(self, x, w, eps):
        v = x.float().pow(2).mean(-1, keepdim=True)
        return (x.float() * torch.rsqrt(v + eps)).to(x.dtype) * w

    def fused_mlp(self, x, gw, uw):
        return F.silu(x @ gw.t()) * (x @ uw.t())

    def attention(self, q, k, v, causal):
        if self.fail == "attention":
            raise RuntimeError("stand-in attention failure")
        return SDPA(q, k, v, is_causal=causal)

    def rotary_embedding(self, x, positions, base):     # x [b, s, h, d], positions [b, s]
        if self.fail == "rope":
            raise RuntimeError("stand-in rope failure")
        d = x.shape[-1]
        inv = 1.0 / (base ** (torch.arange(0, d, 2, dtype=torch.float32) / d))
        ang = positions.float()[..., None] * inv
        c, s = ang.cos()[:, :, None, :], ang.sin()[:, :, None, :]
        x1, x2 = x[..., : d // 2].float(), x[..., d // 2:].float()
        return torch.cat([x1 * c - x2 * s, x2 * c + x1 * s], -1).to(x.dtype)


def model():
    cfg = LlamaConfig(vocab_size=128, hidden_size=64, intermediate_size=128, num_hidden_layers=L, num_attention_heads=4,
                      num_key_value_heads=2, max_position_embeddings=256, rope_theta=10000.0)
    cfg._attn_implementation = "sdpa"
    torch.manual_seed(0)
    return LlamaForCausalLM(cfg).eval()


def run(inj, ops):
    """Generation, then a teacher-forced forward over the generated sequence; counts read after generation."""
    if hasattr(llama_mod, "_arena_original_apply_rope"):          # each run starts from unpatched globals
        llama_mod.apply_rotary_pos_emb = llama_mod._arena_original_apply_rope
    m = model()
    injected = inj.inject_agent_kernels(m, ops)
    if hasattr(inj, "reset_kernel_counts"):
        inj.reset_kernel_counts()
    ids = torch.tensor([[1, 5, 9, 17, 33, 2, 7]])
    with torch.no_grad():
        out = m.generate(ids, max_new_tokens=N, do_sample=False, use_cache=True, pad_token_id=0)
        counts = {k: dict(v) for k, v in getattr(inj, "KERNEL_COUNTS", {}).items()}
        first = dict(getattr(inj, "FIRST_FALLBACK", {}))
        logits = m(out).logits
    return out, logits, counts, first, injected


ok_all = True
def check(c, what):
    global ok_all
    ok_all &= bool(c); print(("ok   " if c else "FAIL ") + what)

print(f"torch {torch.__version__}, transformers {transformers.__version__}; patches {P}")
before, after = composed(P[:-1]), composed(P)
inj6, inj7 = load_inject(before, "06"), load_inject(after, "07")
check(not hasattr(inj6, "KERNEL_COUNTS") and hasattr(inj7, "KERNEL_COUNTS"), "07 adds the counters; 00-06 has none")

o6, l6, _, _, i6 = run(inj6, Ops())
o7, l7, c7, f7, i7 = run(inj7, Ops())
check(i6 == i7 and all(i7.values()), f"same ops injected before and after 07: {i7}")
check(torch.equal(o6, o7) and torch.equal(l6, l7), f"1 outputs bitwise identical before/after 07 (tokens {o7[0, -N:].tolist()}); KL unchanged")
want = {"rmsnorm": {"custom": 2 * L * N, "fallback": 0}, "fused_mlp": {"custom": L * N, "fallback": 0},
        "rotary_embedding": {"custom": L * N, "fallback": 0},
        "attention": {"custom": L, "fallback": 0, "decode_pytorch": L * (N - 1)}}
check(c7 == want and not f7, f"2 counts {c7}")

o6, l6, _, _, _ = run(inj6, Ops("attention"))
o7, l7, c7, f7, _ = run(inj7, Ops("attention"))
check(torch.equal(o6, o7) and torch.equal(l6, l7) and c7["attention"] == {"custom": 0, "fallback": L, "decode_pytorch": L * (N - 1)}
      and "stand-in attention failure" in f7.get("attention", ""), f"3 attention fallbacks counted {c7['attention']}, first {f7.get('attention')}")

o6, l6, _, _, _ = run(inj6, Ops("rope"))
o7, l7, c7, f7, _ = run(inj7, Ops("rope"))
check(torch.equal(o6, o7) and torch.equal(l6, l7) and c7["rotary_embedding"] == {"custom": 0, "fallback": L * N},
      f"4 rope fallbacks counted {c7['rotary_embedding']}, outputs identical")

e6 = open(f"{before}/settings/cuda_kernel/evaluate.py").read(); e7 = open(f"{after}/settings/cuda_kernel/evaluate.py").read()
d = {"x": {"custom": 0}}
t0 = time.perf_counter()
for _ in range(1_000_000):
    d["x"]["custom"] += 1
per = (time.perf_counter() - t0) / 1e6
n_inc = 8 * 128 * (22 * 2 + 22 + 22 + 22)          # one bench pass: 8 prompts x 128 tokens x TinyLlama's 22 layers x ops
share = per * n_inc / 7.3
check(e6 == e7 and share < 0.005, f"5 evaluate.py unchanged by 07; one increment {per * 1e9:.0f} ns, {n_inc} per bench pass = "
      f"{per * n_inc * 1000:.1f} ms of about 7.3 s ({share * 100:.3f}%)")
shutil.rmtree(before); shutil.rmtree(after)
print("INSTRUMENTATION_07_TEST", "PASS" if ok_all else "FAIL"); sys.exit(0 if ok_all else 1)
