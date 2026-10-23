"""Option 2 (Amendment (14)): the minimal set from 11ea904 for correct RoPE math with consistent evaluators.
  - kernels/rotary_embedding.cu and starter_kernels/rotary_embedding.cu: the 11ea904 files (identical blobs upstream)
  - inject.py: only the RoPE hunks of 11ea904 (pin the original apply_rotary_pos_emb; record the real position_ids through
    the rotary_emb forward hook and pass them to the kernel). The attn_mask -> sdpa fallback hunk is NOT taken (not RoPE).
  - side_tasks/embedded3/evaluate.py: 11ea904's only change there, the reference RoPE switched to the split-half form.
Writes the patched tree under <out>/tree and the unified diff <out>/opt2_upstream_rope.patch (paths settings/cuda_kernel/...)."""
import os, re, shutil, subprocess, sys
RA, OUT = "/root/src/ResearchArena", sys.argv[1]
STOCK, UP = "58776e09339c1714d0524130590abaf6eac7879d", "11ea904"
def show(rev, p): return subprocess.run(["git", "-C", RA, "show", f"{rev}:{p}"], capture_output=True, text=True, check=True).stdout
S = "settings/cuda_kernel"
files = {f"{S}/task_context/kernels/rotary_embedding.cu": show(UP, f"{S}/task_context/kernels/rotary_embedding.cu"),
         f"{S}/task_context/starter_kernels/rotary_embedding.cu": show(UP, f"{S}/task_context/starter_kernels/rotary_embedding.cu"),
         f"{S}/side_tasks/embedded3/evaluate.py": show(UP, f"{S}/side_tasks/embedded3/evaluate.py")}
# inject.py: stock + the RoPE hunks of the upstream diff only
diff = subprocess.run(["git", "-C", RA, "diff", STOCK, UP, "--", f"{S}/task_context/inject.py"], capture_output=True, text=True, check=True).stdout
head, *hunks = re.split(r"(?m)^(?=@@ )", diff)
keep = [h for h in hunks if "attn_mask is not None" not in h]
assert len(hunks) == 3 and len(keep) == 2, (len(hunks), len(keep))
up_diff = os.path.join(OUT, "inject_rope_hunks.diff"); os.makedirs(OUT, exist_ok=True)
open(up_diff, "w").write(head + "".join(keep))
stock_tree, tree = os.path.join(OUT, "stock"), os.path.join(OUT, "tree")
for t in (stock_tree, tree):
    shutil.rmtree(t, ignore_errors=True)
for p in list(files) + [f"{S}/task_context/inject.py"]:
    for t in (stock_tree, tree):
        os.makedirs(os.path.dirname(os.path.join(t, p)), exist_ok=True)
        open(os.path.join(t, p), "w").write(show(STOCK, p))
for p, body in files.items():
    open(os.path.join(tree, p), "w").write(body)
subprocess.run(["patch", "-p1", "-d", tree, "-i", os.path.abspath(up_diff)], check=True)
d = subprocess.run(["diff", "-ruN", "stock", "tree"], cwd=OUT, capture_output=True, text=True).stdout
d = d.replace("--- stock/", "--- a/").replace("+++ tree/", "+++ b/")
open(os.path.join(OUT, "opt2_upstream_rope.patch"), "w").write(d)
print("files changed:", [p for p in list(files) + [f"{S}/task_context/inject.py"]])
print("patch lines:", len(d.splitlines()))
