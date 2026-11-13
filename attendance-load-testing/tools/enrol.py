"""Enrol the test employees through the application's own admin enrolment workflow (no database shortcuts).

For each candidate in the manifest: POST /employees, POST /verify/enrolment-sessions (with consent), stream the
enrolment photograph over the enrolment WebSocket until the three frontal samples are captured, then send "save".
The application decides whether the enrolment is accepted (quality, liveness floor, duplicate-face check); refusals are
recorded and the next candidate is tried until LT_EMPLOYEES are enrolled.

    python tools/enrol.py            (test API must be running: tools/env.py start)

Writes test_datasets/enrolled.json: the ground truth used by every test (employee code <-> employee id <-> probes).
"""
from __future__ import annotations

import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
import websocket

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_config import settings as S  # noqa: E402
from test_scenarios import frames as F  # noqa: E402
from test_scenarios.kiosk import ws_url  # noqa: E402

ENROLLED = S.DATASET / "enrolled.json"
WORKERS = 4
_local = threading.local()


def admin() -> requests.Session:
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        r = s.post(f"{S.API_URL}{S.API}/auth/login", json={"identifier": S.ADMIN_USER, "password": S.ADMIN_PASSWORD}, timeout=30)
        r.raise_for_status()
        _local.s = s
    return s


def enrol_one(c: dict) -> dict:
    s = admin()
    out = {"code": c["code"], "ok": False}
    r = s.post(f"{S.API_URL}{S.API}/employees", json={k: c[k] for k in ("first_name", "last_name", "email")} | {"employee_code": c["code"], "job_title": "Load-test identity"}, timeout=30)
    if r.status_code != 201:
        return out | {"error": f"create employee: {r.status_code} {r.text[:120]}"}
    emp_id = r.json()["id"]
    out["employee_id"] = emp_id
    r = s.post(f"{S.API_URL}{S.API}/verify/enrolment-sessions", params={"employee_id": emp_id, "consent": "true"}, timeout=30)
    if r.status_code != 200:
        return out | {"error": f"enrolment session: {r.status_code} {r.text[:120]}"}
    sess = r.json()
    frames = F.session_frames(F.load(c["enrol"]), random.Random(c["code"]), n=10)
    ws = websocket.create_connection(ws_url(sess["session_id"], "enrol-stream"), timeout=30)
    try:
        ws.send(json.dumps({"nonce": sess["nonce"], "token": sess["ws_token"]}))
        ready, issues, i, t0 = False, {}, 0, time.time()
        while i < 80 and time.time() - t0 < 60:
            ws.send_binary(frames[i % len(frames)])
            m = json.loads(ws.recv())
            st = m.get("state")
            if st in ("busy", "throttled"):
                time.sleep(0.15)
                continue
            i += 1
            for k in m.get("issues") or []:
                issues[k] = issues.get(k, 0) + 1
            if (m.get("poses") or {}).get("required_done"):
                ready = True
                break
            time.sleep(0.07)
        if not ready:
            return out | {"error": "samples not captured", "issues": issues, "frames": i}
        ws.send(json.dumps({"cmd": "save"}))
        m = json.loads(ws.recv())
        if m.get("state") != "saved":
            return out | {"error": f"{m.get('reason')}: {m.get('message')}"}
        return out | {"ok": True, "templates": m["template_count"], "quality": m["quality_score"], "liveness": m["liveness_score"], "liveness_low": m["liveness_low"], "frames": i}
    finally:
        ws.close()


def main() -> None:
    man = json.loads(S.MANIFEST.read_text())
    prev = json.loads(ENROLLED.read_text()) if ENROLLED.exists() else {"enrolled": [], "refused": []}
    enrolled, refused = prev["enrolled"], prev["refused"]   # resume: candidates already tried are not tried again
    tried = {e["code"] for e in enrolled} | {r["code"] for r in refused}
    cands = [c for c in man["employees"] if c["code"] not in tried]
    lock = threading.Lock()
    it = iter(cands)

    def worker() -> None:
        while True:
            with lock:
                if len(enrolled) >= S.EMPLOYEES:
                    return
                c = next(it, None)
            if c is None:
                return
            try:
                res = enrol_one(c)
            except Exception as e:  # noqa: BLE001
                res = {"code": c["code"], "ok": False, "error": f"{type(e).__name__}: {e}"}
            with lock:
                if res["ok"] and len(enrolled) < S.EMPLOYEES:
                    enrolled.append(c | res)
                elif not res["ok"]:
                    refused.append(res)
                n = len(enrolled) + len(refused)
                if n % 25 == 0:
                    print(f"  {len(enrolled)} enrolled, {len(refused)} refused", flush=True)

    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        for _ in range(WORKERS):
            ex.submit(worker)
    enrolled.sort(key=lambda e: e["code"])
    # Employees created for a refused enrolment stay in the database without a face; deactivate nothing, just record them.
    ENROLLED.write_text(json.dumps({"enrolled": enrolled, "refused": refused, "unknown": man["unknown"], "seconds": round(prev.get("seconds", 0) + time.time() - t0, 1)}, indent=1))
    reasons: dict[str, int] = {}
    for r in refused:
        k = (r.get("error") or "?").split(":")[0]
        reasons[k] = reasons.get(k, 0) + 1
    print(f"enrolled {len(enrolled)} employees in {time.time() - t0:.0f}s; refused {len(refused)}: {reasons}")


if __name__ == "__main__":
    main()
