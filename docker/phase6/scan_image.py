"""Secret and host-path scan of the Phase 6 image filesystem (PLAN Amendment 2026-10-22 (4); owner's rule: public image).

    python3 scan_image.py --root DIR [--path-scan P ...] [--path-scan-installer-files D ...] [--forbid P ...]
                          [--allow-root-path P ...] [--report FILE]

DIR is the image's root filesystem (in the Dockerfile's `scan` stage: the `env` stage bind-mounted read-only at /img;
in the tests: a fake tree). Paths given to the options are image paths (absolute, resolved under DIR). Fails (exit 1)
when any of these holds:

1. whole image: a file (regular or symlink) named `.env` or ending in `.env`; no exemption is built in;
2. whole image: any content matching an API-key pattern (KEY_PATTERNS below), except the two AWS documentation example
   key ids and the public values listed by sha256 in KNOWN_PUBLIC_SHA256 (each printed as ALLOWED with its reason);
   every regular file is read, binaries included;
3. whole image: a path in `--forbid` exists (credential files: HF token, git credentials, docker config);
4. the paths the Dockerfile writes (`--path-scan`, each must exist): the string `/root/` in any text file, except the
   files named by `--allow-root-path`; for the pip install dirs (`--path-scan-installer-files`) only the files the
   installer writes into each *.dist-info (RECORD, INSTALLER, REQUESTED, direct_url.json) are read, because the
   package authors' own text is not this build's and a `/root/` there would not be a leak from this build.

Every finding prints its kind, the image path, the pattern name and the byte offset; a matched value is never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys

# Left boundaries keep identifiers such as `task-...`, `disk-...` or `self_hf_...` from matching; a real key is
# preceded by a quote, `=`, `:`, whitespace or a line start.
KEY_PATTERNS = [
    ("anthropic_key", rb"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}"),
    ("openrouter_key", rb"(?<![A-Za-z0-9_-])sk-or-[A-Za-z0-9_-]{20,}"),
    ("sk_key", rb"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}"),
    ("github_token", rb"(?<![A-Za-z0-9_])ghp_[A-Za-z0-9]{30,}"),
    ("github_fine_grained_pat", rb"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{30,}"),
    ("hf_token", rb"(?<![A-Za-z0-9_])hf_[A-Za-z0-9]{30,}"),
    ("runpod_key", rb"(?<![A-Za-z0-9_])rpa_[A-Za-z0-9]{20,}"),
    ("aws_access_key_id", rb"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}"),
]
COMPILED = [(n, re.compile(p)) for n, p in KEY_PATTERNS]
PREFIXES = (b"sk-", b"ghp_", b"github_pat_", b"hf_", b"rpa_", b"AKIA")
# AWS's own documentation example key ids (docs.aws.amazon.com); public, not credentials
KNOWN_EXAMPLES = {b"AKIAIOSFODNN7EXAMPLE", b"AKIAI44QH8DHBEXAMPLE"}
# Key-shaped values that are public by design, by the sha256 of the matched bytes (the value itself is not repeated
# here). Each entry was read on the CPU pod on 2026-10-22 with the value masked.
KNOWN_PUBLIC_SHA256 = {
    # transformers/testing_utils.py (4.44.2, 4.53.3, 5.3.0): `TOKEN = ...` beside USER = "__DUMMY_TRANSFORMERS_USER__"
    # and ENDPOINT_STAGING = "https://hub-ci.huggingface.co", commented "Not critical, only usable on the sandboxed
    # CI instance." Hugging Face's published token for its staging CI hub, not an account credential.
    "5de261506c0ff857b7c1af7059f842fb0a36d1ca2e4895da542c5eb726f2c802":
        "Hugging Face staging-CI token published in transformers/testing_utils.py",
}
INSTALLER_FILES = {"RECORD", "INSTALLER", "REQUESTED", "direct_url.json"}
SKIP_TOP = {"proc", "sys", "dev"}           # runtime mounts; empty in an image rootfs
CHUNK = 8 << 20
OVERLAP = 512
ROOT_STR = b"/root/"


def is_env_name(name: str) -> bool:
    return name == ".env" or name.endswith(".env")


def image_path(root: str, p: str) -> str:
    rel = os.path.relpath(p, root)
    return "/" if rel == "." else "/" + rel


def key_hits(fp, allowed: list | None = None) -> list[tuple[str, int]]:
    """(pattern name, offset) of the first match of each pattern in an open binary file; matches of a known public
    value are appended to `allowed` as (pattern name, offset, reason) instead."""
    hits: dict[str, int] = {}
    prev = b""
    base = 0                                  # file offset of prev[0]
    while True:
        chunk = fp.read(CHUNK)
        if not chunk:
            break
        buf = prev + chunk
        if any(p in buf for p in PREFIXES):
            for name, rx in COMPILED:
                if name in hits:
                    continue
                for m in rx.finditer(buf):
                    if m.group(0) in KNOWN_EXAMPLES:
                        continue
                    reason = KNOWN_PUBLIC_SHA256.get(hashlib.sha256(m.group(0)).hexdigest())
                    if reason:
                        if allowed is not None and not any(a[0] == name and a[1] == base + m.start() for a in allowed):
                            allowed.append((name, base + m.start(), reason))
                        continue
                    if name == "sk_key" and (m.group(0).startswith(b"sk-ant-") or m.group(0).startswith(b"sk-or-")):
                        continue              # reported under its own name
                    hits[name] = base + m.start()
                    break
        keep = buf[-OVERLAP:]
        base += len(buf) - len(keep)
        prev = keep
    return sorted(hits.items(), key=lambda x: x[1])


def is_text(path: str) -> bool:
    with open(path, "rb") as f:
        return b"\0" not in f.read(8192)


def scan(root: str, path_scan: list[str], installer_dirs: list[str], forbid: list[str], allow_root: list[str]):
    root = os.path.abspath(root)
    findings: list[str] = []
    notes: list[str] = []
    files = nbytes = 0
    seen: set[tuple[int, int]] = set()

    def under(p: str) -> str:
        return os.path.join(root, p.lstrip("/"))

    # 1-2: whole image
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if dirpath == root:
            dirnames[:] = [d for d in dirnames if d not in SKIP_TOP]
        for d in list(dirnames):               # a symlinked dir named *.env is listed in dirnames
            if is_env_name(d) and os.path.islink(os.path.join(dirpath, d)):
                findings.append(f"FAIL env_file {image_path(root, os.path.join(dirpath, d))}")
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            if is_env_name(fn):
                findings.append(f"FAIL env_file {image_path(root, p)}")
            try:
                st = os.lstat(p)
            except OSError as e:
                findings.append(f"FAIL unreadable {image_path(root, p)} ({type(e).__name__})")
                continue
            if not stat.S_ISREG(st.st_mode) or (st.st_dev, st.st_ino) in seen:
                continue
            seen.add((st.st_dev, st.st_ino))
            try:
                allowed: list = []
                with open(p, "rb") as f:
                    for name, off in key_hits(f, allowed):
                        findings.append(f"FAIL key_pattern {image_path(root, p)} pattern={name} offset={off}")
                for name, off, reason in allowed:
                    notes.append(f"ALLOWED key_pattern {image_path(root, p)} pattern={name} offset={off} ({reason})")
            except OSError as e:
                findings.append(f"FAIL unreadable {image_path(root, p)} ({type(e).__name__})")
                continue
            files += 1
            nbytes += st.st_size

    # 3: credential files that must not exist
    for p in forbid:
        if os.path.lexists(under(p)):
            findings.append(f"FAIL forbidden_file {p}")

    # 4: `/root/` in the text files this Dockerfile writes
    allowed = {"/" + a.lstrip("/") for a in allow_root}
    targets: list[str] = []
    for p in path_scan:
        q = under(p)
        if not os.path.lexists(q):
            findings.append(f"FAIL path_scan_missing {p} (listed in the scan but not in the image)")
            continue
        if os.path.isfile(q) and not os.path.islink(q):
            targets.append(q)
        else:
            for dirpath, _, filenames in os.walk(q, followlinks=False):
                targets.extend(os.path.join(dirpath, fn) for fn in filenames)
    for d in installer_dirs:
        q = under(d)
        if not os.path.isdir(q):
            findings.append(f"FAIL path_scan_missing {d} (listed in the scan but not in the image)")
            continue
        for e in sorted(os.listdir(q)):
            if e.endswith(".dist-info"):
                targets.extend(os.path.join(q, e, fn) for fn in sorted(INSTALLER_FILES) if os.path.isfile(os.path.join(q, e, fn)))
    root_checked = 0
    for t in targets:
        if os.path.islink(t) or not os.path.isfile(t):
            continue
        ip = image_path(root, t)
        if ip in allowed or not is_text(t):
            continue
        root_checked += 1
        with open(t, "rb") as f:
            data = f.read()
        i = data.find(ROOT_STR)
        if i >= 0:
            findings.append(f"FAIL root_path {ip} offset={i}")
    summary = (f"scanned {files} regular files, {nbytes / 1e9:.2f} GB, for .env names and {len(KEY_PATTERNS)} key "
               f"patterns; {root_checked} text files of the build's own paths for '/root/'; "
               f"{len(notes)} known public value(s) allowed; {len(findings)} finding(s)")
    return findings, notes, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True)
    ap.add_argument("--path-scan", action="append", default=[])
    ap.add_argument("--path-scan-installer-files", action="append", default=[])
    ap.add_argument("--forbid", action="append", default=[])
    ap.add_argument("--allow-root-path", action="append", default=[])
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    findings, notes, summary = scan(a.root, a.path_scan, a.path_scan_installer_files, a.forbid, a.allow_root_path)
    for f in notes + findings:
        print(f)
    print(("P6 IMAGE SCAN FAILED: " if findings else "P6 IMAGE SCAN OK: ") + summary)
    if a.report and not findings:
        with open(a.report, "w") as f:
            f.write("".join(n + "\n" for n in notes) + "P6 IMAGE SCAN OK: " + summary + "\n")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
