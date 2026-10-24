#!/bin/bash
# Phase 6 re-measure session (PLAN Amendment (19); owner, 2026-10-24). Order: check; create; ready, driver, setup, kit,
# harness (core: if one fails, the pod cannot run the checks, so they are skipped and the session goes to copy and
# delete); then every check runs whatever happened to the ones before it: prepare, interleave, memcheck,
# memcheck_initial, kl, embedded, rope, vanilla, starter; then copy (verified) and delete (refused without a verified
# copy once results exist). A failed readiness is followed by the pod's real-state check (remeasure.py ready).
# Env (all optional): P6_REPO, P6_OUT_DIR, P6_RUNNER (stub: the runner without --env-file).
set -u; cd ${P6_REPO:-/root/control-loop}
S=${P6_OUT_DIR:-${P6_RM_OUT:-results/phase6_researcharena/fixrun/remeasure}}; mkdir -p $S
R=${P6_RUNNER:-"uv run --frozen --env-file ../.env python scripts/phase6/remeasure.py"}
E="env -u P6_TEMPLATE_ID P6_DCS=${P6_DCS_LIST:-EU-FR-1,US-NE-1,EU-NL-1,US-GA-2,US-CA-2} RESEARCHARENA_ROOT=/root/src/ResearchArena P6_ARENA_ROOT=/root/phase6_arena_root OPENCODE_VERSION=1.19.3"
FAILED=""
step() { local tag="$1"; echo "=== $tag $(date -u +%T)"; $E $R $tag > $S/step_$tag.out 2>&1; local rc=$?
         tail -3 $S/step_$tag.out | cut -c1-240
         if [ "$rc" != 0 ]; then echo "STEP_FAILED $tag rc=$rc $(date -u +%T)"; FAILED="$FAILED $tag"; fi; return $rc; }
step check || { echo "SESSION_END nothing created (check failed)"; exit 1; }
step create || { echo "SESSION_END no pod (create failed)"; exit 1; }
core=ok
for s in ready driver setup kit harness; do step $s || { core=failed; break; }; done
if [ $core = ok ]; then
  for c in prepare interleave memcheck memcheck_initial kl embedded rope vanilla starter; do step $c; done
else
  echo "CHECKS_SKIPPED core step failed: the pod cannot run the checks"
fi
step copy
step delete
echo "SESSION_END failed steps:${FAILED:- none} $(date -u +%T)"
