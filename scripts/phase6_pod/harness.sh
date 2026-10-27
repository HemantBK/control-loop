#!/bin/bash
# Phase 6 GPU pod harness (PLAN Amendments (16)-(19)): apply the benchmark changes (00-10) to the composed root, never to the
# pinned checkout. Every path a patch touches is first made a real file: each symlinked component along it (the composed
# root links e.g. settings/cuda_kernel/instruction.md and side_tasks/embedded3 into the checkout) is replaced by a copy of
# its target. Then: sha256 of every patched file against expected_sha256.txt; the checkout's git status must be clean;
# model-cache mirror; inotify-tools; the model loads offline as bench.py loads it.
# Expects /workspace/bench_changes/[0-9][0-9]_*.patch and expected_sha256.txt (pushed by scripts/phase6/session3.py kit).
set -euo pipefail
[ -f /etc/rp_environment ] && . /etc/rp_environment; [ -f /workspace/p6_env.sh ] && . /workspace/p6_env.sh; export HF_HOME=/workspace/hf
A=${P6_ARENA_ROOT_DIR:-/workspace/arena_root}; BC=${P6_BENCH_CHANGES_DIR:-/workspace/bench_changes}; cd $A   # overridable for the CPU test
python3 - "$A" $BC/[0-9][0-9]_*.patch <<'PY'
import os, re, shutil, sys
root, patches = sys.argv[1], sys.argv[2:]
paths = sorted({m for p in patches for m in re.findall(r"^\+\+\+ b/(\S+)", open(p).read(), flags=re.M)})
for rel in paths:
    parts = rel.split("/")
    for i in range(1, len(parts) + 1):
        q = os.path.join(root, *parts[:i])
        if os.path.islink(q):
            t = os.path.realpath(q); os.unlink(q)
            (shutil.copytree(t, q, symlinks=False) if os.path.isdir(t) else shutil.copy2(t, q))
            print(f"real copy: {'/'.join(parts[:i])} (from {t})")
print(f"patched paths: {len(paths)}")
PY
for f in $BC/[0-9][0-9]_*.patch; do
  if patch -p1 --dry-run -R -s -f < "$f" >/dev/null 2>&1; then echo "already applied: $(basename $f)"; else patch -p1 --no-backup-if-mismatch < "$f" > /dev/null; echo "applied: $(basename $f)"; fi
done
( cd $A && sha256sum -c --quiet $BC/expected_sha256.txt ) && echo "PATCHED_FILES_MATCH_EXPECTED"
CK=$(readlink -f $A/settings/cuda_kernel/config.json | sed 's|/settings/cuda_kernel/config.json||')
if git -C "$CK" diff --quiet HEAD --; then echo "CHECKOUT_UNCHANGED $CK"; else echo "CHECKOUT_MODIFIED $CK"; git -C "$CK" diff --stat HEAD | tail -5; exit 3; fi
for m in $HF_HOME/hub/models--*; do [ -e $HF_HOME/$(basename $m) ] || ln -s $m $HF_HOME/$(basename $m); done
command -v inotifywait >/dev/null || { apt-get install -y -q inotify-tools >/dev/null 2>&1 || (apt-get update -q >/dev/null 2>&1 && apt-get install -y -q inotify-tools >/dev/null 2>&1); }
command -v inotifywait >/dev/null && echo "INOTIFY_OK"
[ -f /workspace/src/control-loop/control_loop/adapters/researcharena/procs.py ] && echo "PROCS_OK"   # the one process-match helper (Amendment (19) item 6)
if [ -n "${P6_LOCAL_TARGET:-}" ]; then echo "MODEL_LOAD_SKIPPED_LOCAL (CPU-pod rehearsal: the model load needs the GPU pod)"; exit 0; fi
D=$(mktemp -d); cp -r $A/settings/cuda_kernel/task_context/. $D/; rm -rf $D/workspace; cd $D
HF_HUB_OFFLINE=1 timeout 300 python3 -c "import sys; sys.path.insert(0, '.'); from config import ArenaConfig; from bench import load_model_and_tokenizer; m, t = load_model_and_tokenizer(ArenaConfig()); print('MODEL_LOAD_OK', type(m).__name__)" 2>&1 | tail -2
rm -rf $D
