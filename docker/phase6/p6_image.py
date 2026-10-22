"""Version record and version check of the Phase 6 prebuilt image (PLAN Amendments 2026-10-22 (4), (5)).

    python3 p6_image.py record <marker path>   write the JSON record pod_setup.sh's baked_match reads
    python3 p6_image.py check  <marker path>   print the versions; exit 1 on any mismatch with the build's pins

Both read the pins from the environment the Dockerfile sets for the RUN (build args, never secrets):
P6_PYTHON_EXPECT, TORCH_VERSION, TORCH_CUDA_EXPECT, NVCC_EXPECT, TRANSFORMERS_VERSION, OPENCODE_VERSION,
RESEARCHARENA_COMMIT, RA_DIR, HF_HOME, TINYLLAMA_MODEL, TINYLLAMA_REVISION, IMAGE_TAG, GIT_SHA, BUILD_DATE, BASE_IMAGE.
No GPU is needed: torch.version.cuda is the wheel's CUDA runtime, nvcc is read from $CUDA_HOME/bin/nvcc.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import sysconfig
from importlib import metadata


def run(*argv: str) -> str:
    return subprocess.run(argv, capture_output=True, text=True, check=True).stdout.strip()


def nvcc_release() -> str | None:
    out = run(os.path.join(os.environ["CUDA_HOME"], "bin", "nvcc"), "--version")
    m = re.search(r"release (\d+\.\d+)", out)
    return m.group(1) if m else None


def tinyllama_snapshot() -> str | None:
    model = os.environ["TINYLLAMA_MODEL"]
    d = os.path.join(os.environ["HF_HOME"], "hub", "models--" + model.replace("/", "--"))
    try:
        ref = open(os.path.join(d, "refs", "main")).read().strip()
    except OSError:
        return None
    return ref if os.path.isdir(os.path.join(d, "snapshots", ref)) else None


def actual() -> dict:
    import torch
    import transformers
    from torch.utils import cpp_extension as ce
    ra = os.environ["RA_DIR"]
    return {
        "python": "%d.%d" % sys.version_info[:2],
        "python_full": sys.version.split()[0],
        "python_executable": os.path.realpath(sys.executable),
        "site_packages": sysconfig.get_paths()["purelib"],
        "torch": metadata.version("torch"),
        "torch_full": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cpp_extension_cuda_home": ce.CUDA_HOME,
        "nvcc": nvcc_release(),
        "cuda_home": os.environ["CUDA_HOME"],
        "torch_cuda_arch_list": os.environ.get("TORCH_CUDA_ARCH_LIST"),
        "transformers": transformers.__version__,
        "accelerate": metadata.version("accelerate"),
        "ninja": metadata.version("ninja"),
        "huggingface_hub": metadata.version("huggingface-hub"),
        "node": run("node", "--version").lstrip("v"),
        "npm": run("npm", "--version"),
        "opencode": run("opencode", "--version").split()[-1],
        "researcharena_commit": run("git", "-C", ra, "rev-parse", "HEAD"),
        "researcharena_clean": run("git", "-C", ra, "status", "--porcelain") == "",
        "researcharena_dir": ra,
        "hf_home": os.environ["HF_HOME"],
        "tinyllama_model": os.environ["TINYLLAMA_MODEL"],
        "tinyllama_snapshot": tinyllama_snapshot(),
    }


def problems(a: dict) -> list[str]:
    e = os.environ
    bad = []
    if a["python"] != e["P6_PYTHON_EXPECT"]:
        bad.append(f"python {a['python']} != {e['P6_PYTHON_EXPECT']}")
    if not (a["torch"] == e["TORCH_VERSION"] or a["torch"].startswith(e["TORCH_VERSION"] + "+")):
        bad.append(f"torch {a['torch']} != {e['TORCH_VERSION']}")
    if not str(a["torch_cuda"]).startswith(e["TORCH_CUDA_EXPECT"]):
        bad.append(f"torch.version.cuda {a['torch_cuda']} != {e['TORCH_CUDA_EXPECT']}")
    if a["nvcc"] != e["NVCC_EXPECT"]:
        bad.append(f"nvcc {a['nvcc']} != {e['NVCC_EXPECT']}")
    home = a["cpp_extension_cuda_home"]
    if not home or not os.path.isfile(os.path.join(home, "include", "cuda_runtime.h")):
        bad.append(f"cpp_extension.CUDA_HOME={home} has no include/cuda_runtime.h")
    if a["transformers"] != e["TRANSFORMERS_VERSION"]:
        bad.append(f"transformers {a['transformers']} != {e['TRANSFORMERS_VERSION']}")
    if a["opencode"] != e["OPENCODE_VERSION"]:
        bad.append(f"opencode {a['opencode']} != {e['OPENCODE_VERSION']}")
    if not a["node"].startswith("22."):
        bad.append(f"node {a['node']} is not 22.x")
    if a["researcharena_commit"] != e["RESEARCHARENA_COMMIT"] or not a["researcharena_clean"]:
        bad.append(f"ResearchArena at {a['researcharena_commit']} (clean={a['researcharena_clean']}), expected {e['RESEARCHARENA_COMMIT']}")
    if a["tinyllama_snapshot"] != e["TINYLLAMA_REVISION"]:
        bad.append(f"TinyLlama snapshot {a['tinyllama_snapshot']} != {e['TINYLLAMA_REVISION']}")
    return bad


def main(argv: list[str]) -> int:
    cmd, marker = argv[1], argv[2]
    a = actual()
    if cmd == "record":
        e = os.environ
        rec = dict(a, image_tag=e["IMAGE_TAG"], control_loop_git_sha=e["GIT_SHA"], build_date=e["BUILD_DATE"],
                   base_image=e["BASE_IMAGE"], plan="phases/phase6_researcharena/PLAN.md Amendments 2026-10-22 (4), (5)")
        with open(marker, "w") as f:
            json.dump(rec, f, indent=2, sort_keys=True)
            f.write("\n")
        print(json.dumps(rec, sort_keys=True))
        return 0
    rec = json.load(open(marker))
    print(" ".join(f"{k}={a[k]}" for k in ("python", "torch_full", "torch_cuda", "nvcc", "cpp_extension_cuda_home",
                                            "transformers", "node", "opencode", "researcharena_commit",
                                            "tinyllama_snapshot")))
    bad = problems(a)
    for k in ("python", "torch", "transformers", "opencode", "researcharena_commit", "tinyllama_snapshot"):
        if rec.get(k) != a[k]:
            bad.append(f"record {marker} says {k}={rec.get(k)!r}, image has {a[k]!r}")
    if bad:
        print("P6 IMAGE VERSION MISMATCH: " + "; ".join(bad))
        return 1
    print("P6 IMAGE VERSIONS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
