"""Verified copy of a GPU pod's results to the CPU pod before the pod is deleted (owner, 2026-10-24: "Delete the pod only
after the copy is verified"). The pod writes a manifest, one `sha256  <tag>/<relative path>` line per regular file under
each root it keeps; after rsync, `verify` hashes the local copy (`<local root>/<tag>/<relative path>`) and compares.
PASS iff every manifest file is present locally with the same sha256 (file count and checksums match). Local files that
are not in the manifest are reported as extra, not as failures."""
from __future__ import annotations

import hashlib
from pathlib import Path


def parse_manifest(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        sha, _, rel = line.partition("  ")
        if len(sha) != 64 or not rel:
            raise ValueError(f"bad manifest line: {line[:120]!r}")
        out[rel] = sha
    return out


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(manifest_text: str, local_root: Path, tags: list[str]) -> dict:
    want = parse_manifest(manifest_text)
    local = {}
    for tag in tags:
        base = local_root / tag
        if base.is_dir():
            for p in base.rglob("*"):
                if p.is_file() and not p.is_symlink():
                    local[f"{tag}/{p.relative_to(base).as_posix()}"] = p
    missing = sorted(r for r in want if r not in local)
    mismatched = sorted(r for r in want if r in local and sha256_file(local[r]) != want[r])
    extra = sorted(r for r in local if r not in want)
    by_tag = {t: sum(1 for r in want if r.startswith(t + "/")) for t in tags}
    return {"pass": bool(want) and not missing and not mismatched, "remote_files": len(want),
            "local_matching": len(want) - len(missing) - len(mismatched), "missing": missing[:50],
            "mismatched": mismatched[:50], "n_missing": len(missing), "n_mismatched": len(mismatched),
            "extra": extra[:50], "n_extra": len(extra), "remote_files_by_root": by_tag}
