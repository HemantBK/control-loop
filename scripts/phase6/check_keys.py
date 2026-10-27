"""Key check before any GPU run (PLAN Amendment (22), Part A item 5): one free or cheap call per key in the environment
(loaded by `uv run --env-file ../.env`), plus runpodctl's own key. Prints each key's name and result only, never a value.
For OpenRouter it also prints the account balance and the key's own limit, against the batch's need. The agent uses
the main OpenRouter key (Amendment (24)); its limit is reported, not required (Amendment (26): the $25 agent cap and the
spend monitor are the protection).

    uv run --frozen --env-file ../.env python scripts/phase6/check_keys.py [--need-openrouter 25]

Exit 0 iff every key that Phase 6 uses works (OpenRouter, Anthropic, RunPod), and the balance and the key's remaining
limit cover the need. The other keys are checked and reported; they do not change the exit code."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

USED = ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "RUNPOD (runpodctl config)")   # HF_TOKEN: optional in pipeline_redteam.sh, never sent to a pod
NOT_KEYS = ("ARGUS_LLM_PROVIDER", "ARGUS_AGENT_MODEL", "ARGUS_MONITOR_MODEL")


def get(url: str, headers: dict, timeout: float = 20.0) -> tuple[int, dict | None]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {"error": type(e).__name__}


def bearer(name: str) -> dict:
    return {"Authorization": f"Bearer {os.environ[name]}"}


CHECKS = {   # name: (url, headers from the key) - each a read-only call that costs nothing
    "ANTHROPIC_API_KEY": ("https://api.anthropic.com/v1/models?limit=1",
                          lambda k: {"x-api-key": os.environ[k], "anthropic-version": "2023-06-01"}),
    "OPENAI_API_KEY": ("https://api.openai.com/v1/models", bearer),
    "GEMINI_API_KEY": ("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                       lambda k: {"x-goog-api-key": os.environ[k]}),
    "HF_TOKEN": ("https://huggingface.co/api/whoami-v2", bearer),
    "KAGGLE_API_TOKEN": ("https://www.kaggle.com/api/v1/competitions/list?page=1", bearer),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--need-openrouter", type=float, default=25.0,
                    help="US dollars the batch's agent needs: checked on the account and on the key's remaining limit")
    a = ap.parse_args(argv)
    ok_used = True
    # OpenRouter: the key itself (usage, limit) and the account's credits
    if "OPENROUTER_API_KEY" in os.environ:
        st, key = get("https://openrouter.ai/api/v1/key", bearer("OPENROUTER_API_KEY"))
        st2, cr = get("https://openrouter.ai/api/v1/credits", bearer("OPENROUTER_API_KEY"))
        works = st == 200 and key and "data" in key
        line = f"OPENROUTER_API_KEY: {'OK' if works else 'FAIL'} (HTTP {st})"
        if works:
            d = key["data"]
            rem = d.get("limit_remaining")
            lim = d.get("limit")
            line += f"; key usage ${float(d.get('usage') or 0):.2f}, key limit " + \
                    (f"${float(lim):.2f} (remaining ${float(rem):.2f})" if lim is not None else "none")
            if st2 == 200 and cr and "data" in cr:
                bal = float(cr["data"].get("total_credits") or 0) - float(cr["data"].get("total_usage") or 0)
                line += f"; account balance ${bal:.2f}"
                enough = bal >= a.need_openrouter and (rem is None or float(rem) >= a.need_openrouter)
                line += f"; need ${a.need_openrouter:.2f}: {'enough' if enough else 'NOT ENOUGH'}"
                ok_used = ok_used and enough
            else:
                line += f"; account balance unreadable (HTTP {st2})"
                ok_used = False
        else:
            ok_used = False
        print(line)
    else:
        print("OPENROUTER_API_KEY: MISSING"); ok_used = False
    for name, (url, hdr) in CHECKS.items():
        if name not in os.environ:
            print(f"{name}: not set"); ok_used = ok_used and name not in USED
            continue
        st, body = get(url, hdr(name))
        works = st == 200
        tag = "" if name in USED else " (not used by Phase 6)"
        print(f"{name}: {'OK' if works else 'FAIL'} (HTTP {st}){tag}")
        if name in USED:
            ok_used = ok_used and works
    cp = subprocess.run(["runpodctl", "pod", "list", "-o", "json"], capture_output=True, text=True, timeout=120)
    print(f"RUNPOD (runpodctl config): {'OK' if cp.returncode == 0 else 'FAIL'} (rc {cp.returncode})")
    ok_used = ok_used and cp.returncode == 0
    for name in NOT_KEYS:
        if name in os.environ:
            print(f"{name}: a setting, not a key (not called)")
    others = sorted(k for k in os.environ if k.endswith(("_KEY", "_TOKEN")) and k not in CHECKS
                    and k != "OPENROUTER_API_KEY"
                    and not k.startswith("RUNPOD_"))
    if others:
        print("other key-like names, not checked: " + ", ".join(others))
    print("RESULT: " + ("PASS" if ok_used else "FAIL") + " (Anthropic has no balance endpoint for this key: the owner "
          "checks the Anthropic console balance and the Claude plan's usage limit)")
    return 0 if ok_used else 1


if __name__ == "__main__":
    sys.exit(main())
