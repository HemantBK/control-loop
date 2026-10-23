#!/bin/bash
L=/workspace/fullrun2/last_bench_events.log; t0=$(date +%s)
before=$(ls -d /tmp/arena_agent_* 2>/dev/null)
while :; do d=$(ls -dt /tmp/arena_agent_* 2>/dev/null | head -1); [ -n "$d" ] && ! echo "$before" | grep -qx "$d" && break; [ $(( $(date +%s) - t0 )) -gt 900 ] && { echo "$(date -u +%FT%TZ) no agent job dir appeared" >> $L; exit 0; }; sleep 1; done
echo "$(date -u +%FT%TZ) WATCHING $d" >> $L
timeout 1800 inotifywait -m -r -q -e access,modify,open,close_write,close_nowrite,create,delete,moved_to,moved_from --timefmt '%FT%TZ' --format '%T %e %w%f' "$d" 2>>$L | grep --line-buffered last_bench >> $L
echo "$(date -u +%FT%TZ) WATCH_END" >> $L
