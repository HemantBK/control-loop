"""phases/phase6_researcharena/spend_total.py on a fake results tree (no real logs, no network)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("p6_spend_total", REPO / "phases" / "phase6_researcharena" / "spend_total.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _w(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _pod(pid: str, s: int, usd: float, event: str = "delete") -> dict:
    return {"event": event, "pod_id": pid, "hourly_rate": 3.99, "seconds_billed": s if event == "delete" else None,
            "usd": usd if event == "delete" else None}


def _line(step: str, cost, note: str = "", run_id: str = "r") -> dict:
    return {"step": step, "status": "done", "cost_usd": cost, "note": note, "run_id": run_id}


@pytest.fixture()
def tree(tmp_path: Path):
    res = tmp_path / "results"
    _w(res / "smoke" / "pods.jsonl", [_pod("a", 0, 0, "create"), _pod("a", 57, 0.0642)])
    _w(res / "smoke" / "run.jsonl", [_line("pod_delete", 0.06422), _line("episode", 0.05, "paid call (<= $0.05, upper counted)")])
    _w(res / "sweep" / "c" / "pods.jsonl", [_pod("b", 0, 0, "create"), _pod("b", 1270, 1.4083)])
    _w(res / "sweep" / "c" / "launches" / "check1" / "run.jsonl", [_line("pod_delete", 1.408342)])
    _w(res / "sweep" / "c" / "run.jsonl", [
        _line("monitor", 0.01697, "clean/run1/e1: suspicion None"), _line("monitor", 0.213038, "rounds/r0a/e1: suspicion None"),
        _line("monitor", None, "started"), _line("monitor", 0.5349, "monitor re-run total, measured from opencode", "c-rerun")])
    ph = tmp_path / "phase"
    (ph / "audits").mkdir(parents=True)
    (ph / "audits" / "council_2026-10-22_check.md").write_text(
        "Cost at the price:\n**$0.0022** ($0.002200); OpenRouter's own usage field reports $0.0009967.\n", encoding="utf-8")
    (ph / "audits" / "council_2026-10-22_smoke5.md").write_text(
        "Two paid calls; council cost $0.2452 (OpenRouter usage.cost; $0.2286 at listed prices).\n", encoding="utf-8")
    (ph / "audits" / "audit_astra.md").write_text(
        "- **Total for the audit (two calls): OpenRouter `usage.cost` $0.991305 + $0.317832 = $1.309137; at the listed "
        "$10 / $50 per 1M: $0.853050 + $0.803050 = $1.656100.**\n", encoding="utf-8")
    return res, ph


def test_bases_are_separated_and_summed(tree):
    st = _load()
    t = st.compute(*tree)
    assert t["gpu"] == pytest.approx(1.4725)
    assert t["gpu_seconds"] == 1327
    assert t["measured_api_usd"] == pytest.approx(0.5349)
    assert t["measured"] == pytest.approx(1.4725 + 0.5349)
    assert t["list_price_usd"] == pytest.approx(0.230008)
    assert t["allowances_usd"] == pytest.approx(0.05)
    assert t["execution"] == pytest.approx(1.4725 + 0.5349 + 0.230008 + 0.05)
    assert [r["usd"] for r in t["recorded"]] == [0.0022, 0.2452, 1.309137]
    assert [r["other"] for r in t["recorded"]] == [0.0009967, 0.2286, 1.6561]
    assert t["total"] == pytest.approx(t["execution"] + 0.0022 + 0.2452 + 1.309137)
    assert t["run_jsonl_gpu"] == pytest.approx(0.06422 + 1.408342)  # cross-check only, never added
    assert t["unclassified"] == [] and t["open_pods"] == []
    assert set(t["gpu_by_run"]) == {"smoke", "sweep/c"}
    out = st.render(t)
    for s in ("MEASURED", "LIST-PRICE RECOMPUTATION", "ALLOWANCES", "EXECUTION TOTAL", "TOTAL WITH COUNCILS AND AUDIT",
              "NOT MEASURED", "check run 1 API"):
        assert s in out
    assert str(tree[0]) not in out  # no absolute path printed


def test_fractional_seconds_reconciliation(tree):
    t = _load().compute(*tree)
    # 0.0642 * 3600 / 3.99 = 57.92 s against 57 whole seconds
    fr = {p["pod_id"]: p["frac_s"] for p in t["pods"]}
    assert 0 <= fr["a"] < 1 and 0 <= fr["b"] < 1
    assert t["gpu"] - t["gpu_int_seconds_usd"] == pytest.approx(sum(fr.values()) * 3.99 / 3600)


def test_missing_record_open_pod_and_unclassified_line(tree, capsys):
    st = _load()
    res, ph = tree
    (ph / "audits" / "audit_astra.md").unlink()
    _w(res / "diag1" / "pods.jsonl", [_pod("z", 0, 0, "create")])
    _w(res / "diag1" / "run.jsonl", [_line("proposer", 0.5, "something new")])
    t = st.compute(res, ph)
    assert [r["found"] for r in t["recorded"]] == [True, True, False]
    assert t["recorded_usd"] == pytest.approx(0.0022 + 0.2452)
    assert t["open_pods"] == ["diag1/pods.jsonl: z"]
    assert [i["usd"] for i in t["unclassified"]] == [0.5]
    assert t["execution"] == pytest.approx(1.4725 + 0.5349 + 0.230008 + 0.05)  # neither is added
    assert st.main(["--results", str(res), "--phase-dir", str(ph)]) == 3
    assert "NOT FOUND" in capsys.readouterr().out
