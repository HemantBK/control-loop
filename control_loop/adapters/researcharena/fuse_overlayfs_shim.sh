#!/usr/bin/env bash
# Copy-based stand-in for fuse-overlayfs, for RunPod pods that have no /dev/fuse (Phase 6; installed by pod_setup.sh
# as /usr/local/bin/fuse-overlayfs ONLY when /dev/fuse is absent). ResearchArena's src/utils/hf_overlay.sh calls
#   fuse-overlayfs -o lowerdir=L,upperdir=U,workdir=W MERGED
# and wants: MERGED shows L's contents, writes to MERGED never reach L, `rm -rf` of the overlay dir removes it all.
# This shim gives exactly that for a one-episode pod by COPYING L into MERGED (reflink when the filesystem can,
# else a plain copy; never hard links, which would let an in-place write reach L). U and W stay unused and empty.
# Teardown is `fusermount -u`/`umount` (fails, ignored by hf_overlay.sh's `|| true`) then `rm -rf` of the overlay dir.
# Refuses (exit 2) when L/U/W are not all given as directories, when MERGED is not empty, or when the copy would
# not fit. A marker `<dirname MERGED>/.shim_overlay` records the paths and the time. Prints one line to stderr
# naming itself a shim so a transcript reader can tell this mode from a real FUSE mount.
set -euo pipefail
me="fuse-overlayfs(shim)"
die() { echo "$me: $*" >&2; exit 2; }

lower=""; upper=""; work=""; merged=""; opts=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) [ $# -ge 2 ] || die "-o needs a value"; opts="$opts,$2"; shift ;;
    -o*) opts="$opts,${1#-o}" ;;
    -V|--version) echo "fuse-overlayfs copy-based shim (control_loop phase 6, no FUSE)"; exit 0 ;;
    -h|--help) echo "usage: fuse-overlayfs -o lowerdir=L,upperdir=U,workdir=W MERGED   (copy-based shim)"; exit 0 ;;
    -f|-d|-s) ;;                                   # foreground/debug/single-thread: meaningless here, tolerated
    -*) die "unsupported option $1" ;;
    *) [ -z "$merged" ] || die "more than one mount point ($merged, $1)"; merged="$1" ;;
  esac
  shift
done
IFS=, read -ra kv <<< "${opts#,}"
for o in "${kv[@]}"; do
  case "$o" in
    lowerdir=*) lower="${o#lowerdir=}" ;;
    upperdir=*) upper="${o#upperdir=}" ;;
    workdir=*)  work="${o#workdir=}" ;;
    *) ;;                                          # other -o keys (squash_to_root, noacl, ...) are tolerated
  esac
done
[ -n "$merged" ] || die "no mount point given"
[ -n "$lower" ] && [ -n "$upper" ] && [ -n "$work" ] || die "lowerdir, upperdir and workdir are all required (got lower='$lower' upper='$upper' work='$work')"
case "$lower" in *:*) die "a single lowerdir only (got '$lower')" ;; esac
for d in "$lower" "$upper" "$work"; do [ -d "$d" ] || die "not a directory: $d"; done
mkdir -p "$merged"
[ -z "$(ls -A "$merged")" ] || die "mount point $merged is not empty"
case "$(cd "$lower" && pwd -P)" in "$(cd "$merged" && pwd -P)") die "lowerdir and mount point are the same directory" ;; esac

need_kb=$(du -sk "$lower" | cut -f1)
avail_kb=$(df -Pk "$merged" | awk 'NR==2 {print $4}')
[ "$avail_kb" -gt "$need_kb" ] || die "not enough space under $merged for a copy of $lower (${need_kb} KiB needed, ${avail_kb} KiB free)"

t0=$(date +%s)
if ! cp -a --reflink=auto "$lower/." "$merged/" 2>/dev/null; then
  rm -rf "${merged:?}"/* "${merged:?}"/.[!.]* 2>/dev/null || true
  cp -a "$lower/." "$merged/"
fi
marker="$(dirname "$merged")/.shim_overlay"
printf 'mode=shim (copy, no FUSE)\nlower=%s\nupper=%s\nwork=%s\nmerged=%s\ncopied_kb=%s\ntime=%s\n' \
  "$lower" "$upper" "$work" "$merged" "$need_kb" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$marker"
echo "$me: no /dev/fuse; COPIED $lower -> $merged ($(( need_kb / 1024 )) MiB in $(( $(date +%s) - t0 )) s); writes stay in the copy, teardown is rm -rf; marker $marker" >&2
exit 0
