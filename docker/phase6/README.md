# Phase 6 prebuilt image

`ghcr.io/hemantbk/control-loop-phase6`. Public, like the repository. It holds only public packages, a public checkout
and public model weights. It exists because of PLAN Amendment 2026-10-22 (4) (prebuilt image, RunPod template, 20-minute
pod-ready wait) and is pinned by Amendment (5) (transformers 4.53.3).

## What the image holds

`Dockerfile` bakes steps 1–6 of `control_loop/adapters/researcharena/pod_setup.sh` into image layers. They are not put
under `/workspace`, because the pod's volume is mounted there at runtime and would hide them.

| pod_setup step | in the image |
|---|---|
| base | `runpod/base:1.4.1-cuda1290-ubuntu2204`: CUDA 12.9.0 devel + cuDNN, deadsnakes Python 3.9–3.13, `uv`, RunPod's sshd `start.sh` (kept as CMD) |
| 1 | `git rsync curl ca-certificates fuse-overlayfs`; `CUDA_HOME=/usr/local/cuda`, its `bin` first on `PATH`, `TORCH_CUDA_ARCH_LIST="8.0;8.9;9.0"` |
| 3 | `python3` and `python` → `/usr/bin/python3.11`; `torch==2.10.0` from PyPI (CUDA 12.8 runtime); `transformers==4.53.3`, plus accelerate, ninja, huggingface-hub and setuptools (unpinned; their versions are recorded) |
| 2 | node 22 (NodeSource) and `opencode-ai@1.19.3` |
| 4 | ResearchArena at `58776e09339c1714d0524130590abaf6eac7879d`, clean, in `/opt/ResearchArena` |
| 6 | `TinyLlama/TinyLlama-1.1B-Chat-v1.0` at revision `fe8a4ea1ffedaf415f4da2f062534de366a451e6`, in `HF_HOME=/opt/hf` |
| record | `/etc/p6_image.json` records every version, the ResearchArena commit, the TinyLlama snapshot, the image tag, the build date and this repository's git sha. `/etc/p6_scan.txt` holds the scan report. |

The image also sets `HF_HUB_ENABLE_HF_TRANSFER=0`. runpod/base sets it to 1 but installs `hf_transfer` only for
python3.12. huggingface_hub 0.x is the range transformers 4.53.3 requires, and 0.36.2 raises `ValueError` on a plain
HTTP download when the flag is set and the package is missing.

Some things are deliberately left out:

- `control_loop/`: pods.py pushes the local tree to every pod.
- The composed arena root (step 5) and the compile check (step 7): these need that tree, so they run on every pod.
- Any secret, token or credential.

Size estimate: about 15–16 GB compressed and about 30–35 GB unpacked. That is the base at 10.1 GB compressed, plus
torch with its NVIDIA wheels at about 3 GB, plus TinyLlama at 2.2 GB, plus node and opencode at about 0.2 GB. The
template's container disk is 60 GB.

## Build inputs

| build arg | default | workflow input |
|---|---|---|
| `TRANSFORMERS_VERSION` | `4.53.3` | `transformers_version` (required, no default: type `4.53.3`) |
| `OPENCODE_VERSION` | `1.19.3` | `opencode_version` (default `1.19.3`) |
| `RESEARCHARENA_COMMIT` | `58776e09339c1714d0524130590abaf6eac7879d` | `researcharena_commit` (default the pin) |
| `TORCH_VERSION`, `NODE_MAJOR`, `TINYLLAMA_MODEL`, `TINYLLAMA_REVISION`, `BASE_IMAGE` | `2.10.0`, `22`, TinyLlama, `fe8a4ea…`, runpod/base 1.4.1 | fixed |
| `IMAGE_TAG`, `GIT_SHA`, `BUILD_DATE` | set by the workflow | recorded only |

The build fails when any of these is off:

- python 3.11
- torch 2.10.x with `torch.version.cuda` 12.8
- nvcc 12.9
- a `cpp_extension.CUDA_HOME` holding `include/cuda_runtime.h`
- transformers equal to the build arg
- opencode equal to the build arg
- node 22
- the ResearchArena HEAD equal to the pin, with a clean checkout
- the TinyLlama `refs/main` equal to the pinned revision

Two tags are pushed: `tf<transformers>-oc<opencode>-ra<first 7 of the commit>`, for example
`tf4.53.3-oc1.19.3-ra58776e0`, and `sha-<git sha of this repository>`. The workflow prints the digest. Record the
digest, because re-running the workflow with the same inputs moves the first tag.

## The scan (before any push)

The Dockerfile's `scan` stage runs `scan_image.py` with the base image's python. It reads the `env` stage's filesystem
through a read-only mount, with no network. The build fails on any of these:

1. A file named `.env` or `*.env` anywhere in the image. No exemption.
2. A string matching an API-key pattern anywhere in the image, binaries included: `sk-…`, `sk-ant-…`, `sk-or-…`,
   `ghp_…`, `github_pat_…`, `hf_…`, `rpa_…` or `AKIA…`, each with a left word boundary.
   - AWS's two documentation example ids are exempt.
   - Values listed by sha256 in `KNOWN_PUBLIC_SHA256` are exempt and printed as ALLOWED. Today there is one:
     Hugging Face's staging-CI token, published in `transformers/testing_utils.py` and marked there "only usable on the
     sandboxed CI instance".
3. A credential file: `/opt/hf/token`, `/opt/hf/stored_tokens`, `/root/.cache/huggingface/token`,
   `/root/.git-credentials`, `/root/.docker/config.json` or `/root/.npmrc`.
4. The string `/root/` in a text file under a path this Dockerfile writes:
   - The paths: `/opt/ResearchArena`, `/opt/hf`, `/etc/p6_image.json`, `/usr/local/share/p6`,
     `/usr/lib/node_modules/opencode-ai/package.json`, and the installer-written files (RECORD, INSTALLER, REQUESTED,
     direct_url.json) of every `*.dist-info` in `/usr/local/lib/python3.11/dist-packages`.
   - Allowed: upstream's three ResearchArena files, which hold PATH strings for the agent container:
     `containers/arena.def`, `src/pipeline_monitor.sh` and `src/pipeline_redteam.sh`.
   - Package authors' own text is not read. A `/root/` there would not come from this build.

A finding prints the path, the pattern name and the byte offset. It never prints the value.

The scan sees the final merged filesystem, not files that an earlier layer added and a later layer deleted. Every RUN
therefore cleans its own caches in the same layer, and no secret enters the build. Every download is anonymous.

## How pods use it

1. The manager creates a RunPod template from the image (owner's steps below) and exports `P6_TEMPLATE_ID=<id>`.
   `pods.py` reads the variable (`PodConfig.template_id`; `--template-id` on `pods smoke` and `pods diag`). With it
   set:
   - `runpodctl pod create` gets `--template-id <id>` instead of `--image`.
   - It gets `--container-disk-in-gb 60`.
   - The other fields and `--env` are sent as before. RunPod merges `env` per key, and create fields override the
     template's.
2. The pod-ready wait is `--wait-timeout 20m`, with a driver deadline of 1,200 s (owner's decision, Amendment (4)).
3. `pod_setup.sh` still runs.
   - When `/etc/p6_image.json` matches the run on python, torch, transformers, opencode (when `OPENCODE_VERSION` is
     set) and the ResearchArena commit, and records a TinyLlama snapshot, it logs
     `baked image <tag>: steps 1-6 skipped`. Step `0_baked` then:
     - writes `/workspace/p6_env.sh` and its line in `/etc/rp_environment`;
     - sets up FUSE or the shim;
     - checks the python link and the versions;
     - links `/workspace/src/ResearchArena` → `/opt/ResearchArena` and `/workspace/hf` → `/opt/hf`;
     - checks the pushed control-loop tree.

     Steps 5 (composed root) and 7 (dry run and compile check) run as on any pod.
   - Any mismatch, or no record at all, runs steps 1–6 as on a plain image and logs the reason.

## Owner's steps

1. **Commit and push** the image files. The workflow only appears under Actions once it is on the default branch
   (`main`). Pushing a file under `.github/workflows/` over HTTPS needs a token with the `workflow` scope; a normal
   `gh auth login` session has it.
   ```
   git add docker/phase6/Dockerfile docker/phase6/README.md docker/phase6/p6_image.py docker/phase6/scan_image.py .github/workflows/phase6-image.yml
   git commit -m "phase6: prebuilt image and build workflow"
   git push origin main
   ```
2. **Run the workflow.** Do this after the head-layout verdict, which is now in: transformers 4.53.3.
   - Go to github.com/HemantBK/control-loop → Actions → phase6-image → Run workflow.
   - Set `transformers_version` = `4.53.3` and leave the other two at their defaults.
   - Or, from a shell: `gh workflow run phase6-image.yml -R HemantBK/control-loop -f transformers_version=4.53.3`.
   - The job summary shows the tag and the digest.
3. **Make the package public, once, after the first push.** GHCR creates a new package as private, even from a public
   repository. The package inherits the repository's access permissions, not its visibility. GitHub's REST API has no
   endpoint to change package visibility, so `GITHUB_TOKEN` cannot do it from the workflow.
   - Go to github.com/users/HemantBK/packages/container/package/control-loop-phase6 → Package settings → Danger Zone
     → Change visibility → Public. Type the package name and confirm.
   - GitHub says a public package cannot be made private again.
   - Check it: the workflow's last step, "Package visibility", reports whether an anonymous pull works. On a re-run, or
     from any shell:
     ```
     tok=$(curl -s "https://ghcr.io/token?scope=repository:hemantbk/control-loop-phase6:pull" | jq -r .token)
     curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $tok" -H "Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json" https://ghcr.io/v2/hemantbk/control-loop-phase6/manifests/tf4.53.3-oc1.19.3-ra58776e0
     ```
     `200` means public. A private or missing package gives `403` at the token step.
4. **The manager creates the template.** No registry credential is needed, because the image is public, and the
   template carries no environment variable.
   ```
   runpodctl template create --name p6-researcharena-tf4.53.3 \
     --image ghcr.io/hemantbk/control-loop-phase6:tf4.53.3-oc1.19.3-ra58776e0 \
     --container-disk-in-gb 60 --volume-in-gb 30 --volume-mount-path /workspace --ports 22/tcp \
     --readme "Phase 6 prebuilt image (docker/phase6/README.md); digest <digest from the workflow>"
   ```
   - pods.py sends each pod's environment at create time: `OPENROUTER_API_KEY` (from the manager's environment, never
     stored in the template), `HF_HOME`, `ARENA_RESULTS_DIR`, `ARENA_ROOT`, `P6_EPISODE`, `P6_SIDE_TASK` and
     `TOKENIZERS_PARALLELISM`.
   - The manager records the image tag, the digest and the template id in PLAN Amendment (4) by a dated line, then
     runs pods with `export P6_TEMPLATE_ID=<template id>`.
