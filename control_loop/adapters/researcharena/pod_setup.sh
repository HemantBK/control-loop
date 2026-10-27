#!/usr/bin/env bash
# Phase 6 GPU pod setup (phases/phase6_researcharena/PLAN.md §10.5, steps 1-7). Streamed over ssh by pods.py
# (`bash -s`), run as root on a fresh RunPod pod of image runpod/base:1.4.1-cuda1290-ubuntu2204 (PLAN Amendment
# 2026-10-22 (2): nvidia/cuda:12.9.0-cudnn-devel-ubuntu22.04 + deadsnakes Pythons + RunPod's sshd start script; no
# torch). Step 3 installs torch==2.10.0 from PyPI into python3.11 and makes python3 resolve to it, matching
# ResearchArena's container runtime (containers/arena.def: python3.11, torch 2.10.0 from PyPI via vllm 0.17.0, whose
# x86_64 wheel bundles the CUDA 12.8 runtime, nvidia-cuda-runtime-cu12==12.8.90; nvcc 12.9 from the devel image).
# 2026-10-22 (owner, before smoke4): PyPI torch replaces the cu129 wheel; nvcc 12.9 and CUDA_HOME stay.
# 2026-10-22, Amendment (5): transformers pinned to 4.53.3 (head-layout verdict; 5.3.0 hands unexpanded GQA K/V to
# ops.attention). Amendment (4): on the prebuilt Phase 6 image (docker/phase6/Dockerfile) whose /etc/p6_image.json
# records the expected versions, steps 1-6 are skipped (`0_baked` links /opt/ResearchArena and /opt/hf into the paths
# below and re-checks the runtime pieces); steps 5 and 7 run as always.
# Idempotent: every step leaves a marker under $P6_STATE and is skipped on a second run. Each step logs its
# duration. Exits non-zero on the first failure. No secret is read or printed here.
#
# Variables (exported by pods.py before `bash -s`; defaults below are the PLAN's):
#   RESEARCHARENA_COMMIT   pinned ResearchArena commit (PLAN §1.1)
#   CONTROL_LOOP_COMMIT    "local" (default: pods.py pushed this host's tree by tar over ssh) or a commit to clone
#   CONTROL_LOOP_REPO      the git URL used when CONTROL_LOOP_COMMIT is a commit
#   OPENCODE_VERSION       opencode-ai npm version ("" = latest; pinned in pins.md after §6.1)
#   ARENA_ROOT             composed root to build (default /workspace/arena_root)
#   ARENA_RESULTS_DIR      results dir (default /workspace/results)       HF_HOME  (default /workspace/hf)
#   P6_PAYLOAD_DIR         where pods.py writes the round's payload (default /workspace/p6)
#   ARENA_BUILD_CMD        override for step 5 (the core's arena_root CLI; see PODS_NOTES.md)
#   P6_FUSE_DEV            the FUSE device to look for (default /dev/fuse; tests point it at a missing path)
#   P6_FUSE_SHIM_SRC       the copy-based fuse-overlayfs stand-in, used only when P6_FUSE_DEV is absent
#                          (default: this adapter's fuse_overlayfs_shim.sh in the pushed/cloned control-loop tree)
#   P6_FUSE_SHIM_DEST      where the shim is installed (default /usr/local/bin/fuse-overlayfs)
#   P6_FUSE_MODE_FILE      "real" or "shim" is written here (default /workspace/p6_fuse_mode; pins.md states it per pod)
#   P6_PYTHON              the interpreter python3 is pointed at (default python3.11, arena.def's)
#   P6_TORCH_VERSION       torch to install (default 2.10.0, arena.def via vllm 0.17.0)
#   P6_TORCH_INDEX         wheel index for it (default empty = PyPI, as arena.def; set a URL only to override)
#   P6_TRANSFORMERS_VERSION  transformers to install (default 4.53.3, Amendment 2026-10-22 (5))
#   P6_EXPECT_TORCH / P6_EXPECT_TORCH_CUDA / P6_EXPECT_NVCC / P6_EXPECT_PY / P6_EXPECT_TRANSFORMERS
#                          versions the setup and the smoke test require (2.10 / 12.8 / 12.9 / 3.11 prefixes;
#                          transformers exact, default $P6_TRANSFORMERS_VERSION)
#   P6_IMAGE_MARKER        the prebuilt image's version record (default /etc/p6_image.json; tests point it elsewhere)
#   P6_BAKED_RA / P6_BAKED_HF  where the prebuilt image holds the ResearchArena checkout and the HF cache
#                          (default /opt/ResearchArena, /opt/hf)
#   P6_CUDA_HOME           CUDA toolkit root (default /usr/local/cuda; /usr/local/cuda-12.9 if step 1 installs it)
#   P6_TORCH_CUDA_ARCH_LIST  arena.def's %environment value (default 8.0;8.9;9.0)
#   P6_ENV_FILE            CUDA_HOME / PATH / TORCH_CUDA_ARCH_LIST exports (default /workspace/p6_env.sh); a line
#                          sourcing it is appended to P6_RP_ENV (default /etc/rp_environment), which every ssh
#                          session of pods.py sources (run_prelude), so episodes see the same toolchain as setup
#   P6_COMPILE_LOG         full stdout+stderr of `bench.sh --compile-only` (compile_check; step 7 writes
#                          /workspace/p6_setup_compile.log, the smoke test /workspace/p6_compile.log)
#   P6_BUILD_TMP           where bench.py builds (/tmp, hard-coded in bench.py 126; tests only)
#   P6_RUN_ONLY            tests only: run this one function (e.g. fuse_setup) and exit, no steps
set -euo pipefail
# 2026-10-25 (Amendment (23) item 6): RunPod's /etc/rp_environment carries a pod-scoped RUNPOD_API_KEY that can read
# every pod of the account, env values included (measured on two CPU test pods). It is 644 by default: make it root-only.
chmod 600 /etc/rp_environment 2>/dev/null || true

: "${RESEARCHARENA_COMMIT:=58776e09339c1714d0524130590abaf6eac7879d}"
: "${CONTROL_LOOP_COMMIT:=local}"
: "${CONTROL_LOOP_REPO:=https://github.com/HemantBK/control-loop}"
: "${OPENCODE_VERSION:=}"
: "${WORKSPACE:=/workspace}"
: "${ARENA_ROOT:=$WORKSPACE/arena_root}"
: "${ARENA_RESULTS_DIR:=$WORKSPACE/results}"
: "${HF_HOME:=$WORKSPACE/hf}"
: "${P6_PAYLOAD_DIR:=$WORKSPACE/p6}"
: "${P6_STATE:=$WORKSPACE/p6/.setup_done}"
RA_DIR="$WORKSPACE/src/ResearchArena"
CL_DIR="$WORKSPACE/src/control-loop"
: "${P6_FUSE_DEV:=/dev/fuse}"
: "${P6_FUSE_SHIM_SRC:=$CL_DIR/control_loop/adapters/researcharena/fuse_overlayfs_shim.sh}"
: "${P6_FUSE_SHIM_DEST:=/usr/local/bin/fuse-overlayfs}"
: "${P6_FUSE_MODE_FILE:=$WORKSPACE/p6_fuse_mode}"
: "${P6_PYTHON:=python3.11}"
: "${P6_TORCH_VERSION:=2.10.0}"
: "${P6_TORCH_INDEX:=}"
: "${P6_TRANSFORMERS_VERSION:=4.53.3}"
: "${P6_EXPECT_TRANSFORMERS:=$P6_TRANSFORMERS_VERSION}"
: "${P6_HF_TRANSFER_VERSION:=0.1.9}"     # Amendment 2026-10-23 (10)
: "${P6_IMAGE_MARKER:=/etc/p6_image.json}"
: "${P6_BAKED_RA:=/opt/ResearchArena}"
: "${P6_BAKED_HF:=/opt/hf}"
: "${P6_EXPECT_TORCH:=2.10}"
: "${P6_EXPECT_TORCH_CUDA:=12.8}"
: "${P6_EXPECT_NVCC:=12.9}"
: "${P6_EXPECT_PY:=3.11}"
: "${P6_CUDA_HOME:=/usr/local/cuda}"
: "${P6_TORCH_CUDA_ARCH_LIST:=8.0;8.9;9.0}"
: "${P6_ENV_FILE:=$WORKSPACE/p6_env.sh}"
: "${P6_RP_ENV:=/etc/rp_environment}"
: "${P6_SETUP_COMPILE_LOG:=$WORKSPACE/p6_setup_compile.log}"
: "${P6_COMPILE_LOG:=$WORKSPACE/p6_compile.log}"
: "${P6_BUILD_TMP:=/tmp}"
# a second run (or a later function call) sees the toolchain step 1 chose
if [ -f "$P6_ENV_FILE" ]; then . "$P6_ENV_FILE"; fi
export DEBIAN_FRONTEND=noninteractive HF_HOME ARENA_ROOT ARENA_RESULTS_DIR TOKENIZERS_PARALLELISM=false
mkdir -p "$P6_STATE" "$ARENA_RESULTS_DIR" "$HF_HOME" "$P6_PAYLOAD_DIR" "$WORKSPACE/src"

T_ALL=$(date +%s)
log() { printf '[pod_setup %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
step() {   # step <name> <command...>: run once, time it
  local name="$1"; shift
  if [ -e "$P6_STATE/$name" ]; then log "step $name: already done, skipped"; return 0; fi
  local t0; t0=$(date +%s)
  log "step $name: start"
  if "$@"; then
    touch "$P6_STATE/$name"
    log "step $name: done in $(( $(date +%s) - t0 )) s"
  else
    log "step $name: FAILED after $(( $(date +%s) - t0 )) s"; return 1
  fi
}

# The HF-cache overlay (ResearchArena src/utils/hf_overlay.sh) needs a `fuse-overlayfs` on PATH. RunPod Secure Cloud
# pods have no /dev/fuse (smoke 2026-10-21), so without the device the copy-based shim stands in: same invocation,
# merged = a copy of the cache, writes stay in the copy, teardown's rm -rf removes it (FUSE_NOTES.md). The mode is
# logged and written to $P6_FUSE_MODE_FILE so each pod's mode is on record.
fuse_mode() { if [ -e "$P6_FUSE_DEV" ]; then echo real; else echo shim; fi; }

fuse_selftest() {   # fuse_selftest <real|shim>: lower file visible in merged; writes in merged never reach lower; rm -rf cleans
  local mode="$1" d; d=$(mktemp -d)
  mkdir -p "$d/lower" "$d/upper" "$d/work" "$d/merged" && echo x > "$d/lower/x"
  fuse-overlayfs -o "lowerdir=$d/lower,upperdir=$d/upper,workdir=$d/work" "$d/merged" || { log "fuse-overlayfs ($mode) failed"; return 1; }
  [ "$(cat "$d/merged/x")" = x ] || { log "fuse-overlayfs ($mode): lower file not visible in merged"; return 1; }
  echo y > "$d/merged/y"; echo more >> "$d/merged/x"
  [ ! -e "$d/lower/y" ] && [ "$(cat "$d/lower/x")" = x ] || { log "fuse-overlayfs ($mode): a write in merged reached lower"; return 1; }
  if [ "$mode" = real ]; then fusermount -u "$d/merged" 2>/dev/null || umount "$d/merged"; fi
  rm -rf "$d"
  [ ! -e "$d" ] || { log "fuse-overlayfs ($mode): overlay dir not removable"; return 1; }
  log "fuse-overlayfs ($mode) self-test ok"
}

fuse_setup() {
  local mode; mode=$(fuse_mode)
  if [ "$mode" = real ]; then
    command -v fuse-overlayfs >/dev/null 2>&1 || { log "fuse-overlayfs package missing"; return 1; }
  else
    if [ ! -f "$P6_FUSE_SHIM_SRC" ] && [ "$CONTROL_LOOP_COMMIT" != local ]; then   # the clone normally happens in step 4
      [ -d "$CL_DIR/.git" ] || git clone -q "$CONTROL_LOOP_REPO" "$CL_DIR"
      git -C "$CL_DIR" fetch -q --all && git -C "$CL_DIR" checkout -q "$CONTROL_LOOP_COMMIT"
    fi
    [ -f "$P6_FUSE_SHIM_SRC" ] || { log "no $P6_FUSE_DEV and no shim at $P6_FUSE_SHIM_SRC"; return 1; }
    mkdir -p "$(dirname "$P6_FUSE_SHIM_DEST")"
    install -m 755 "$P6_FUSE_SHIM_SRC" "$P6_FUSE_SHIM_DEST"
    [ "$(command -v fuse-overlayfs)" = "$P6_FUSE_SHIM_DEST" ] || { log "shim installed at $P6_FUSE_SHIM_DEST but PATH resolves fuse-overlayfs to $(command -v fuse-overlayfs || echo nothing)"; return 1; }
  fi
  fuse_selftest "$mode" || return 1
  mkdir -p "$(dirname "$P6_FUSE_MODE_FILE")"; echo "$mode" > "$P6_FUSE_MODE_FILE"
  if [ "$mode" = real ]; then log "fuse: real"; else log "fuse: shim (no $P6_FUSE_DEV)"; fi
}

# The toolchain every later step and every episode uses (arena.def %environment: CUDA_HOME=/usr/local/cuda,
# TORCH_CUDA_ARCH_LIST="8.0;8.9;9.0"). smoke3's compile ran with CUDA_HOME unset and nvcc reached through a
# /usr/local/bin/nvcc symlink, so torch.utils.cpp_extension derived CUDA_HOME=/usr/local (its compile line shows
# `-isystem /usr/local/include`, no CUDA include dir); the symlink is no longer made and CUDA_HOME is exported.
nvcc_release() { { "$1" --version 2>/dev/null || true; } | sed -n 's/.*release \([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -1 || true; }

write_env_file() {
  mkdir -p "$(dirname "$P6_ENV_FILE")"
  cat > "$P6_ENV_FILE" <<EOF
# written by pod_setup.sh (Phase 6, PLAN Amendment 2026-10-22 (2)); sourced through $P6_RP_ENV by every ssh session
export CUDA_HOME=$P6_CUDA_HOME
case ":\$PATH:" in *":$P6_CUDA_HOME/bin:"*) ;; *) export PATH="$P6_CUDA_HOME/bin:\$PATH" ;; esac
export TORCH_CUDA_ARCH_LIST="$P6_TORCH_CUDA_ARCH_LIST"
EOF
  local line="if [ -f $P6_ENV_FILE ]; then . $P6_ENV_FILE; fi"
  mkdir -p "$(dirname "$P6_RP_ENV")"; touch "$P6_RP_ENV"
  grep -qxF "$line" "$P6_RP_ENV" || echo "$line" >> "$P6_RP_ENV"
  . "$P6_ENV_FILE"
}

# 1. system packages, fuse (real or shim), nvidia-smi, the CUDA toolkit (nvcc 12.9)
step1() {
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends git rsync curl ca-certificates >/dev/null
  if [ "$(fuse_mode)" = real ]; then apt-get install -y -qq --no-install-recommends fuse-overlayfs >/dev/null; fi
  local rel; rel=$(nvcc_release "$P6_CUDA_HOME/bin/nvcc")
  if [ "$rel" != "$P6_EXPECT_NVCC" ]; then
    local pkg="cuda-toolkit-${P6_EXPECT_NVCC//./-}"
    log "nvcc under $P6_CUDA_HOME is '${rel:-absent}', not $P6_EXPECT_NVCC: installing $pkg from NVIDIA's apt repo (+3-5 min, +3 GB)"
    . /etc/os-release
    local distro="ubuntu$(echo "$VERSION_ID" | tr -d .)"
    curl -fsSL -o /tmp/cuda-keyring.deb "https://developer.download.nvidia.com/compute/cuda/repos/${distro}/x86_64/cuda-keyring_1.1-1_all.deb"
    dpkg -i /tmp/cuda-keyring.deb >/dev/null
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends "$pkg" >/dev/null
    P6_CUDA_HOME="/usr/local/cuda-$P6_EXPECT_NVCC"
    rel=$(nvcc_release "$P6_CUDA_HOME/bin/nvcc")
    [ "$rel" = "$P6_EXPECT_NVCC" ] || { log "after installing $pkg, $P6_CUDA_HOME/bin/nvcc reports '${rel:-nothing}'"; return 1; }
  fi
  write_env_file
  log "CUDA_HOME=$CUDA_HOME nvcc=$(command -v nvcc) release $rel; TORCH_CUDA_ARCH_LIST=$TORCH_CUDA_ARCH_LIST; env file $P6_ENV_FILE (sourced from $P6_RP_ENV)"
  nvcc --version | tail -2
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
  fuse_setup   # hf_overlay.sh needs a fuse-overlayfs on PATH (PLAN §1.1): the real one, or the shim when /dev/fuse is absent
}

# 2. node 22 + opencode
step2() {
  if ! command -v node >/dev/null 2>&1 || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 22 ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null
    apt-get install -y -qq nodejs >/dev/null
  fi
  node --version
  if [ -n "$OPENCODE_VERSION" ]; then npm install -g "opencode-ai@${OPENCODE_VERSION}" >/dev/null
  else npm install -g opencode-ai >/dev/null; fi
  opencode --version
  # benchmark change 10 (PLAN Amendment (34)) sets the agent's command timeout through this variable: fail if this
  # opencode does not read it
  grep -aq OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS "$(readlink -f "$(command -v opencode)")" \
    || { echo "OPENCODE_IGNORES_TIMEOUT_VAR: change 10 would not reach this opencode"; return 1; }
}

# Versions the phase requires (Amendment 2026-10-22 (2); transformers exact since Amendment (5)): python, torch,
# torch's CUDA, nvcc, transformers, and the CUDA_HOME torch.utils.cpp_extension will build with. Prints one line; non-zero on any mismatch. Used by step 3 and smoke_test.sh.
versions_check() {
  local nv; nv=$(nvcc_release "${CUDA_HOME:-$P6_CUDA_HOME}/bin/nvcc")
  python3 - "$P6_EXPECT_PY" "$P6_EXPECT_TORCH" "$P6_EXPECT_TORCH_CUDA" "$P6_EXPECT_NVCC" "${nv:-absent}" "$P6_EXPECT_TRANSFORMERS" <<'PY'
import os, sys
want_py, want_torch, want_cuda, want_nvcc, nvcc, want_tf = sys.argv[1:7]
py = "%d.%d" % sys.version_info[:2]
bad = []
try:
    import torch
    from torch.utils import cpp_extension as ce
    tv, tc, home = torch.__version__, torch.version.cuda, ce.CUDA_HOME
except Exception as e:  # torch missing or broken
    tv = tc = home = None
    bad.append(f"import torch failed: {type(e).__name__}: {e}")
try:
    import transformers
    tf = transformers.__version__
except Exception as e:
    tf = None
    bad.append(f"import transformers failed: {type(e).__name__}: {e}")
print(f"python {py} ({sys.executable}) torch {tv} torch.version.cuda {tc} nvcc {nvcc} cpp_extension.CUDA_HOME {home} "
      f"transformers {tf} TORCH_CUDA_ARCH_LIST={os.environ.get('TORCH_CUDA_ARCH_LIST')}")
if tf is not None and tf != want_tf: bad.append(f"transformers {tf} != {want_tf}")
if py != want_py: bad.append(f"python {py} != {want_py}")
if tv is not None and not (tv == want_torch or tv.startswith(want_torch + ".")): bad.append(f"torch {tv} is not {want_torch}.x")
if tv is not None and not (tc == want_cuda or str(tc).startswith(want_cuda + ".")): bad.append(f"torch.version.cuda {tc} != {want_cuda}")
if nvcc != want_nvcc: bad.append(f"nvcc release {nvcc} != {want_nvcc}")
if tv is not None and (not home or not os.path.isfile(os.path.join(home, "include", "cuda_runtime.h"))):
    bad.append(f"cpp_extension.CUDA_HOME={home} has no include/cuda_runtime.h")
if bad:
    print("VERSION MISMATCH: " + "; ".join(bad)); sys.exit(1)
PY
}

# 3. python + packages: python3 -> python3.11, torch 2.10.0 from PyPI (CUDA 12.8 runtime, as arena.def),
#    transformers 4.53.3 (Amendment 2026-10-22 (5); was 5.3.0)
step3() {
  local py; py=$(command -v "$P6_PYTHON") || { log "$P6_PYTHON not in the image (runpod/base ships deadsnakes 3.9-3.13)"; return 1; }
  # every later `python3` (bench.sh's `exec python3`, pipeline_redteam.sh, the arena_root CLI) is this interpreter;
  # arena.def does the same with `ln -sf /usr/bin/python3.11 /usr/bin/python3` (/usr/bin/python3 is left to apt here)
  ln -sf "$py" /usr/local/bin/python3; ln -sf "$py" /usr/local/bin/python; hash -r
  [ "$(command -v python3)" = /usr/local/bin/python3 ] || { log "python3 resolves to $(command -v python3), not /usr/local/bin/python3 (PATH=$PATH)"; return 1; }
  # 2026-10-22: externally managed (PEP 668) system Pythons refused --system installs in smoke2; the override stays
  command -v uv >/dev/null 2>&1 || python3 -m pip install -q --break-system-packages uv
  if [ -n "$P6_TORCH_INDEX" ]; then
    uv pip install --system --python "$py" --break-system-packages -q --index-url "$P6_TORCH_INDEX" "torch==$P6_TORCH_VERSION"
  else
    uv pip install --system --python "$py" --break-system-packages -q "torch==$P6_TORCH_VERSION"   # PyPI, as arena.def
  fi
  # 2026-10-23, Amendment (10): runpod/base sets HF_HUB_ENABLE_HF_TRANSFER=1 in /etc/rp_environment, which the benchmark
  # and the episodes source; with transformers 4.53.3 loading TinyLlama then needs hf_transfer (debug7 crashed without it)
  uv pip install --system --python "$py" --break-system-packages -q "transformers==$P6_TRANSFORMERS_VERSION" accelerate ninja huggingface-hub \
    "hf_transfer==$P6_HF_TRANSFER_VERSION"
  python3 -c "import torch, transformers, hf_transfer; print('torch', torch.__version__, 'cuda', torch.version.cuda, torch.cuda.is_available(), 'transformers', transformers.__version__, 'hf_transfer ok')"
  versions_check
}

# 4. the two pinned checkouts
step4() {
  if [ ! -d "$RA_DIR/.git" ]; then git clone -q https://github.com/aisa-group/ResearchArena "$RA_DIR"; fi
  git -C "$RA_DIR" fetch -q --all && git -C "$RA_DIR" checkout -q "$RESEARCHARENA_COMMIT"
  log "ResearchArena at $(git -C "$RA_DIR" rev-parse HEAD)"
  cl_checkout
}

cl_checkout() {   # the control-loop tree: pushed by pods.py ("local") or cloned at CONTROL_LOOP_COMMIT
  if [ "$CONTROL_LOOP_COMMIT" = local ]; then
    # the tree was pushed by pods.py (tar over ssh) before this script ran: the adapter is not yet in any remote
    [ -d "$CL_DIR/control_loop/adapters/researcharena" ] || { log "local control_loop tree missing under $CL_DIR"; return 1; }
    log "control-loop: local tree pushed by pods.py ($(find "$CL_DIR/control_loop" -name '*.py' | wc -l) files)"
  else
    if [ ! -d "$CL_DIR/.git" ]; then git clone -q "$CONTROL_LOOP_REPO" "$CL_DIR"; fi
    git -C "$CL_DIR" fetch -q --all && git -C "$CL_DIR" checkout -q "$CONTROL_LOOP_COMMIT"
    log "control-loop at $(git -C "$CL_DIR" rev-parse HEAD)"
  fi
}

# --- prebuilt image (PLAN Amendment 2026-10-22 (4); docker/phase6/) ---------------------------------------------------
# The image bakes steps 1-6 into image layers (a /workspace volume mounted at runtime would hide anything put there)
# and records what it holds in $P6_IMAGE_MARKER. baked_match compares that record with what this run expects; only on
# an exact match are steps 1-6 skipped. Anything else (no record, unreadable record, any version or commit differs)
# runs steps 1-6 as on a plain image, with the reason logged.
BAKED_TAG=""
baked_match() {
  [ -f "$P6_IMAGE_MARKER" ] || { log "no $P6_IMAGE_MARKER: not the prebuilt image, steps 1-6 run"; return 1; }
  local out
  out=$(P6_M_PY="$P6_EXPECT_PY" P6_M_TORCH="$P6_TORCH_VERSION" P6_M_TF="$P6_TRANSFORMERS_VERSION" \
        P6_M_OC="$OPENCODE_VERSION" P6_M_RA="$RESEARCHARENA_COMMIT" python3 - "$P6_IMAGE_MARKER" <<'PY' 2>&1
import json, os, sys
try:
    m = json.load(open(sys.argv[1]))
except Exception as e:
    print("MISMATCH unreadable marker: %s: %s" % (type(e).__name__, e)); sys.exit(1)
want = {"python": os.environ["P6_M_PY"], "torch": os.environ["P6_M_TORCH"], "transformers": os.environ["P6_M_TF"],
        "researcharena_commit": os.environ["P6_M_RA"]}
if os.environ["P6_M_OC"]:            # OPENCODE_VERSION unset = "latest" on a plain image; the baked pin is accepted
    want["opencode"] = os.environ["P6_M_OC"]
bad = []
for k, v in want.items():
    got = str(m.get(k, ""))
    ok = got == v or (k == "torch" and got.startswith(v + "+"))
    if not ok:
        bad.append("%s %r != expected %r" % (k, got or None, v))
if not m.get("tinyllama_snapshot"):
    bad.append("no tinyllama_snapshot recorded")
if bad:
    print("MISMATCH " + "; ".join(bad)); sys.exit(1)
print("MATCH %s" % (m.get("image_tag") or "untagged"))
PY
) || { log "prebuilt image record $P6_IMAGE_MARKER does not match this run (${out#MISMATCH }): steps 1-6 run"; return 1; }
  BAKED_TAG="${out#MATCH }"
  return 0
}

baked_link() {   # baked_link <image path> <expected path>: a symlink to the image's copy (an empty dir is replaced)
  local src="$1" dst="$2"
  [ -d "$src" ] || { log "prebuilt image has no $src"; return 1; }
  if [ -L "$dst" ] || [ ! -e "$dst" ]; then
    mkdir -p "$(dirname "$dst")" && ln -sfn "$src" "$dst" || return 1
  elif [ -d "$dst" ] && [ -z "$(ls -A "$dst")" ]; then
    rmdir "$dst" && ln -s "$src" "$dst" || return 1
  else
    log "$dst already holds files: kept as is (not linked to $src)"; return 0
  fi
  log "$dst -> $(readlink "$dst")"
}

baked_links() {   # the checkout and the HF cache at the paths steps 5, 7, smoke_test.sh and episodes use
  baked_link "$P6_BAKED_RA" "$RA_DIR" || return 1
  local head; head=$(git -C "$RA_DIR" rev-parse HEAD 2>/dev/null) || { log "$RA_DIR is not a git checkout"; return 1; }
  [ "$head" = "$RESEARCHARENA_COMMIT" ] || { log "ResearchArena at $head, expected $RESEARCHARENA_COMMIT"; return 1; }
  log "ResearchArena at $head (prebuilt image)"
  baked_link "$P6_BAKED_HF" "$HF_HOME" || return 1
  [ -d "$HF_HOME/hub/models--TinyLlama--TinyLlama-1.1B-Chat-v1.0/snapshots" ] || { log "no TinyLlama snapshot under $HF_HOME/hub"; return 1; }
  log "HF_HOME $HF_HOME holds TinyLlama (prebuilt image)"
}

# 0. prebuilt image: the runtime parts of step 1 (toolchain env file, FUSE mode), the version check of step 3, the
#    links in place of steps 4 and 6, and the control-loop tree (step 4)
baked_setup() {
  local rel; rel=$(nvcc_release "$P6_CUDA_HOME/bin/nvcc")
  [ "$rel" = "$P6_EXPECT_NVCC" ] || { log "prebuilt image: nvcc under $P6_CUDA_HOME is '${rel:-absent}', not $P6_EXPECT_NVCC"; return 1; }
  write_env_file || return 1
  log "CUDA_HOME=$CUDA_HOME nvcc=$(command -v nvcc) release $rel; TORCH_CUDA_ARCH_LIST=$TORCH_CUDA_ARCH_LIST; env file $P6_ENV_FILE (sourced from $P6_RP_ENV)"
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || return 1
  fuse_setup || return 1
  [ "$(command -v python3)" = /usr/local/bin/python3 ] || { log "python3 resolves to $(command -v python3), not /usr/local/bin/python3"; return 1; }
  versions_check || return 1
  node --version && opencode --version || return 1
  baked_links || return 1
  cl_checkout
}

# the steps of this run, in order (tests: P6_RUN_ONLY=print_plan)
P6_PLAN=""
choose_plan() {
  if baked_match; then
    P6_PLAN="0_baked 5_arena_root 7_smoke"
    log "baked image $BAKED_TAG: steps 1-6 skipped"
  else
    P6_PLAN="1_system 2_node_opencode 3_python 4_checkouts 5_arena_root 6_tinyllama 7_smoke"
  fi
}
print_plan() { choose_plan; echo "PLAN $P6_PLAN"; }

# 5. composed arena root (PLAN §1.4) + verify. The payload file is written by pods.py per episode; at setup time
#    the stock independent/side_task.md stands in so the root is complete.
step5() {
  mkdir -p "$P6_PAYLOAD_DIR"
  [ -s "$P6_PAYLOAD_DIR/payload.txt" ] || cp "$RA_DIR/settings/cuda_kernel/side_tasks/independent/side_task.md" "$P6_PAYLOAD_DIR/payload.txt"
  export PYTHONPATH="$CL_DIR${PYTHONPATH:+:$PYTHONPATH}" RESEARCHARENA_ROOT="$RA_DIR"
  if [ -n "${ARENA_BUILD_CMD:-}" ]; then bash -c "$ARENA_BUILD_CMD"
  else
    ( cd "$CL_DIR" && python3 -m control_loop.adapters.researcharena.arena_root build "$ARENA_ROOT" \
        --checkout "$RA_DIR" --payload-file "$P6_PAYLOAD_DIR/payload.txt" )
    ( cd "$CL_DIR" && python3 -m control_loop.adapters.researcharena.arena_root verify "$ARENA_ROOT" --checkout "$RA_DIR" )
  fi
  [ -f "$ARENA_ROOT/run_redteam.sh" ] || { log "composed root has no run_redteam.sh"; return 1; }
}

# 6. TinyLlama into HF_HOME. runpod/base sets HF_HUB_ENABLE_HF_TRANSFER=1 but installs hf_transfer for python3.12
#    only; huggingface_hub 0.x (the range transformers 4.53.3 requires; 0.36.2 read on the CPU pod) raises ValueError
#    on a plain-HTTP download with the flag set and the package missing, so the download runs with it off.
step6() {
  HF_HUB_ENABLE_HF_TRANSFER=0 python3 - <<'PY'
import os
from huggingface_hub import snapshot_download
p = snapshot_download("TinyLlama/TinyLlama-1.1B-Chat-v1.0")
print("TinyLlama at", p, "HF_HOME", os.environ.get("HF_HOME"))
PY
}

# The starter-kernel compile, judged by its artefact (Amendment 2026-10-22 (2)). smoke3's `bench.sh --compile-only`
# printed "ninja: build stopped: subcommand failed." and exited 0: bench.py returns its result dict on a compile
# failure and exits 0 (bench.py 173-179, 297-310). PASS only if a fresh agent_ops.so exists under
# /tmp/arena_build_<pid>/ (bench.py 126, torch.utils.cpp_extension.load(name="agent_ops", build_directory=...),
# bench.py 138-145) and bench printed COMPILE_STATUS=PASS; the exit code is recorded, not trusted. The full
# stdout+stderr goes to $P6_COMPILE_LOG (pods.py collects it); a FAIL prints the error lines and the last 40 lines.
# The build runs in the composed root's real task_context copy; afterwards the generated workspace/ and
# __pycache__/ are removed, so the copy equals the checkout again before an episode's pipeline_redteam.sh:146
# `cp -r task_context/*` (bench's own last_bench.json is appended to the log first).
compile_check() {
  local tc="$ARENA_ROOT/settings/cuda_kernel/task_context" log_f="$P6_COMPILE_LOG" stamp so rc=0
  if [ -L "$tc" ] || [ ! -d "$tc" ]; then
    echo "compile FAILED: $tc is not a real directory (the composed root must hold a copy; Amendment 2026-10-22 (2))"; return 1
  fi
  mkdir -p "$(dirname "$log_f")"
  stamp=$(mktemp); sleep 1
  { echo "# compile_check $(date -u +%FT%TZ): cd $tc && bash bench.sh --compile-only"
    echo "# CUDA_HOME=${CUDA_HOME:-unset} TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST:-unset} python3=$(command -v python3)"; } > "$log_f"
  ( cd "$tc" && bash bench.sh --compile-only ) >> "$log_f" 2>&1 || rc=$?
  so=$(find "$P6_BUILD_TMP" -maxdepth 2 -type f -name 'agent_ops.so' -path '*/arena_build_*' -newer "$stamp" 2>/dev/null | head -1 || true)
  rm -f "$stamp"
  if [ -f "$tc/workspace/last_bench.json" ]; then
    { echo "--- task_context/workspace/last_bench.json ---"; cat "$tc/workspace/last_bench.json"; echo; } >> "$log_f"
  fi
  rm -rf "$tc/workspace"; find "$tc" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
  echo "--- compile_check: bench.sh rc=$rc, artefact ${so:-none} ---" >> "$log_f"
  if [ -n "$so" ] && grep -q '^COMPILE_STATUS=PASS' "$log_f"; then
    echo "compile ok: $so ($(stat -c %s "$so" 2>/dev/null || wc -c < "$so") bytes; bench rc=$rc; full log $log_f)"
    return 0
  fi
  echo "compile FAILED: bench.sh rc=$rc, no fresh agent_ops.so under $P6_BUILD_TMP/arena_build_*$(grep -q '^COMPILE_STATUS=PASS' "$log_f" || echo ', no COMPILE_STATUS=PASS'); full log $log_f"
  echo "--- error lines ---"
  grep -n -E 'error|Error|FAILED|COMPILE_' "$log_f" | head -25 || true
  echo "--- last 40 lines ---"
  tail -40 "$log_f"
  return 1
}

# 7. smoke: dry run of the pipeline and the starter-kernel compile (not marked done: cheap, re-run every time)
step7() {
  ( cd "$ARENA_ROOT" && bash run_redteam.sh --setting cuda_kernel --side_task payload --redruntime 0.01 \
      --redteammodel opencode_or:openrouter/qwen/qwen3-235b-a22b-2507 --seed 733 --experiment phase6_setup_dryrun \
      --cluster_id setup --task_config tinyllama --dry_run ) | tail -5
  P6_COMPILE_LOG="$P6_SETUP_COMPILE_LOG" compile_check
}

if [ -n "${P6_RUN_ONLY:-}" ]; then "$P6_RUN_ONLY"; exit $?; fi   # tests: one function, no steps

choose_plan
for s in $P6_PLAN; do
  case "$s" in
    0_baked) step 0_baked baked_setup ;;
    7_smoke) rm -f "$P6_STATE/7_smoke"; step 7_smoke step7 ;;
    *) step "$s" "step${s%%_*}" ;;
  esac
done
log "setup complete in $(( $(date +%s) - T_ALL )) s"
