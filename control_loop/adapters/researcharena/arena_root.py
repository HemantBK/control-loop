"""The composed arena root (phases/phase6_researcharena/PLAN.md §1.4): ResearchArena unmodified.

ResearchArena resolves every path from `ARENA_ROOT` (`run_redteam.sh` 17, 156; `run_monitor.sh` 142) and
discovers side tasks and agents by directory (`README.md` 401–415). `build()` creates a second directory
whose top-level entries are symlinks into the pinned checkout, except for exactly two additions:

1. `settings/cuda_kernel/side_tasks/payload/`: `side_task.md` = the round's payload file, plus symlinks to
   `independent/{evaluate.py, requirements.txt}` and `independent/hooks/pre_agent.sh`, so the scorer and the
   staged requirements.txt are the stock ones. (`settings/`, `settings/cuda_kernel/` and `side_tasks/` are
   therefore real directories whose other entries are symlinks.)
2. `agents/opencode_or/`: `human_readable_trace.py` (copy of the stock file), `keep_env_vars` (stock lines plus
   `OPENROUTER_API_KEY`) and `solve.sh`. The stock `agents/opencode/solve.sh` writes its own `opencode.json`
   from a heredoc into the task directory (lines 51–92), so a separate config file in the agent directory
   would never be read; the overlay's `solve.sh` is the stock text with the `openrouter` provider block
   (`apiKey` `{env:OPENROUTER_API_KEY}`) inserted into that heredoc and, since 2026-10-22, one exported
   `OPENCODE_CONFIG_CONTENT` line after it carrying the Qwen3 OpenRouter routing (ROUTING_CONFIG; see the
   comment at QWEN3_ROUTING for why the heredoc cannot carry it), nothing else changed. Tests may pass
   `overlay_agent_dir` to install a different directory under the same name (a mock agent).

Amendment 2026-10-22 (2) (PLAN): `settings/cuda_kernel/task_context/` is a real directory holding a byte copy of
the checkout's task_context (no symlinks inside), not a symlink. `bench.sh --compile-only` writes
`task_context/workspace/` (bench.py 305–307, `ROOT` = the script's own directory) and Python writes `__pycache__/`
next to `config.py`/`inject.py`; through the old symlink both landed in the pinned checkout (smoke3). With the copy
they land in the composed root. The copy changes nothing an episode sees: `src/pipeline_redteam.sh:145–146` copies
`$SETTING_DIR/task_context/*` into the per-run `$AGENT_JOB_DIR/task/` with `cp -r`, which reads the same bytes
whether `task_context` is a symlink or a real copy; it is the only use of `task_context` in `src/` and the
`cuda_kernel` setting. Generated paths left in the copy WOULD be copied by that glob, so the compile check
(`pod_setup.sh` compile_check) removes them after the build.

`verify()` hashes every regular file reachable from the composed root (symlinks followed), checks that each
file outside the two additions is byte-identical to the checkout's file at the same relative path (this covers
every file of the task_context copy), that nothing in the checkout is missing from the composed root, that the
checkout is clean at the pinned commit, that `task_context` is a real directory without symlinks, and writes a
manifest JSON (hashes of the additions, the stock files they derive from, the counts). Build artefacts under
`task_context/workspace/` and `__pycache__/` (GENERATED_DIRS) are not compared but are listed in the manifest as
`generated_ignored`; any other difference fails.
No ResearchArena file is modified. No model call. Paths inside the manifest are as given (the composed root
and the checkout live outside the repository on the pods)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

PINNED_COMMIT = "58776e09339c1714d0524130590abaf6eac7879d"
SETTING = "cuda_kernel"
SIDE_TASK_NAME = "payload"            # --side_task payload
OVERLAY_AGENT = "opencode_or"         # --redteammodel opencode_or:<model>
PAYLOAD_DIR = f"settings/{SETTING}/side_tasks/{SIDE_TASK_NAME}"
AGENT_DIR = f"agents/{OVERLAY_AGENT}"
MANIFEST = "composed_root_manifest.json"
TASK_CONTEXT = f"settings/{SETTING}/task_context"   # a real copy in the composed root (Amendment 2026-10-22 (2))
GENERATED_DIRS = ("workspace", "__pycache__")     # written by bench.py / the Python import system; never compared

# The provider block added to the stock heredoc, inserted immediately before the stock "anthropic" entry.
_STOCK_ANCHOR = '  "provider": {\n    "anthropic": {\n'
OPENROUTER_BLOCK = ('  "provider": {\n'
                    '    "openrouter": {\n'
                    '      "options": {\n'
                    '        "apiKey": "{env:OPENROUTER_API_KEY}"\n'
                    '      }\n'
                    '    },\n'
                    '    "anthropic": {\n')

# Qwen3 provider routing (2026-10-22, PLAN Amendment (3); phases/phase6_researcharena/pins.md "OpenRouter routing").
# run2 check e1 died on an OpenRouter 404 from the Google Vertex route (`.../publishers/qwen/models/
# qwen3-235b-a22b-instruct-2507-maas` not found; CHECK_BYHAND.md §3). Pinned to the providers that served this model
# without error in Phase 4 (phases/phase4_controlarena/pins.md: DeepInfra, Parasail, Venice; Google's only route for
# this model on OpenRouter is google-vertex, so it is excluded), no fallback (openrouter.ai/docs/features/
# provider-routing: `order`, `allow_fallbacks`, `ignore`; a base slug matches every endpoint of that provider).
# Where it goes: opencode passes a model's config `options` to the AI SDK as providerOptions.openrouter, which
# @openrouter/ai-sdk-provider spreads into the /chat/completions body (opencode.ai/docs/providers shows the form).
# BUT opencode 1.19.3 `opencode run` does not apply the provider/model settings of the opencode.json that solve.sh
# writes into the task directory: captured request bodies (no request reached OpenRouter; a local TLS-terminating
# proxy recorded them; FINDINGS 2026-10-22, "unpaid fixes") carried no
# `provider` and no configured header from that file, in a plain and in a committed git repo, while the same JSON
# given through $OPENCODE_CONFIG, the global config dir or $OPENCODE_CONFIG_CONTENT did reach the body. So the overlay
# exports OPENCODE_CONFIG_CONTENT holding ONLY the Qwen3 routing (nothing else the agent sees changes), right after
# the stock heredoc; the heredoc keeps the openrouter apiKey block as before.
QWEN3_MODEL = "qwen/qwen3-235b-a22b-2507"
QWEN3_ROUTING = {"order": ["deepinfra", "parasail", "venice"], "allow_fallbacks": False, "ignore": ["google-vertex"]}
ROUTING_CONFIG = {"provider": {"openrouter": {"models": {QWEN3_MODEL: {"options": {"provider": QWEN3_ROUTING}}}}}}
_HEREDOC_START = "cat > opencode.json << 'EOF'\n"
_HEREDOC_END = "\nEOF\n"


def routing_export_block() -> str:
    """The lines the overlay adds after the stock opencode.json heredoc (single-quoted JSON: no shell expansion)."""
    content = json.dumps(ROUTING_CONFIG, separators=(",", ":"))
    assert "'" not in content
    return ("# control-loop Phase 6 overlay (PLAN Amendment 2026-10-22 (3)): opencode 1.19.3 `run` does not apply the\n"
            "# provider settings of the opencode.json above; OPENCODE_CONFIG_CONTENT is applied. Qwen3 OpenRouter routing\n"
            "# pinned (phases/phase6_researcharena/pins.md): DeepInfra, Parasail, Venice; no fallback; google-vertex ignored.\n"
            f"export OPENCODE_CONFIG_CONTENT='{content}'\n")


def routing_from_solve_sh(text: str) -> dict | None:
    """The OPENCODE_CONFIG_CONTENT JSON an overlay solve.sh exports (tests, verify), or None."""
    for line in text.splitlines():
        if line.startswith("export OPENCODE_CONFIG_CONTENT='") and line.endswith("'"):
            return json.loads(line[len("export OPENCODE_CONFIG_CONTENT='"):-1])
    return None


class ArenaRootError(RuntimeError):
    pass


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def checkout_state(checkout: str | os.PathLike) -> dict:
    """HEAD and `git status --porcelain` of the checkout (read-only git calls)."""
    checkout = str(checkout)
    head = subprocess.run(["git", "-C", checkout, "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    status = subprocess.run(["git", "-C", checkout, "status", "--porcelain"], capture_output=True, text=True, check=True)
    return dict(head=head.stdout.strip(), porcelain=status.stdout)


def overlay_solve_sh(stock_text: str) -> str:
    """Stock agents/opencode/solve.sh with the openrouter provider inserted into its opencode.json heredoc and,
    right after the heredoc, the Qwen3 routing exported as OPENCODE_CONFIG_CONTENT (2026-10-22)."""
    if stock_text.count(_STOCK_ANCHOR) != 1 or stock_text.count(_HEREDOC_START) != 1:
        raise ArenaRootError("stock agents/opencode/solve.sh does not contain the expected provider block / heredoc once; "
                             "the checkout is not the pinned one")
    text = stock_text.replace(_STOCK_ANCHOR, OPENROUTER_BLOCK)
    start = text.index(_HEREDOC_START)
    end = text.index(_HEREDOC_END, start) + len(_HEREDOC_END)
    return text[:end] + "\n" + routing_export_block() + text[end:]


def overlay_keep_env_vars(stock_text: str) -> str:
    lines = [ln for ln in stock_text.splitlines() if ln.strip()]
    if "OPENROUTER_API_KEY" not in lines:
        lines.append("OPENROUTER_API_KEY")
    return "\n".join(lines) + "\n"


def default_overlay_agent(checkout: Path, dest_dir: Path) -> None:
    """Write agents/opencode_or/ from the stock agents/opencode/ (PLAN §1.4 item 2)."""
    stock = checkout / "agents" / "opencode"
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "solve.sh").write_text(overlay_solve_sh((stock / "solve.sh").read_text(encoding="utf-8")), encoding="utf-8")
    os.chmod(dest_dir / "solve.sh", 0o755)
    (dest_dir / "keep_env_vars").write_text(overlay_keep_env_vars((stock / "keep_env_vars").read_text(encoding="utf-8")),
                                            encoding="utf-8")
    shutil.copyfile(stock / "human_readable_trace.py", dest_dir / "human_readable_trace.py")


def build(dest: str | os.PathLike, checkout: str | os.PathLike, payload_file: str | os.PathLike,
          overlay_agent_dir: str | os.PathLike | None = None) -> Path:
    """Create (or refresh) the composed root at `dest`. Idempotent: an existing composed root is removed
    first (it contains only symlinks, the task_context copy and the two additions). `payload_file` becomes
    settings/cuda_kernel/side_tasks/payload/side_task.md (a copy, so the round's file may be rewritten later
    without changing a running episode). `overlay_agent_dir`: None = derive agents/opencode_or from the
    stock agents/opencode; a path = copy that directory under the same name (tests: a mock agent)."""
    dest, checkout, payload_file = Path(dest), Path(checkout).resolve(), Path(payload_file)
    if not (checkout / "run_redteam.sh").exists():
        raise ArenaRootError(f"{checkout} is not a ResearchArena checkout (no run_redteam.sh)")
    if dest.exists():
        if (dest / MANIFEST).exists() or (dest / "run_redteam.sh").is_symlink():
            shutil.rmtree(dest)
        else:
            raise ArenaRootError(f"{dest} exists and is not a composed root; refusing to remove it")
    dest.mkdir(parents=True)

    def link_children(src_dir: Path, dst_dir: Path, skip: set[str] = frozenset()) -> None:
        dst_dir.mkdir(parents=True, exist_ok=True)
        for child in sorted(src_dir.iterdir()):
            if child.name in skip or child.name == ".git":
                continue
            os.symlink(child, dst_dir / child.name)

    # top level: everything but settings/ and agents/ is a symlink
    link_children(checkout, dest, skip={"settings", "agents"})
    # settings/: real dir; every setting but cuda_kernel symlinked; inside cuda_kernel every entry but side_tasks symlinked
    link_children(checkout / "settings", dest / "settings", skip={SETTING})
    link_children(checkout / "settings" / SETTING, dest / "settings" / SETTING, skip={"side_tasks", "task_context"})
    link_children(checkout / "settings" / SETTING / "side_tasks", dest / "settings" / SETTING / "side_tasks")
    # task_context: a real byte copy (file modes kept, symlinks resolved to files, generated dirs not copied), so
    # bench.sh's build outputs land here and never in the checkout (Amendment 2026-10-22 (2))
    shutil.copytree(checkout / TASK_CONTEXT, dest / TASK_CONTEXT, symlinks=False,
                    ignore=shutil.ignore_patterns(*GENERATED_DIRS, "*.pyc"))
    payload_dir = dest / PAYLOAD_DIR
    payload_dir.mkdir()
    independent = checkout / "settings" / SETTING / "side_tasks" / "independent"
    shutil.copyfile(payload_file, payload_dir / "side_task.md")
    os.symlink(independent / "evaluate.py", payload_dir / "evaluate.py")
    os.symlink(independent / "requirements.txt", payload_dir / "requirements.txt")
    (payload_dir / "hooks").mkdir()
    os.symlink(independent / "hooks" / "pre_agent.sh", payload_dir / "hooks" / "pre_agent.sh")
    # agents/: real dir; every stock agent symlinked; opencode_or added
    link_children(checkout / "agents", dest / "agents")
    agent_dir = dest / AGENT_DIR
    if overlay_agent_dir is None:
        default_overlay_agent(checkout, agent_dir)
    else:
        shutil.copytree(Path(overlay_agent_dir), agent_dir, symlinks=False)
        if (agent_dir / "solve.sh").exists():
            os.chmod(agent_dir / "solve.sh", 0o755)
    return dest


def _generated_files(dest: Path) -> list[str]:
    """Relative paths of the build artefacts in the composed root's task_context copy: every file under a
    GENERATED_DIRS directory (bench.py's `workspace/`, Python's `__pycache__/`) and any stray *.pyc."""
    tc = dest / TASK_CONTEXT
    out: list[str] = []
    if not tc.is_dir() or tc.is_symlink():
        return out
    for dirpath, dirnames, filenames in os.walk(tc):
        dirnames.sort()
        rel_dir = Path(dirpath).relative_to(tc)
        in_generated = any(part in GENERATED_DIRS for part in rel_dir.parts)
        for fn in sorted(filenames):
            if in_generated or fn.endswith(".pyc"):
                out.append(str(Path(TASK_CONTEXT) / rel_dir / fn))
    return out


def _is_generated(relp: str) -> bool:
    if not relp.startswith(TASK_CONTEXT + "/"):
        return False
    parts = Path(relp).relative_to(TASK_CONTEXT).parts
    return any(p in GENERATED_DIRS for p in parts[:-1]) or relp.endswith(".pyc")


def _walk_files(root: Path) -> dict[str, Path]:
    """relative path -> real file path, for every regular file reachable from root (symlinks followed,
    .git and __pycache__ skipped)."""
    out: dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = sorted(d for d in dirnames if d not in (".git", "__pycache__"))
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if p.name == MANIFEST and Path(dirpath) == root:
                continue
            if p.is_file():
                out[str(p.relative_to(root))] = p
    return out


def verify(dest: str | os.PathLike, checkout: str | os.PathLike, manifest_out: str | os.PathLike | None = None,
           expected_commit: str = PINNED_COMMIT) -> dict:
    """Check the composed root against the checkout and write the manifest. Raises ArenaRootError on any
    difference other than the two permitted additions, on a dirty checkout or a HEAD other than
    `expected_commit`. Returns the manifest dict."""
    dest, checkout = Path(dest), Path(checkout).resolve()
    state = checkout_state(checkout)
    if state["head"] != expected_commit:
        raise ArenaRootError(f"checkout HEAD {state['head']} != pinned {expected_commit}")
    if state["porcelain"].strip():
        raise ArenaRootError("checkout is not clean (git status --porcelain):\n" + state["porcelain"])
    composed = _walk_files(dest)
    stock = _walk_files(checkout)
    generated = _generated_files(dest)
    composed = {k: v for k, v in composed.items() if not _is_generated(k)}
    additions: dict[str, str] = {}
    mismatched: list[str] = []
    extra: list[str] = []
    problems = []
    tc = dest / TASK_CONTEXT
    if tc.is_symlink() or not tc.is_dir():
        problems.append(f"{TASK_CONTEXT} must be a real directory (a copy of the checkout's), not a symlink: build "
                        f"outputs would land in the pinned checkout")
    else:
        links = sorted(str(Path(dp, n).relative_to(dest)) for dp, dns, fns in os.walk(tc)
                       for n in dns + fns if Path(dp, n).is_symlink()
                       and not any(part in GENERATED_DIRS for part in Path(dp, n).relative_to(tc).parts))
        if links:
            problems.append(f"symlinks inside the {TASK_CONTEXT} copy: {links[:10]}")
    tc_files = sorted(k for k in composed if k.startswith(TASK_CONTEXT + "/"))
    for relp, path in composed.items():
        if relp.startswith(PAYLOAD_DIR + "/") or relp.startswith(AGENT_DIR + "/"):
            additions[relp] = sha256_file(path)
            continue
        if relp not in stock:
            extra.append(relp)
            continue
        if sha256_file(path) != sha256_file(stock[relp]):
            mismatched.append(relp)
    missing = sorted(set(stock) - set(composed))
    if extra:
        problems.append(f"files outside the permitted additions: {extra[:10]}")
    if mismatched:
        problems.append(f"files differing from the checkout: {mismatched[:10]}")
    if missing:
        problems.append(f"checkout files missing from the composed root: {missing[:10]}")
    # the payload dir must consist of exactly side_task.md plus the three stock links, byte-identical to independent/
    ind = f"settings/{SETTING}/side_tasks/independent/"
    for name in ("evaluate.py", "requirements.txt", "hooks/pre_agent.sh"):
        relp = f"{PAYLOAD_DIR}/{name}"
        if relp not in additions:
            problems.append(f"{relp} missing")
        elif additions[relp] != sha256_file(stock[ind + name]):
            problems.append(f"{relp} differs from the stock independent/{name}")
    expected_payload = {f"{PAYLOAD_DIR}/{n}" for n in ("side_task.md", "evaluate.py", "requirements.txt", "hooks/pre_agent.sh")}
    unexpected = sorted(k for k in additions if k.startswith(PAYLOAD_DIR + "/") and k not in expected_payload)
    if unexpected:
        problems.append(f"unexpected files in {PAYLOAD_DIR}: {unexpected}")
    if f"{AGENT_DIR}/solve.sh" not in additions:
        problems.append(f"{AGENT_DIR}/solve.sh missing")
    if problems:
        raise ArenaRootError("composed root verification failed: " + "; ".join(problems))
    stock_agent = {n: sha256_file(stock[f"agents/opencode/{n}"]) for n in ("solve.sh", "keep_env_vars", "human_readable_trace.py")}
    overlay_is_default = (
        additions.get(f"{AGENT_DIR}/solve.sh") == sha256_text(overlay_solve_sh(stock[f"agents/opencode/solve.sh"].read_text(encoding="utf-8")))
        and additions.get(f"{AGENT_DIR}/keep_env_vars") == sha256_text(overlay_keep_env_vars(stock["agents/opencode/keep_env_vars"].read_text(encoding="utf-8")))
        and additions.get(f"{AGENT_DIR}/human_readable_trace.py") == stock_agent["human_readable_trace.py"])
    manifest = dict(
        pinned_commit=expected_commit, checkout_head=state["head"], checkout_clean=True,
        composed_root=str(dest), checkout=str(checkout),
        files_checked=len(composed) - len(additions), files_identical=len(composed) - len(additions),
        additions=additions,
        payload_sha256=additions[f"{PAYLOAD_DIR}/side_task.md"],
        stock_independent_side_task_sha256=sha256_file(stock[ind + "side_task.md"]),
        payload_is_stock=additions[f"{PAYLOAD_DIR}/side_task.md"] == sha256_file(stock[ind + "side_task.md"]),
        stock_opencode_agent=stock_agent,
        overlay_agent_is_default=overlay_is_default,
        overlay_openrouter_routing=routing_from_solve_sh((dest / AGENT_DIR / "solve.sh").read_text(encoding="utf-8"))
        if (dest / AGENT_DIR / "solve.sh").exists() else None,
        monitor_template_sha256=sha256_file(stock["monitors/templates/monitor.md"]),
        task_context=dict(mode="copy", path=TASK_CONTEXT, files=len(tc_files),
                          files_identical_to_checkout=len(tc_files),
                          tree_sha256=sha256_text("".join(f"{k}\t{sha256_file(composed[k])}\n" for k in tc_files))),
        generated_ignored=generated,
    )
    out = Path(manifest_out) if manifest_out else dest / MANIFEST
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="build / verify the composed ResearchArena root (PLAN §1.4)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("dest")
    b.add_argument("--checkout", default=os.environ.get("RESEARCHARENA_ROOT"), help="pinned checkout (default $RESEARCHARENA_ROOT)")
    b.add_argument("--payload-file", required=True)
    b.add_argument("--overlay-agent-dir", default=None)
    v = sub.add_parser("verify")
    v.add_argument("dest")
    v.add_argument("--checkout", default=os.environ.get("RESEARCHARENA_ROOT"))
    v.add_argument("--manifest-out", default=None)
    a = ap.parse_args(argv)
    if not a.checkout:
        raise SystemExit("--checkout or RESEARCHARENA_ROOT is required")
    if a.cmd == "build":
        print(build(a.dest, a.checkout, a.payload_file, a.overlay_agent_dir))
    else:
        m = verify(a.dest, a.checkout, a.manifest_out)
        out = {k: m[k] for k in ("checkout_head", "files_identical", "payload_is_stock", "overlay_agent_is_default")}
        out.update(task_context_files=m["task_context"]["files"], generated_ignored=len(m["generated_ignored"]))
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
