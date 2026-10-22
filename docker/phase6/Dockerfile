# syntax=docker/dockerfile:1
# Phase 6 prebuilt image (phases/phase6_researcharena/PLAN.md Amendments 2026-10-22 (4) and (5)).
# pod_setup.sh steps 1-6 baked into image layers (not /workspace: the pod's volume is mounted there at runtime and
# hides image content): system packages, python3 -> 3.11, torch 2.10.0 from PyPI (CUDA 12.8 runtime), transformers
# (build arg; 4.53.3 after the head-layout verdict), node 22 + opencode-ai, the ResearchArena checkout at the pin, the
# TinyLlama snapshot. control_loop/ is NOT baked: pods.py pushes the local tree and pod_setup.sh builds the composed
# root (step 5) and runs the compile check (step 7) on every pod. /etc/p6_image.json records every version; pod_setup.sh
# skips steps 1-6 only when it matches. No secret is used or stored: every download is public and anonymous.
#
# Stages: env (the environment) -> scan (docker/phase6/scan_image.py over env's filesystem, read-only, no network;
# fails the build on a .env file, an API-key pattern or a `/root/` path in the build's own files) -> final (env + the
# scan report). Built by .github/workflows/phase6-image.yml; see docker/phase6/README.md.

ARG BASE_IMAGE=runpod/base:1.4.1-cuda1290-ubuntu2204

FROM ${BASE_IMAGE} AS env
ARG BASE_IMAGE
ARG TORCH_VERSION=2.10.0
ARG TRANSFORMERS_VERSION=4.53.3
ARG OPENCODE_VERSION=1.19.3
ARG NODE_MAJOR=22
ARG RESEARCHARENA_REPO=https://github.com/aisa-group/ResearchArena
ARG RESEARCHARENA_COMMIT=58776e09339c1714d0524130590abaf6eac7879d
ARG TINYLLAMA_MODEL=TinyLlama/TinyLlama-1.1B-Chat-v1.0
ARG TINYLLAMA_REVISION=fe8a4ea1ffedaf415f4da2f062534de366a451e6
ARG IMAGE_TAG=unset
ARG GIT_SHA=unset
ARG BUILD_DATE=unset
ARG DEBIAN_FRONTEND=noninteractive

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# arena.def %environment (CUDA_HOME, TORCH_CUDA_ARCH_LIST) as pod_setup.sh's p6_env.sh writes it. runpod/base sets
# HF_HUB_ENABLE_HF_TRANSFER=1 but installs hf_transfer only for python3.12; huggingface_hub 0.x (required by
# transformers 4.53.3) raises on a download with the flag set and the package missing, so it is off here.
ENV CUDA_HOME=/usr/local/cuda \
    PATH=/usr/local/cuda/bin:${PATH} \
    TORCH_CUDA_ARCH_LIST="8.0;8.9;9.0" \
    HF_HOME=/opt/hf \
    HF_HUB_ENABLE_HF_TRANSFER=0 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TOKENIZERS_PARALLELISM=false

# step 1: system packages (git, rsync, curl, fuse-overlayfs; the base already has most of them)
RUN apt-get update \
 && apt-get install -y --no-install-recommends git rsync curl ca-certificates fuse-overlayfs \
 && rm -rf /var/lib/apt/lists/*

# step 3a: python3 and python resolve to python3.11 (arena.def links /usr/bin/python3 the same way; /usr/bin/python3
# stays apt's)
RUN ln -sf /usr/bin/python3.11 /usr/local/bin/python3 \
 && ln -sf /usr/bin/python3.11 /usr/local/bin/python \
 && python3 --version | grep -q '^Python 3\.11\.'

# step 3b: torch from PyPI (the x86_64 wheel bundles the CUDA 12.8 runtime, as ResearchArena's container gets it)
RUN uv pip install --system --python python3.11 --break-system-packages --no-cache "torch==${TORCH_VERSION}"

# step 3c: transformers at the verdict's version, and what bench.py / the setup need (setuptools: imported by
# torch.utils.cpp_extension; get-pip already put it into the base's python3.11, listed so the build does not rely on it)
RUN uv pip install --system --python python3.11 --break-system-packages --no-cache \
      "transformers==${TRANSFORMERS_VERSION}" accelerate ninja huggingface-hub setuptools

# step 2: node 22 (NodeSource) and opencode-ai
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" -o /tmp/nodesource_setup.sh \
 && bash /tmp/nodesource_setup.sh \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/* /tmp/nodesource_setup.sh \
 && npm install -g "opencode-ai@${OPENCODE_VERSION}" \
 && npm cache clean --force \
 && opencode --version \
 && rm -rf /root/.npm /root/.cache/opencode /root/.local/share/opencode /root/.local/state/opencode /root/.config/opencode

# step 4: the ResearchArena checkout at the pin (pod_setup.sh links it to /workspace/src/ResearchArena)
RUN git clone --quiet "${RESEARCHARENA_REPO}" /opt/ResearchArena \
 && git -C /opt/ResearchArena checkout --quiet "${RESEARCHARENA_COMMIT}" \
 && test "$(git -C /opt/ResearchArena rev-parse HEAD)" = "${RESEARCHARENA_COMMIT}" \
 && test -z "$(git -C /opt/ResearchArena status --porcelain)"

# step 6: the TinyLlama snapshot (the cuda_kernel task config's model) in HF_HOME=/opt/hf (pod_setup.sh links it to
# /workspace/hf). Downloaded as "main" so refs/main exists for an unpinned from_pretrained; the build fails if main has
# moved off the pinned revision.
RUN python3 -c "from huggingface_hub import snapshot_download; print(snapshot_download('${TINYLLAMA_MODEL}', revision='main'))" \
 && test "$(cat "/opt/hf/hub/models--${TINYLLAMA_MODEL/\//--}/refs/main")" = "${TINYLLAMA_REVISION}" \
 && rm -rf /opt/hf/xet /opt/hf/token /opt/hf/stored_tokens /root/.cache/huggingface

# the version record pod_setup.sh's baked_match reads, then the version check (fails the build on a mismatch)
COPY p6_image.py /usr/local/share/p6/p6_image.py
RUN P6_PYTHON_EXPECT=3.11 TORCH_CUDA_EXPECT=12.8 NVCC_EXPECT=12.9 RA_DIR=/opt/ResearchArena \
    TORCH_VERSION="${TORCH_VERSION}" TRANSFORMERS_VERSION="${TRANSFORMERS_VERSION}" OPENCODE_VERSION="${OPENCODE_VERSION}" \
    RESEARCHARENA_COMMIT="${RESEARCHARENA_COMMIT}" TINYLLAMA_MODEL="${TINYLLAMA_MODEL}" TINYLLAMA_REVISION="${TINYLLAMA_REVISION}" \
    IMAGE_TAG="${IMAGE_TAG}" GIT_SHA="${GIT_SHA}" BUILD_DATE="${BUILD_DATE}" BASE_IMAGE="${BASE_IMAGE}" \
    python3 /usr/local/share/p6/p6_image.py record /etc/p6_image.json \
 && rm -rf /root/.cache /root/.npm /root/.local/share/opencode /root/.local/state/opencode /root/.config/opencode \
           /workspace/.cache /tmp/* \
 && find /usr/local/share/p6 -name __pycache__ -type d -prune -exec rm -rf {} +
RUN P6_PYTHON_EXPECT=3.11 TORCH_CUDA_EXPECT=12.8 NVCC_EXPECT=12.9 RA_DIR=/opt/ResearchArena \
    TORCH_VERSION="${TORCH_VERSION}" TRANSFORMERS_VERSION="${TRANSFORMERS_VERSION}" OPENCODE_VERSION="${OPENCODE_VERSION}" \
    RESEARCHARENA_COMMIT="${RESEARCHARENA_COMMIT}" TINYLLAMA_MODEL="${TINYLLAMA_MODEL}" TINYLLAMA_REVISION="${TINYLLAMA_REVISION}" \
    python3 /usr/local/share/p6/p6_image.py check /etc/p6_image.json \
 && rm -rf /root/.cache /root/.npm /root/.local/share/opencode /root/.local/state/opencode /root/.config/opencode /tmp/* \
 && find /usr/local/share/p6 -name __pycache__ -type d -prune -exec rm -rf {} +

# scan: the env stage's filesystem, mounted read-only, no network, run by the base image's python (not the scanned
# image's). The `/root/` check covers the paths this Dockerfile writes; the three ResearchArena files are upstream's
# at the pinned, clean commit (PATH strings for the agent container: containers/arena.def 10, 44;
# src/pipeline_monitor.sh 277; src/pipeline_redteam.sh 336).
FROM ${BASE_IMAGE} AS scan
COPY scan_image.py /usr/local/share/p6-scan/scan_image.py
RUN --network=none --mount=type=bind,from=env,source=/,target=/img \
    python3 /usr/local/share/p6-scan/scan_image.py --root /img --report /p6_scan/report.txt --status /p6_scan/status --no-fail \
      --path-scan /opt/ResearchArena --path-scan /opt/hf --path-scan /etc/p6_image.json --path-scan /usr/local/share/p6 \
      --path-scan /usr/lib/node_modules/opencode-ai/package.json \
      --path-scan-installer-files /usr/local/lib/python3.11/dist-packages \
      --allow-root-path /opt/ResearchArena/containers/arena.def \
      --allow-root-path /opt/ResearchArena/src/pipeline_monitor.sh \
      --allow-root-path /opt/ResearchArena/src/pipeline_redteam.sh \
      --forbid /opt/hf/token --forbid /opt/hf/stored_tokens --forbid /root/.cache/huggingface/token \
      --forbid /root/.git-credentials --forbid /root/.docker/config.json --forbid /root/.npmrc

# scan_out: only the scan's report and status, exported by the workflow (target scan_out, local output) so the report is
# printed in the job log before anything else is built or pushed (2026-10-22, owner).
FROM scratch AS scan_out
COPY --from=scan /p6_scan/ /

FROM env AS final
COPY --from=scan /p6_scan/report.txt /etc/p6_scan.txt
COPY --from=scan /p6_scan/status /etc/p6_scan_status
# the pushed image can only be built from a clean scan
RUN test "$(cat /etc/p6_scan_status)" = OK || { echo "P6 image scan has findings; see the 'Print the scan report' step"; exit 1; }
LABEL org.opencontainers.image.source="https://github.com/HemantBK/control-loop" \
      org.opencontainers.image.description="Phase 6 (ResearchArena cuda_kernel) pod environment; see docker/phase6/README.md"
