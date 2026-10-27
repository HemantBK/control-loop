#!/bin/bash
# Run the untrusted agent as an unprivileged user (PLAN Amendment (25) item 5; benchmark change 08). The pipeline runs the
# agent with no container on our pods ("running locally"), so as root it could read RunPod's pod-scoped key, which
# reads every pod's environment. Run as root:
#   p6_agent_exec.sh prepare <agent job dir>   create the user if needed, make /etc/rp_environment root-only, give the
#                                              user the job dir
#   p6_agent_exec.sh run <command...>          the command as the user, with its own HOME and without RUNPOD_API_KEY
#   p6_agent_exec.sh check                     fail-closed probe through `run`: the agent's environment, the pod-key
#                                              file, every /proc/*/environ and /proc/*/cmdline it can read, and every
#                                              file on the pod that holds the key and is readable by the user. Prints
#                                              counts only, never the key. Exit 0 iff all are 0.
# Settings: P6_AGENT_USER (default p6agent); P6_RP_ENV (default /etc/rp_environment); P6_SCAN_ROOTS (default: where
# runtime processes write: /etc /root /home /tmp /var /workspace /opt); P6_SCAN_SKIP (paths left out: by default the
# model cache and /var/lib's package databases). Directories named site-packages, node_modules, .venv, .git and
# __pycache__, and the package caches (.cache/uv, .cache/pip, .cache/huggingface, .npm), are never scanned: installed
# packages, not runtime output. Only files modified since the pod key was written (the mtime of $RPENV, less 60 s) are
# scanned: no file older than the key can hold it. /usr and /proc are not scanned as files; /proc is probed through
# environ and cmdline above. A scan of every file took over 15 minutes on the CPU pod.
set -u
U=${P6_AGENT_USER:-p6agent}
RPENV=${P6_RP_ENV:-/etc/rp_environment}
SELF=$(readlink -f "$0")

ids() { echo "$(id -u "$U") $(id -g "$U")"; }

case "${1:-}" in
  prepare)
    id -u "$U" > /dev/null 2>&1 || useradd -m -s /bin/bash "$U" || exit 1
    chmod 600 "$RPENV" 2>/dev/null
    # each episode starts clean: a fresh home (the agent's tools keep sessions there, prompts included) and no file of
    # an earlier episode in /tmp (2026-10-26: several episodes run serially on one pod)
    H=$(getent passwd "$U" | cut -d: -f6)
    if [ -n "$H" ] && [ "$H" != "/" ]; then rm -rf "$H" && mkdir -p "$H" && cp -rT /etc/skel "$H" 2>/dev/null; chown -R "$U": "$H"; chmod 700 "$H"; fi
    find /tmp -mindepth 1 -maxdepth 1 -user "$U" ! -path "${2:-/nonexistent}" -exec rm -rf {} + 2>/dev/null
    [ -n "${2:-}" ] && chown -R "$U": "$2"
    exit 0 ;;
  run)
    shift
    read -r UID_ GID_ <<< "$(ids)" || exit 1
    H=$(getent passwd "$U" | cut -d: -f6)
    exec setpriv --reuid="$UID_" --regid="$GID_" --init-groups -- \
      env -u RUNPOD_API_KEY HOME="${H:-/tmp}" USER="$U" LOGNAME="$U" "$@" ;;
  check)
    K=$(sed -n 's/^\(export \)\{0,1\}RUNPOD_API_KEY=//p' "$RPENV" 2>/dev/null | tr -d '"' | head -1)
    if [ -z "$K" ]; then echo "AGENT_KEY_CHECK no pod key in $RPENV; nothing to find"; echo "AGENT_KEY_CHECK PASS"; exit 0; fi
    KF=$(mktemp); chmod 600 "$KF"; printf '%s\n' "$K" > "$KF"; unset K   # grep -f: the key never sits in a command line
    trap 'rm -f "$KF"' EXIT INT TERM HUP
    ENV_N=$("$SELF" run env 2>/dev/null | grep -cFf "$KF")
    FILE_N=$("$SELF" run cat "$RPENV" 2>/dev/null | grep -cFf "$KF")
    PROC_N=$("$SELF" run sh -c 'cat /proc/[0-9]*/environ 2>/dev/null' | tr '\0' '\n' | grep -cFf "$KF")
    CMD_N=$("$SELF" run sh -c 'cat /proc/[0-9]*/cmdline 2>/dev/null' | tr '\0' '\n' | grep -cFf "$KF")
    SKIP=${P6_SCAN_SKIP:-${HF_HOME:-/workspace/hf} /workspace/hf /var/lib /var/cache}
    EX=(); for s in $SKIP; do EX+=(-path "$s" -prune -o); done
    for n in site-packages node_modules .venv .git __pycache__ .npm; do EX+=(-name "$n" -prune -o); done
    for c in uv pip huggingface; do EX+=(-path "*/.cache/$c" -prune -o); done
    SINCE=$(( $(stat -c %Y "$RPENV" 2>/dev/null || echo 0) - 60 ))
    READABLE=0
    while IFS= read -r -d '' f; do
      if "$SELF" run test -r "$f" 2>/dev/null; then
        READABLE=$((READABLE + 1)); echo "AGENT_KEY_CHECK readable file holding the key: $f"
      fi
    done < <(find ${P6_SCAN_ROOTS:-/etc /root /home /tmp /var /workspace /opt} "${EX[@]}" -type f -size -50M \
               -newermt "@$SINCE" -print0 2>/dev/null \
             | xargs -0 -r grep -lZFf "$KF" 2>/dev/null)
    echo "AGENT_KEY_CHECK user $U: environment $ENV_N, $RPENV $FILE_N, /proc environ $PROC_N, /proc cmdline $CMD_N, readable files holding the key $READABLE"
    if [ "$ENV_N" = 0 ] && [ "$FILE_N" = 0 ] && [ "$PROC_N" = 0 ] && [ "$CMD_N" = 0 ] && [ "$READABLE" = 0 ]; then
      echo "AGENT_KEY_CHECK PASS"; exit 0
    fi
    echo "AGENT_KEY_CHECK FAIL: the agent could reach the pod key; it must not start"; exit 1 ;;
  *)
    echo "usage: p6_agent_exec.sh prepare <dir> | run <command...> | check"; exit 2 ;;
esac
