# Council (docs/SOP.md §9) — Phase 6 smoke5, 2026-10-22

Members chosen by the owner: Claude Fable 5.1 (`anthropic/claude-fable-5.1`) and OpenAI GPT-6 Astra (`openai/gpt-6-astra`), both through OpenRouter (https://openrouter.ai/api/v1), script `<session scratch>/council/or_call.py`. Two paid calls; council cost $0.2452 (OpenRouter usage.cost; $0.2286 at listed prices). The packet is the logs only: nothing interpretive from the project (no manager's view, no FINDINGS interpretation, no close-out README) went to either model.

## Evidence

Packet: `<session scratch>/council/packet_smoke5.md` (built by `<session scratch>/council/build_packet_smoke5.py`), 18036 bytes, sha256 `f03cbd62ae2c4b314449bd57a9f95d573c4687125d2aa8f8aaf7e8149eecac6b`. Both models received the identical packet and question.

It holds:
- Factual context only: the image `ghcr.io/hemantbk/control-loop-phase6:tf4.53.3-oc1.19.3-ra58776e0` (16.25 GB compressed, built FROM `runpod/base:1.4.1-cuda1290-ubuntu2204`, which carries RunPod's sshd start script), used through RunPod template `pzov5japaa`; the driver's create call waits up to 20 minutes (`runpodctl pod create ... --wait --wait-timeout 20m`); the first SSH command after `pod_create done` is a tar push of the local code over ssh; smoke4 ran the plain runpod/base image and passed setup; diag1 is a pod that never got an SSH port.
- Verbatim, each under `## FILE: <repo path>`:
  - `results/phase6_researcharena/smoke5/{driver.log, run.jsonl, pods.jsonl, launch.json}`
  - `results/phase6_researcharena/smoke4/{run.jsonl, pods.jsonl, launch.json}` (no `driver.log` exists; listed as absent) and `results/phase6_researcharena/smoke4/pods/evfwaz8dpfybcl/setup.log`
  - `results/phase6_researcharena/diag1/{run.jsonl, pods.jsonl, launch.json}` (no `driver.log` exists; listed as absent)

Question, verbatim (identical to both, appended after the packet under `## QUESTION`):

> From these logs only: (1) Can you name a specific cause for the dropped SSH connection in smoke5 ('Connection to … closed by remote host', rc 255, in the same second as pod_create done after 612 s)? Say how confident you are and what in the logs supports it. (2) Is a retry likely to pass, and what fix, if any, would make it more likely? State whether that fix requires changing ResearchArena's code (it must not) or only the driver/template. (3) Answer in at most 200 words.

## Opinions

### Claude Fable 5.1 (`anthropic/claude-fable-5.1`, 2026-10-22T17:39:42+00:00)

- Request settings as sent: `{"model": "anthropic/claude-fable-5.1", "max_tokens": 1500}`; one user message = packet + `\n\n---\n\n## QUESTION\n\n` + question (request sha256 `930bd87a6aec3e87820cbb9b6b1e503ed057872f472044bcae6474eec1b1c9c4`); no system message; no temperature (unsupported).
- Model as sent: `anthropic/claude-fable-5.1`; as returned: `anthropic/claude-fable-5.1`; generation id `gen-1792690784-DyBAyhQPH7DDDGIqCa6n`; finish_reason `stop`; latency 19.7 s.
- Usage: prompt 9496, completion 1056 (of which reasoning 628), total 10552; cache_write_tokens 0.
- Cost at OpenRouter listed prices ($10 / $50 per 1M in/out): 9496 x 10/1M + 1056 x 50/1M = **$0.147760**; OpenRouter usage.cost: **$0.14776**.
- Sidecar (full response JSON): `<session scratch>/council/fable_smoke5.json`.

Response, verbatim:

````markdown
**(1) Cause.** No — the logs cannot pin a specific cause. The only evidence is one ssh rc=255 "closed by remote host" in the same second the create-wait returned, with no `ssh -v` output, no pod logs, and the pod deleted one second later. diag1's error text shows the wait condition is "ssh port allocated", not "sshd accepting logins", so a port can be exposed before sshd (the base image's start script) is ready. The 612 s create (vs 197 s on smoke4 with the plain image) is consistent with most of the wait going to pulling the 16 GB image, leaving the first SSH to arrive while the container was still starting. That is a plausible race, moderate-low confidence (~50%); alternatives (proxy glitch, key not yet installed, container crash) are not excludable from these files.

**(2) Retry.** A plain retry has a fair chance of passing (the race is timing-dependent), but the robust fix is in the driver: after pod_create, poll `ssh … true` with a bounded retry/backoff (e.g. up to 2–3 min) before the tar push; retry the push once on rc=255; and run `runpodctl pod get`/log capture before deleting on failure. Optionally raise nothing else. This touches only the driver/template, not ResearchArena's code.
````

### GPT-6 Astra (`openai/gpt-6-astra`, 2026-10-22T17:40:02+00:00)

- Request settings as sent: `{"model": "openai/gpt-6-astra", "max_tokens": 1500, "seed": 8}`; one user message = packet + `\n\n---\n\n## QUESTION\n\n` + question (request sha256 `930bd87a6aec3e87820cbb9b6b1e503ed057872f472044bcae6474eec1b1c9c4`); no system message; no temperature (unsupported).
- Model as sent: `openai/gpt-6-astra`; as returned: `openai/gpt-6-astra`; generation id `gen-1792690803-aVPF1gg3E9vZUXU2nPoK`; finish_reason `stop`; latency 8.6 s.
- Usage: prompt 6646, completion 287 (of which reasoning 0), total 6933; cache_write_tokens 6643.
- Cost at OpenRouter listed prices ($10 / $50 per 1M in/out): 6646 x 10/1M + 287 x 50/1M = **$0.080810**; OpenRouter usage.cost: **$0.0974175** (upstream prompt cost includes cache-write pricing).
- Sidecar (full response JSON): `<session scratch>/council/astra_smoke5.json`.

Response, verbatim:

````markdown
**1. Cause:** No specific root cause is identifiable from these logs. **High confidence** that smoke5 failed on its first SSH operation—the repository tar push—before `pod_setup.sh` ran. Creation returned an SSH endpoint after 612 seconds; the push then failed with rc 255 and “closed by remote host,” followed by immediate cleanup.

An SSH/startup readiness race is plausible, but **low-confidence**. Container restart, sshd failure, or host/network disruption also fit. There are no server/container logs to distinguish them. The large image could explain slow provisioning, not the disconnect itself. This was **not** a 20-minute create timeout or diag1’s missing-port failure. Inheriting the base image’s sshd script does not establish that it ran correctly.

**2. Retry/fix:** A retry might pass if transient, but these logs do not justify calling success likely. smoke4 establishes that the plain-base path worked, not that this image/template works reliably.

Add a **bounded post-create SSH readiness loop** that successfully executes a trivial remote command, with backoff and limited retries for transient repository-push failures. Collect container/startup diagnostics before deletion if it still fails. Verify template startup configuration preserves the intended sshd startup path. Increasing the create timeout alone does not address this observed failure.

These changes belong only in the **driver/template**, not ResearchArena.
````

## Manager's view

Content of `<session scratch>/council/myview_p6smoke5.md`, verbatim; file mtime 2026-10-22T17:37:57+00:00 (before the first call at 2026-10-22T17:39:42+00:00).

### The manager's view (Claude Opus 5.5), written 2026-10-22 before reading either opinion, from the smoke5 logs only

1. **Cause.** A readiness race, not a network fault: RunPod reported the pod ready (`pod_create done ... in 612s`, SSH address
   31.24.80.42:19291) at 17:13:17Z, the driver opened its first SSH session in the same second (`setup started`), and the remote
   host closed that connection before the tar push completed (ssh rc 255). The 612 s are the first pull of the 16.25 GB image;
   RunPod publishes the port mapping when the container starts, while the image's start script is still bringing sshd up
   (host keys, config), so the first connection hit an sshd that was not yet serving, or that restarted. The driver makes one
   attempt with no SSH readiness probe or retry (`pods.py` `push_repo` is the first SSH call after `pod_create`). The logs cannot
   distinguish "sshd not yet up" from "container restarted once after the pull"; both are fixed the same way.
2. **Fix, no ResearchArena change.** Before setup, probe the pod with `ssh ... true` every 10 s for up to 3 minutes and proceed
   only after two consecutive successes; then push. Optionally give the template a start command that waits for sshd. Both are
   control-loop changes only.
3. **Retry likely to pass?** Yes, likely: the same image is now cached in the registry layers RunPod pulls (pull time is the only
   new factor since smoke4, whose pod reached setup), and a readiness probe removes the race. Residual risk: H100 stock and a
   second slow pull on a different host. Confidence: moderate (about 70 %).

## Agreement

2026-10-22, the manager. **On a cause: no.** Claude Fable 5.1 names no specific cause ("No — the logs cannot pin a specific
cause"; a readiness race "plausible", about 50 %). GPT-6 Astra names no specific cause ("No specific root cause is identifiable
from these logs"; a race "plausible, but low-confidence"). Only the manager's view names one (a readiness race, about 70 %).
The owner's rule ("if at least two agree on a cause with a fix needing no ResearchArena change") is therefore **not met**.
**On a fix: yes, all three:** a bounded SSH readiness check after pod creation (a trivial remote command must succeed), limited
retries of the push, and diagnostics collected before the pod is deleted; Astra adds verifying that the template keeps the base
image's sshd start path. All three place the fix in the driver/template only, with no ResearchArena change. On a retry, Fable:
"a fair chance"; Astra: "these logs do not justify calling success likely"; the manager: likely, about 70 %.

## Decision

2026-10-22, by the owner's rule stated before the council: the rule is not met, so **the Phase 6 close-out stands as written**
("not reproducible on RunPod"); no further smoke or check runs. The agreed driver/template fix is recorded here for any later
attempt the owner may decide on.
