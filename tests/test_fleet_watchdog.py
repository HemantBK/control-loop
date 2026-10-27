"""No-network tests of the fleet watchdog (control_loop/adapters/researcharena/fleet_watchdog.py; PLAN Amendment (22),
Part A): per-pod and per-batch caps, the idle rule on the job's own process, copy before delete, the pods it must never
touch, failed listings, dry run and a restart."""
from __future__ import annotations

import json

import pytest

from control_loop.adapters.researcharena import fleet_watchdog as fw

T0 = fw.parse_time("2026-10-25T10:00:00Z")
BUSY = "JOB ep01\nGPU 87\nAPPS 1\n"
IDLE = "GPU 0\nAPPS 0\n"


def pod(pid="g1", name="p6-a", minutes=1.0, rate=3.99):
    return {"id": pid, "name": name, "createdAt": "2026-10-25T10:00:00Z", "costPerHr": rate, "_m": minutes}


class Rig:
    """A watchdog over scripted listings, a fake shell (copy and probe commands) and a fake clock."""

    def __init__(self, tmp_path, pods, *, batch=None, regs=None, probe=IDLE, copy_rc=0, dry=False, own="cpu1"):
        self.state = tmp_path / "wd"
        (self.state / "pods").mkdir(parents=True)
        (self.state / "batch.json").write_text(json.dumps(batch or {"batch_id": "b1", "gpu_cap_usd": 100,
                                                                   "default_cap_usd": 4, "default_cap_min": 60}))
        for name, reg in (regs or {}).items():
            (self.state / "pods" / f"{name}.json").write_text(json.dumps(reg))
        self.pods, self.t, self.logs, self.deleted, self.cmds = pods, T0 + 60, [], [], []
        self.probe, self.copy_rc, self.fail_list = probe, copy_rc, 0
        self.w = self.make(dry, own)

    def make(self, dry=False, own="cpu1"):
        return fw.Watchdog(self.state, self.logs.append, dry_run=dry, listers=[self.lister],
                           real_delete=self.real_delete, shell=self.shell, now=lambda: self.t, idle_s=900, probe_s=60,
                           beat_s=60, own_id=own)

    def lister(self):
        if self.fail_list:
            self.fail_list -= 1
            raise fw.ListingError("rc=1: boom")
        return [p for p in self.pods if p["id"] not in self.deleted]

    def real_delete(self, pid):
        self.deleted.append(pid)
        return True, "ok"

    def shell(self, cmd, timeout):
        self.cmds.append(cmd)
        if cmd.startswith("copy"):
            return self.copy_rc, "copied" if self.copy_rc == 0 else "rsync error"
        return 0, self.probe

    def step(self, seconds=30, n=1):
        for _ in range(n):
            self.t += seconds
            self.w.poll_once()


def reg(name, cap_usd=4.0, cap_min=60, copy=True, probe=True):
    return {"name": name, "cap_usd": cap_usd, "cap_min": cap_min,
            "copy_cmd": f"copy {name}" if copy else None, "probe_cmd": f"probe {name}" if probe else None}


def test_pod_cap_copies_then_deletes(tmp_path):
    r = Rig(tmp_path, [pod()], regs={"p6-a": reg("p6-a", cap_usd=1.0)}, probe=BUSY)
    r.step(60, 10)
    assert not r.deleted
    r.t = T0 + 3600 * 1.0 / 3.99 + 5          # cost just over $1
    r.w.poll_once()
    assert r.deleted == ["g1"]
    assert r.cmds.index("copy p6-a") < len(r.cmds)
    assert any("copy verified" in l for l in r.logs) and any("pod cap" in l for l in r.logs)


def test_age_cap_deletes_even_when_the_copy_fails(tmp_path):
    r = Rig(tmp_path, [pod()], regs={"p6-a": reg("p6-a", cap_min=10)}, probe=BUSY, copy_rc=1)
    r.t = T0 + 601
    r.w.poll_once()
    assert r.deleted == ["g1"] and any("copy FAILED" in l for l in r.logs)


def test_idle_rule_needs_15_minutes_of_no_job(tmp_path):
    r = Rig(tmp_path, [pod()], regs={"p6-a": reg("p6-a")}, probe=BUSY)
    r.step(60, 5)
    r.probe = IDLE
    r.step(60, 14)
    assert not r.deleted
    r.probe = BUSY                              # a job starts again: the clock resets
    r.step(60, 1)
    r.probe = IDLE
    r.step(60, 15)
    assert not r.deleted
    r.step(60, 2)
    assert r.deleted == ["g1"] and "copy p6-a" in r.cmds


def test_gpu_activity_or_a_compute_process_is_not_idle(tmp_path):
    for out in ("GPU 5\nAPPS 0\n", "GPU 0\nAPPS 1\n"):
        r = Rig(tmp_path / out[:5].strip(), [pod()], regs={"p6-a": reg("p6-a")}, probe=out)
        r.step(60, 40)
        assert not r.deleted


def test_failed_probe_is_never_idle(tmp_path):
    r = Rig(tmp_path, [pod()], regs={"p6-a": reg("p6-a")}, probe="ssh: connect refused")
    r.step(60, 40)
    assert not r.deleted and any("not counted as idle" in l for l in r.logs)


def test_idle_close_retries_a_failed_copy_then_deletes(tmp_path):
    r = Rig(tmp_path, [pod()], regs={"p6-a": reg("p6-a")}, copy_rc=1)
    r.step(60, 16)
    assert not r.deleted
    r.step(30, 2)
    assert r.deleted == ["g1"] and r.cmds.count("copy p6-a") == 3


def test_batch_cap_closes_every_pod_and_writes_stop(tmp_path):
    pods = [pod("g1", "p6-a"), pod("g2", "p6-b")]
    r = Rig(tmp_path, pods, batch={"batch_id": "b1", "gpu_cap_usd": 1.0}, regs={n: reg(n) for n in ("p6-a", "p6-b")},
            probe=BUSY)
    r.t = T0 + 3600 * 0.5 / 3.99 + 5           # each pod just over $0.50: $1.00 in all
    r.w.poll_once()
    assert sorted(r.deleted) == ["g1", "g2"] and (r.state / "STOP").exists()


def test_ledger_counts_pods_deleted_by_anyone_toward_the_batch(tmp_path):
    r = Rig(tmp_path, [pod("g1", "p6-a")], batch={"batch_id": "b1", "gpu_cap_usd": 1.0}, regs={"p6-a": reg("p6-a")},
            probe=BUSY)
    r.t = T0 + 3600 * 0.6 / 3.99
    r.w.poll_once()
    r.deleted.append("g1")                       # the runner deletes it after its last verified copy
    r.step(30, 3)
    led = [json.loads(l) for l in (r.state / "ledger.jsonl").read_text().splitlines()]
    assert led[0]["pod_id"] == "g1" and led[0]["closed_by"] == "not the watchdog" and led[0]["usd"] == pytest.approx(0.6, abs=0.01)
    r.pods.append(pod("g2", "p6-b"))             # a second pod: $0.60 closed + its own cost
    (r.state / "pods" / "p6-b.json").write_text(json.dumps(reg("p6-b")))
    r.t = T0 + 3600 * 0.41 / 3.99
    r.w.poll_once()
    assert "g2" in r.deleted and (r.state / "STOP").exists()


def test_never_touches_other_pods_or_its_own(tmp_path):
    old = pod("cpu1", "p6-cpu", minutes=1)        # carries the prefix but is the pod the watchdog runs on
    other = pod("x9", "ubuntu-cpu-8c-32g")
    r = Rig(tmp_path, [old, other], batch={"batch_id": "b1", "gpu_cap_usd": 0.01}, probe=IDLE)
    r.t = T0 + 30 * 3600
    r.step(60, 30)
    assert r.deleted == []


def test_unregistered_p6_pod_gets_the_batch_defaults(tmp_path):
    r = Rig(tmp_path, [pod("g7", "p6-stray")])
    r.t = T0 + 3601
    r.w.poll_once()
    assert r.deleted == ["g7"] and any("UNREGISTERED" in l for l in r.logs)


def test_failed_listing_is_not_gone_and_not_an_action(tmp_path):
    r = Rig(tmp_path, [pod()], regs={"p6-a": reg("p6-a")}, probe=BUSY)
    r.step(30, 2)
    r.fail_list = 10
    r.step(30, 10)
    assert not (r.state / "ledger.jsonl").exists() and r.deleted == []
    assert sum("list error (not counted as gone)" in l for l in r.logs) == 10


def test_dry_run_writes_one_would_delete_line_and_deletes_nothing(tmp_path):
    r = Rig(tmp_path, [pod()], regs={"p6-a": reg("p6-a", cap_usd=0.01)}, dry=True)
    r.step(60, 5)
    assert r.deleted == [] and sum("would delete g1" in l for l in r.logs) == 1 and r.cmds.count("copy p6-a") == 1


def test_fake_pods_are_removed_from_the_fake_file(tmp_path):
    f = tmp_path / "fake.json"
    f.write_text(json.dumps([{k: v for k, v in pod("f1", "p6-fake-a").items() if k != "_m"}]))
    fake = fw.FakePods(f)
    r = Rig(tmp_path, [], regs={"p6-fake-a": reg("p6-fake-a", cap_usd=0.01)})
    r.w = fw.Watchdog(r.state, r.logs.append, dry_run=True, listers=[fake.list], fake=fake,
                      real_delete=r.real_delete, shell=r.shell, now=lambda: r.t, own_id="cpu1")
    r.step(60, 1)
    assert json.loads(f.read_text()) == [] and r.deleted == []
    r.step(30, 3)
    assert json.loads((r.state / "ledger.jsonl").read_text().splitlines()[0])["fake"] is True


def test_idle_clock_survives_a_restart(tmp_path):
    r = Rig(tmp_path, [pod()], regs={"p6-a": reg("p6-a")})
    r.step(60, 10)                              # idle for about 9 minutes
    r.w = r.make()                              # the restart loop starts a new process
    r.step(60, 7)
    assert r.deleted == ["g1"]


def test_probe_parser():
    assert fw.parse_probe("JOB ep01\nJOB ep02\nGPU 3\nAPPS 2\n") == (["ep01", "ep02"], 3, 2)
    with pytest.raises(ValueError):
        fw.parse_probe("JOB ep01\n")


def test_idle_clock_is_saved_the_moment_it_starts(tmp_path):
    """2026-10-26 test: the watchdog was killed one poll after a pod went idle, and its successor started the clock
    again. The clock is now saved when it starts."""
    r = Rig(tmp_path, [pod()], regs={"p6-a": reg("p6-a")})
    r.step(60, 1)                               # idle from this poll
    r.w = r.make()                              # killed at once, restarted
    r.step(60, 15)
    assert r.deleted == ["g1"]


def test_a_pod_awaiting_the_ledger_still_counts_toward_the_batch(tmp_path):
    """After a delete, a pod enters the ledger only after 3 listings without it; meanwhile its last cost still counts."""
    pods = [pod("g1", "p6-a"), pod("g2", "p6-b")]
    r = Rig(tmp_path, pods, batch={"batch_id": "b1", "gpu_cap_usd": 1.0}, regs={n: reg(n) for n in ("p6-a", "p6-b")},
            probe=BUSY)
    r.t = T0 + 3600 * 0.45 / 3.99
    r.w.poll_once()                             # $0.90 live
    r.deleted.append("g1")                      # the runner deletes p6-a; it is not in the ledger yet
    r.t = T0 + 3600 * 0.56 / 3.99               # p6-b alone is $0.56; with p6-a's last $0.45 the batch is over $1.00
    r.w.poll_once()
    assert (r.state / "STOP").exists() and "g2" in r.deleted


def test_a_gone_pod_leaves_no_idle_clock(tmp_path):
    r = Rig(tmp_path, [pod()], regs={"p6-a": reg("p6-a")})
    r.step(60, 3)                                # idle clock running
    r.deleted.append("g1")                       # deleted by the runner
    r.step(60, 4)
    assert "g1" not in r.w.idle_since and json.loads((r.state / "seen.json").read_text())["g1"]["idle_since"] is None
