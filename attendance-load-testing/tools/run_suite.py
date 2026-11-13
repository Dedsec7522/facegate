"""Run the staged test plan against the isolated instance, driving the already running Locust master over its REST API.

    python tools/run_suite.py                     all stages in test_config/stages.json
    python tools/run_suite.py --only "Test 2"     stages whose name contains the text (repeatable)
    python tools/run_suite.py --from "Test 6"     start at that stage

Per stage: restore the database baseline and restart the test API, apply stage settings through the admin API, start
the swarm, wait until every virtual employee has finished its workflow, stop, save Locust's HTML report and CSVs,
validate the stored attendance rows, and probe the API again to see how it recovered.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_config import settings as S  # noqa: E402
from tools import env  # noqa: E402
from tools.validate_db import validate  # noqa: E402

L = S.LOCUST_WEB
SUITE = S.RESULTS / "suite.json"
RUNS = S.RESULTS / "runs"


def data() -> dict:
    """Dashboard snapshot from the Locust master. The master shares the machine with the server under test and can
    be slow to answer for a moment; one slow poll must not fail a whole stage."""
    for attempt in range(4):
        try:
            return requests.get(f"{L}/facegate/data", timeout=30).json()
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2)
    raise RuntimeError("unreachable")


def wait_state(states: tuple[str, ...], timeout: float = 60) -> str:
    t0 = time.time()
    st = "?"
    while time.time() - t0 < timeout:
        st = data()["state"]
        if st in states:
            return st
        time.sleep(0.5)
    return st


def apply_settings(patch: dict) -> dict:
    s = requests.Session()
    s.post(f"{S.API_URL}{S.API}/auth/login", json={"identifier": S.ADMIN_USER, "password": S.ADMIN_PASSWORD}, timeout=30).raise_for_status()
    r = s.patch(f"{S.API_URL}{S.API}/settings", json=patch, timeout=30)
    r.raise_for_status()
    return r.json()


def current_settings() -> dict:
    s = requests.Session()
    s.post(f"{S.API_URL}{S.API}/auth/login", json={"identifier": S.ADMIN_USER, "password": S.ADMIN_PASSWORD}, timeout=30).raise_for_status()
    return s.get(f"{S.API_URL}{S.API}/settings", timeout=30).json()


def probe_health(n: int = 10) -> dict:
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            ok = requests.get(f"{S.API_URL}/api/health", timeout=10).status_code == 200
        except Exception:  # noqa: BLE001
            ok = False
        ts.append((time.perf_counter() - t0) * 1000 if ok else None)
        time.sleep(0.2)
    good = [t for t in ts if t is not None]
    return {"ok": len(good), "of": n, "median_ms": round(sorted(good)[len(good) // 2], 1) if good else None, "max_ms": round(max(good), 1) if good else None}


def session_arrivals(log_from: int, t_release: float | None) -> dict | None:
    """Server-side arrival times of POST /verify/sessions, from the test API's timestamped access log."""
    pat = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}) ACCESS .*\"POST /api/v1/verify/sessions HTTP")
    ts = []
    with open(env.API_LOG, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(log_from)
        for line in fh:
            m = pat.match(line)
            if m:
                ts.append(datetime.fromisoformat(m.group(1)).timestamp())
    if not ts or not t_release:
        return None
    # The access log line is written when the response is sent, so these are completion times of the session request.
    rel = sorted(t - t_release for t in ts if t >= t_release - 1)
    if not rel:
        return None
    within = lambda s: sum(1 for x in rel if x <= s)  # noqa: E731
    return {"requests_logged": len(rel), "first_s": round(rel[0], 3), "last_s": round(rel[-1], 3), "answered_within_0.5s": within(0.5), "answered_within_1s": within(1.0),
            "answered_within_2s": within(2.0), "answered_within_5s": within(5.0), "busiest_100ms": max(sum(1 for x in rel if a <= x < a + 0.1) for a in rel)}


STALL_S = 240   # longest legitimate silence: the 125 s wait before check-out plus one 70 s session deadline


def run_stage(st: dict, suite: dict, idx: int, attempt: int = 1) -> dict:
    def mark(**kw):
        suite["stages"][idx].update(kw)
        SUITE.write_text(json.dumps(suite, indent=1))

    print(f"\n=== {st['name']}: {st['scenario']}, {st['users']} users ===", flush=True)
    mark(status="running", started=time.time(), note=st.get("note", ""))
    wait_state(("ready", "stopped"), 120)
    env.reset()
    applied = apply_settings(st["settings"]) if st.get("settings") else current_settings()
    log_from = env.API_LOG.stat().st_size
    requests.post(f"{L}/stats/reset", timeout=15)
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}_{re.sub(r'[^a-z0-9]+', '-', st['name'].lower()).strip('-')}"
    form = {"user_count": st["users"], "spawn_rate": st["spawn_rate"], "host": S.API_URL, "scenario": st["scenario"], "stage": st["name"], "run_id": run_id,
            "hold_seconds": st.get("hold_seconds", 300)}
    r = requests.post(f"{L}/swarm", data=form, timeout=30)
    r.raise_for_status()
    if not r.json().get("success"):
        raise SystemExit(f"swarm refused: {r.text}")
    t0, d, timed_out, died = time.time(), {}, False, ""
    progress, t_progress = None, time.time()
    while True:
        time.sleep(2)
        d = data()
        fl = d["flows"]
        if d["meta"].get("run_id") == run_id and fl["planned"] and fl["done"] >= fl["planned"]:
            break
        # Never wait on a run that is no longer running. Locust stops a test by itself when it loses its workers, and
        # a stage that has produced nothing new for longer than any legitimate pause is stuck, not slow.
        if time.time() - t0 > 8 and (d["finished"] or d["state"] not in ("spawning", "running")):
            died = f"Locust stopped the run by itself after {int(time.time() - t0)}s (state {d['state']}, {fl['done']}/{fl['planned']} finished)"
        now = (d["predictions"], fl["done"], d["locust"]["requests"])
        if now != progress:
            progress, t_progress = now, time.time()
        elif time.time() - t_progress > STALL_S:
            died = f"no request, verdict or finished workflow for {STALL_S}s ({fl['done']}/{fl['planned']} finished)"
        if died:
            print(f"  {died}", flush=True)
            break
        if time.time() - t0 > st["timeout_s"]:
            timed_out = True
            print(f"  timeout after {st['timeout_s']}s: {fl['done']}/{fl['planned']} finished", flush=True)
            break
        if int(time.time() - t0) % 30 < 2:
            v = d["verdicts"]
            print(f"  {int(time.time() - t0):4d}s  users {d['users']:3d}  in flight {d['inflight']['now']:3d}  done {fl['done']}/{fl['planned']}  correct {v.get('correct', 0)}  rejected {v.get('rejected', 0)}  errors {v.get('error', 0)}", flush=True)
    requests.post(f"{L}/stop", timeout=30)
    for _ in range(60):
        d = data()
        if d["finished"]:
            break
        time.sleep(0.5)
    rd = RUNS / run_id
    for url, name in ((f"{L}/stats/report", "locust_report.html"), (f"{L}/stats/requests/csv", "locust_stats.csv"), (f"{L}/stats/failures/csv", "locust_failures.csv"),
                      (f"{L}/facegate/predictions?run={run_id}&format=csv", "predictions.csv")):
        try:
            (rd / name).write_bytes(requests.get(url, timeout=120).content)
        except Exception as e:  # noqa: BLE001
            print(f"  could not save {name}: {e}")
    if died and attempt < 3:
        print(f"  retrying the stage (attempt {attempt + 1} of 3)", flush=True)
        (rd / "ABANDONED.txt").write_text(died)
        wait_state(("ready", "stopped"), 120)
        return run_stage(st, suite, idx, attempt + 1)
    timed_out = timed_out or bool(died)
    db = validate(run_id)
    summary = json.loads((rd / "summary.json").read_text())
    info = {"settings": applied, "timed_out": timed_out, "stopped_early": died, "attempt": attempt, "recovery_immediately": probe_health()}
    time.sleep(15)
    info["recovery_after_15s"] = probe_health()
    if summary.get("burst"):
        info["burst_server_side"] = session_arrivals(log_from, summary["burst"].get("t_release"))
    (rd / "stage_info.json").write_text(json.dumps(info, indent=1))
    m = summary["metrics"]
    v = summary["verdicts"]
    print(f"  done in {summary['duration_s']}s: {summary['predictions']} recognitions, verdicts {v}, attendance {summary['attendance']}, "
          f"p95 {m['recognition_ms']['p95']} ms, peak in flight {summary['inflight_peak']}, DB {'consistent' if db['ok'] else str(db['problems']) + ' problems'}", flush=True)
    wrong = v.get("incorrect", 0) + v.get("false_accept", 0)
    mark(status="done", ended=time.time(), run_id=run_id, ok=db["ok"] and wrong == 0 and summary["attendance"]["unexpected"] == 0 and not timed_out)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--from", dest="start", default="")
    ap.add_argument("--append", action="store_true", help="keep the finished stages already listed in suite.json")
    a = ap.parse_args()
    stages = json.loads((S.ROOT / "test_config" / "stages.json").read_text())["stages"]
    if a.start:
        i = next(i for i, s in enumerate(stages) if a.start.lower() in s["name"].lower())
        stages = stages[i:]
    if a.only:
        stages = [s for s in stages if any(o.lower() in s["name"].lower() for o in a.only)]
    try:
        data()
    except Exception:  # noqa: BLE001
        raise SystemExit(f"Locust is not running on {L}; start it first (start.ps1)")
    kept = []
    started = time.time()
    if a.append and SUITE.exists():
        old = json.loads(SUITE.read_text())
        started = old.get("started", started)
        names = {s["name"] for s in stages}
        kept = [s for s in old["stages"] if s.get("status") == "done" and s.get("run_id") and s["name"] not in names]
    suite = {"started": started, "finished": False, "stages": kept + [{"name": s["name"], "status": "pending"} for s in stages]}
    SUITE.write_text(json.dumps(suite, indent=1))
    for i, st in enumerate(stages, start=len(kept)):
        try:
            run_stage(st, suite, i)
        except Exception as e:  # noqa: BLE001 - one failed stage must not hide the others
            print(f"  STAGE FAILED: {type(e).__name__}: {e}", flush=True)
            suite["stages"][i].update(status="done", ok=False, note=f"{type(e).__name__}: {e}")
            try:
                requests.post(f"{L}/stop", timeout=30)
            except Exception:  # noqa: BLE001
                pass
    suite["finished"] = True
    suite["ended"] = time.time()
    SUITE.write_text(json.dumps(suite, indent=1))
    print("\nsuite complete")


if __name__ == "__main__":
    main()
