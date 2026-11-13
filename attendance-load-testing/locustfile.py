"""FaceGate attendance load test (Locust).

Every virtual user is one enrolled test employee with a known identity. It performs the real kiosk workflow against the
isolated test instance: create a verification session, stream camera frames over the WebSocket until the server gives
a verdict, then record attendance with the single-use token. Every verdict is compared with the ground truth and
written to test_results/runs/<run>/predictions_*.jsonl; the dashboard at /facegate reads those files live.

Scenarios (--scenario, also selectable in the Locust web form):
  attendance   LOGIN -> immediate duplicate LOGIN (must be refused) -> LOGOUT after the duplicate window -> duplicate LOGOUT
  burst        all users prepare, then every recognition request is released at the same instant
  sustained    repeated scans for --hold-seconds (9 in 10 genuine, 1 in 10 a person who is not enrolled)
  accuracy     every probe photo once, plus unknown people, empty frames, two faces, dark / bright / blurred frames
  liveness     genuine photos against the kiosk's passive anti-spoofing policy (set by the suite for that stage)

Run distributed (Windows has no --processes): one master with the web UI plus LT_WORKERS workers; see start.ps1.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import gevent
import gevent.event
import numpy as np
import psutil
from locust import HttpUser, constant, events, task
import locust.runners as _runners
from locust.runners import MasterRunner, WorkerRunner

# The master declares a worker dead after 3 missed one-second heartbeats and then stops the whole test. On a machine
# that is also running the server under test, a worker can be descheduled for longer than that while 500 users start,
# which silently ended three stages. Twenty seconds still catches a worker that has really died.
_runners.HEARTBEAT_LIVENESS = 20

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_config import settings as S  # noqa: E402
from test_scenarios import frames as F  # noqa: E402
from test_scenarios import kiosk as K  # noqa: E402

RUNS = S.RESULTS / "runs"
CURRENT = S.RESULTS / "current_run.json"
SUITE = S.RESULTS / "suite.json"
WORKERS = max(1, int(os.environ.get("LT_WORKERS", "4")))
SCENARIOS = ["attendance", "burst", "sustained", "accuracy", "liveness"]

_gt = json.loads((S.DATASET / "enrolled.json").read_text()) if (S.DATASET / "enrolled.json").exists() else {"enrolled": [], "unknown": []}
EMPLOYEES: list[dict] = _gt["enrolled"]
UNKNOWN: list[dict] = _gt["unknown"]
CODE_BY_ID = {e["employee_id"]: e["code"] for e in EMPLOYEES}
# Load stages: employees whose probe photos the application's quality gate can process come first (tools/screen_probes.py),
# so a stage of N users uses N employees who can actually be scanned. The accuracy pass ignores this and uses every probe.
LOAD_EMPLOYEES: list[dict] = sorted(EMPLOYEES, key=lambda e: (not e.get("load_probes", e["probes"]), e["code"]))


# ------------------------------------------------------------------------------------------------------------------
# Per-process state
# ------------------------------------------------------------------------------------------------------------------
class Ctx:
    run_id = ""
    run_dir: Path | None = None
    scenario = "attendance"
    stage = "manual"
    started = 0.0
    hold = 300
    users = 0
    worker = 0            # this process's partition index
    partitions = 1
    fh = None             # this process's prediction file
    queue: deque = deque()   # work items for this process's users (employees or accuracy cases)
    gate = gevent.event.Event()
    release_at = 0.0
    running = False


class Inflight:
    """Recognition sessions whose WebSocket is open right now in this process."""
    n = 0
    peak = 0

    @classmethod
    def enter(cls):
        cls.n += 1
        cls.peak = max(cls.peak, cls.n)

    @classmethod
    def leave(cls):
        cls.n -= 1


def _write(obj: dict) -> None:
    if Ctx.fh:
        Ctx.fh.write(json.dumps(obj, separators=(",", ":")) + "\n")
        Ctx.fh.flush()


def accuracy_cases() -> list[dict]:
    """Deterministic list of labelled inputs for the accuracy pass (same list in every process)."""
    cases: list[dict] = []
    for e in EMPLOYEES:
        for p in e["probes"]:
            cases.append({"category": "genuine", "emp": e, "image": p})
    for u in UNKNOWN:
        cases.append({"category": "unknown", "label": u["id"], "image": u["image"]})
    for i in range(40):
        cases.append({"category": "no_face", "label": f"EMPTY{i + 1:02d}"})
    for i in range(40):
        a, b = UNKNOWN[i % len(UNKNOWN)], UNKNOWN[(i + 37) % len(UNKNOWN)]
        cases.append({"category": "two_faces", "label": f"PAIR{i + 1:02d}", "image": a["image"], "image_b": b["image"]})
    for variant in ("dark", "bright", "blur"):
        for e in EMPLOYEES[:100]:
            cases.append({"category": f"genuine_{variant}", "emp": e, "image": e["probes"][0], "variant": variant})
    return cases


def liveness_cases() -> list[dict]:
    return [{"category": "genuine", "emp": e, "image": (e.get("load_probes") or e["probes"])[0]} for e in LOAD_EMPLOYEES[:60]]


def planned_flows(scenario: str, users: int) -> int:
    if scenario == "accuracy":
        return len(accuracy_cases())
    if scenario == "liveness":
        return len(liveness_cases())
    return min(users, len(EMPLOYEES))


# ------------------------------------------------------------------------------------------------------------------
# Command line / web form parameters
# ------------------------------------------------------------------------------------------------------------------
@events.init_command_line_parser.add_listener
def _args(parser):
    parser.add_argument("--scenario", choices=SCENARIOS, default="attendance", help="Which workflow the virtual employees run")
    parser.add_argument("--stage", default="manual", help="Label for this run (shown in the dashboard and reports)")
    parser.add_argument("--run-id", default="", help="Run folder name; generated when empty")
    parser.add_argument("--hold-seconds", type=int, default=300, help="Duration of the sustained scenario")


# ------------------------------------------------------------------------------------------------------------------
# Run lifecycle
# ------------------------------------------------------------------------------------------------------------------
@events.test_start.add_listener
def _start(environment, **_):
    o = environment.parsed_options
    runner = environment.runner
    is_worker = isinstance(runner, WorkerRunner)
    Ctx.scenario, Ctx.stage, Ctx.hold = o.scenario, o.stage, int(o.hold_seconds)
    Ctx.gate = gevent.event.Event()
    Ctx.release_at, Ctx.running = 0.0, True
    Inflight.n = Inflight.peak = 0
    if is_worker:
        cur = {}
        for _ in range(40):   # the master writes this file in its own test_start, just before it tells workers to spawn
            try:
                cur = json.loads(CURRENT.read_text())
                if time.time() - cur["started"] < 60:
                    break
            except Exception:  # noqa: BLE001
                pass
            gevent.sleep(0.05)
        Ctx.run_id, Ctx.started, Ctx.users = cur.get("run_id", "orphan"), cur.get("started", time.time()), cur.get("users", 0)
        Ctx.worker, Ctx.partitions = runner.worker_index % WORKERS, WORKERS
    else:
        Ctx.users = int(getattr(runner, "target_user_count", 0) or o.num_users or 0)
        Ctx.started = time.time()
        Ctx.run_id = o.run_id or f"{datetime.now():%Y%m%d-%H%M%S}_{Ctx.stage}_{Ctx.scenario}_{Ctx.users}u"
        Ctx.worker, Ctx.partitions = 0, (WORKERS if isinstance(runner, MasterRunner) else 1)
        (RUNS / Ctx.run_id).mkdir(parents=True, exist_ok=True)
        meta = {"run_id": Ctx.run_id, "stage": Ctx.stage, "scenario": Ctx.scenario, "users": Ctx.users, "started": Ctx.started,
                "planned": planned_flows(Ctx.scenario, Ctx.users), "hold_seconds": Ctx.hold, "target": S.API_URL, "enrolled_employees": len(EMPLOYEES)}
        CURRENT.write_text(json.dumps(meta))
        (RUNS / Ctx.run_id / "meta.json").write_text(json.dumps(meta, indent=1))
        AGG.reset(meta)
    Ctx.run_dir = RUNS / Ctx.run_id
    Ctx.run_dir.mkdir(parents=True, exist_ok=True)
    if not isinstance(runner, MasterRunner):   # workers and a single local process generate load and write records
        Ctx.fh = open(Ctx.run_dir / f"predictions_w{Ctx.worker}.jsonl", "a", encoding="utf-8")
        items = accuracy_cases() if Ctx.scenario == "accuracy" else liveness_cases() if Ctx.scenario == "liveness" else LOAD_EMPLOYEES
        Ctx.queue = deque(x for i, x in enumerate(items) if i % Ctx.partitions == Ctx.worker)
        gevent.spawn(_inflight_beacon)


def _inflight_beacon() -> None:
    while Ctx.running:
        _write({"type": "inflight", "w": Ctx.worker, "t": time.time(), "n": Inflight.n, "peak": Inflight.peak})
        Inflight.peak = Inflight.n
        gevent.sleep(1)


@events.test_stop.add_listener
def _stop(environment, **_):
    Ctx.running = False
    Ctx.gate.set()
    if Ctx.fh:
        Ctx.fh.close()
        Ctx.fh = None
    if not isinstance(environment.runner, WorkerRunner):
        gevent.sleep(1.2)   # let the last records land
        AGG.tail()
        AGG.finish(environment)


# --- synchronised burst: users report "ready", the master releases everyone at one wall-clock instant ---------------
def _on_ready(environment, msg, **_):
    AGG.ready += 1
    if AGG.ready >= AGG.meta.get("planned", 0) and not AGG.released:
        AGG.released = time.time() + 2.0
        environment.runner.send_message("lt_release", {"at": AGG.released})


def _on_release(environment, msg, **_):
    Ctx.release_at = msg.data["at"]
    Ctx.gate.set()


@events.init.add_listener
def _init(environment, **_):
    r = environment.runner
    if not isinstance(r, WorkerRunner):
        r.register_message("lt_ready", _on_ready)
    if not isinstance(r, MasterRunner):
        r.register_message("lt_release", _on_release)
        gevent.get_hub().threadpool.maxsize = 2   # frame building: enough, and leaves the CPU to the server under test
    if environment.web_ui:
        from dashboard.routes import mount
        mount(environment, AGG, S, RUNS)
        gevent.spawn(_monitor, environment)


# ------------------------------------------------------------------------------------------------------------------
# The virtual employee
# ------------------------------------------------------------------------------------------------------------------
_ip = iter(range(1, 1 << 24))


def _build_frames(case: dict, rng: random.Random) -> list[bytes]:
    cat = case["category"]
    if cat == "no_face":
        img = F.no_face_image(rng)
    elif cat == "two_faces":
        img = F.two_faces_image(F.load_raw(case["image"]), F.load_raw(case["image_b"]))
    else:
        img = F.load(case["image"])
    return F.session_frames(img, rng, n=6, variant=case.get("variant"))


class Employee(HttpUser):
    host = S.API_URL
    wait_time = constant(1)

    def on_start(self):
        self.xff = K.xff_for((Ctx.worker << 16) + next(_ip))
        self.client.headers["X-Forwarded-For"] = self.xff
        self.rng = random.Random(f"{Ctx.run_id}-{Ctx.worker}-{id(self)}")
        self.finished = False

    # -- one recognition, classified against ground truth -----------------------------------------------------------
    def prepare(self, case: dict) -> list[bytes]:
        """Build the camera frames for one scan on a helper thread. OpenCV releases the GIL, so the event loop keeps
        serving every other user's WebSocket (and the heartbeat to the master) while images are decoded and encoded;
        done inline, 125 users starting at once froze a worker for over 20 s and that time was booked as latency."""
        return gevent.get_hub().threadpool.apply(_build_frames, (case, self.rng))

    def recognise(self, step: str, case: dict, attempt: int = 1, frames: list[bytes] | None = None) -> dict:
        emp = case.get("emp")
        cat = case["category"]
        frames = frames or self.prepare(case)
        rec = {"type": "prediction", "t": time.time(), "run": Ctx.run_id, "stage": Ctx.stage, "scenario": Ctx.scenario, "step": step, "attempt": attempt,
               "category": cat, "expected_code": emp["code"] if emp else None, "expected_employee_id": emp["employee_id"] if emp else None,
               "label": emp["code"] if emp else case.get("label"), "probe": case.get("image"), "variant": case.get("variant"), "attendance": None}
        t0 = time.perf_counter()
        r = self.client.post(f"{S.API}/verify/sessions", name="POST /verify/sessions")
        rec["session_post_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        if r.status_code != 200:
            rec.update(outcome="error", error=f"session {r.status_code}", verdict="error", total_ms=rec["session_post_ms"])
            return rec
        v = K.verify(r.json(), frames, self.xff, inflight=Inflight, on_frame=self._frame,
                     max_frames=20 if cat in ("no_face", "two_faces") else None)
        token = v.pop("token")
        rtts, srv = v.pop("frame_rtt_ms"), v.pop("server_ms")
        rec.update(v)
        rec["predicted_code"] = rec.get("predicted_code") or CODE_BY_ID.get(rec.get("predicted_employee_id") or "")
        rec["frame_rtt_p50_ms"] = round(float(np.median(rtts)), 1) if rtts else None
        rec["frame_rtt_max_ms"] = round(max(rtts), 1) if rtts else None
        rec["server_frame_ms"] = round(float(np.mean(srv)), 1) if srv else None      # server-reported inference time per frame
        rec["server_total_ms"] = round(float(np.sum(srv)), 1) if srv else None
        rec["total_ms"] = round(rec["total_ms"] + rec["session_post_ms"], 1)
        rec["connect_ms"] = round(rec.get("connect_ms") or 0, 1)
        o, pid = rec["outcome"], rec.get("predicted_employee_id")
        gated = o == "incomplete" and rec.get("incomplete") == "frames" and not rec.get("error")
        if gated:
            # The server looked at every frame and refused to use any: a second face in the picture, or a face turned
            # too far for evidence to be collected. That is the application declining the input, not a system failure.
            issues = {k: n for k, n in rec["states"].items() if k not in ("collecting", "busy", "throttled")}
            rec["reason"] = "gate:" + (max(issues, key=issues.get) if issues else "not_frontal")
        if cat.startswith("genuine"):
            rec["verdict"] = ("correct" if pid == emp["employee_id"] else "incorrect") if o == "identified" else "rejected" if (o == "rejected" or gated) else "error"
        else:   # nobody should be identified: unknown person, empty frame, two equally close faces
            rec["verdict"] = "false_accept" if o == "identified" else "error" if (o == "error" or rec.get("error")) else "correct_reject"
        rec["_token"] = token
        bad = rec["verdict"] in ("incorrect", "false_accept", "error")
        events.request.fire(request_type="WS", name=f"recognition [{step}]", response_time=rec["total_ms"], response_length=0,
                            exception=RuntimeError(f"{rec['verdict']}: {rec.get('reason') or rec.get('error') or o}") if bad else None, context={})
        return rec

    @staticmethod
    def _frame(state: str, rtt: float) -> None:
        events.request.fire(request_type="WS", name="frame (busy: not analysed)" if state == "busy" else "frame (analysed)",
                            response_time=rtt, response_length=0, exception=None, context={})

    # -- attendance write with the verification token, checked against what must happen ------------------------------
    def attend(self, rec: dict, action: str, expect: int, step: str) -> None:
        token = rec.pop("_token", None)
        if not token or rec["verdict"] != "correct":
            return
        t0 = time.perf_counter()
        with self.client.post(f"{S.API}/attendance/events", json={"token": token, "action": action, "device_label": f"loadtest-{rec['expected_code']}"},
                              name=f"POST /attendance/events [{step}]", catch_response=True) as r:
            ms = round((time.perf_counter() - t0) * 1000, 1)
            body = {}
            try:
                body = r.json()
            except Exception:  # noqa: BLE001
                pass
            att = {"action": action, "status": r.status_code, "expected_status": expect, "ms": ms}
            if r.status_code == 201:
                att.update(event_id=body.get("id"), employee_code=body.get("employee_code"), occurred_at=body.get("occurred_at"))
            elif r.status_code == 409:
                d = body.get("detail")
                att["refusal"] = d.get("code") if isinstance(d, dict) else str(d)[:60]
            mapped = r.status_code != 201 or body.get("employee_code") == rec["expected_code"]
            att["ok"] = r.status_code == expect and mapped
            if att["ok"]:
                r.success()
            else:
                r.failure(f"expected {expect}, got {r.status_code}" + ("" if mapped else " (wrong employee)"))
            rec["attendance"] = att

    def step(self, step: str, case: dict, action: str | None, expect: int = 201, retries: int = 0, frames: list[bytes] | None = None) -> dict:
        rec: dict = {}
        for attempt in range(1, retries + 2):
            rec = self.recognise(step, case, attempt, frames if attempt == 1 else None)
            if action:
                self.attend(rec, action, expect, step)
            rec.pop("_token", None)
            _write(rec)
            if rec["verdict"] == "correct" or not Ctx.running:
                break
        return rec

    def _done(self, **extra) -> None:
        self.finished = True
        _write({"type": "flow_done", "t": time.time(), **extra})

    # -- scenarios ---------------------------------------------------------------------------------------------------
    @task
    def flow(self):
        if self.finished or not Ctx.running:
            gevent.sleep(1)
            return
        sc = Ctx.scenario
        if not Ctx.queue:
            self.finished = True
            return
        if sc in ("accuracy", "liveness"):
            self.step("SCAN", Ctx.queue.popleft(), None)
            _write({"type": "flow_done", "t": time.time()})
            return
        emp = Ctx.queue.popleft()
        probes = emp.get("load_probes") or emp["probes"]
        case = lambda i: {"category": "genuine", "emp": emp, "image": probes[i % len(probes)]}  # noqa: E731
        if sc == "attendance":
            r = self.step("LOGIN", case(0), "check_in", 201, retries=1)
            if (r.get("attendance") or {}).get("status") == 201:
                t_in = time.time()
                self.step("DUP_LOGIN", case(1), "check_in", 409)
                while Ctx.running and time.time() - t_in < S.CHECKOUT_AFTER_S:
                    gevent.sleep(0.5)
                if Ctx.running:
                    r2 = self.step("LOGOUT", case(2), "check_out", 201, retries=1)
                    if (r2.get("attendance") or {}).get("status") == 201:
                        self.step("DUP_LOGOUT", case(0), "check_out", 409)
            self._done(code=emp["code"])
        elif sc == "burst":
            ready = self.prepare(case(0))   # build the frames before the gate so the release measures the server, not this process
            self.environment.runner.send_message("lt_ready", {"w": Ctx.worker})
            Ctx.gate.wait()
            gevent.sleep(max(0.0, Ctx.release_at - time.time()))
            if Ctx.running:
                r = self.step("LOGIN", case(0), "check_in", 201, frames=ready)
                _write({"type": "burst", "t_release": Ctx.release_at, "t_first_frame": r.get("t_first_frame"), "code": emp["code"]})
            self._done(code=emp["code"])
        elif sc == "sustained":
            n, checked_in = 0, False
            while Ctx.running and time.time() - Ctx.started < Ctx.hold:
                if UNKNOWN and self.rng.random() < 0.1:
                    u = self.rng.choice(UNKNOWN)
                    self.step("SCAN_UNKNOWN", {"category": "unknown", "label": u["id"], "image": u["image"]}, None)
                else:
                    # The first check-in the server confirms must be stored; every later one must be refused. Under
                    # overload the first scans may get no answer at all, so "first" means first confirmed, not first sent.
                    r = self.step("SCAN", case(n), "check_in", 409 if checked_in else 201)
                    checked_in = checked_in or (r.get("attendance") or {}).get("status") == 201
                    n += 1
                gevent.sleep(self.rng.uniform(1, 3))
            self._done(code=emp["code"])


# ------------------------------------------------------------------------------------------------------------------
# Aggregation for the dashboard and the summary (master / single process only)
# ------------------------------------------------------------------------------------------------------------------
def _pct(xs, p):
    return round(float(np.percentile(xs, p)), 1) if len(xs) else None


def _mean(xs, nd=1):
    return round(float(np.mean(xs)), nd) if len(xs) else None


class Agg:
    def __init__(self):
        self.reset({})

    def reset(self, meta: dict) -> None:
        self.meta = meta
        self.offsets: dict[str, int] = {}
        self.verdicts: dict[str, int] = {}
        self.by_category: dict[str, dict[str, int]] = {}
        self.reasons: dict[str, int] = {}
        self.by_step: dict[str, dict] = {}
        self.attendance = {"created": 0, "refused_as_expected": 0, "unexpected": 0, "wrong_employee": 0}
        self.scores: list[float] = []          # match score of every genuine identification
        self.impostor_scores: list[float] = []  # best score offered by someone who is not enrolled
        self.total_ms: list[float] = []
        self.server_frame_ms: list[float] = []
        self.attend_ms: list[float] = []
        self.frames_needed: list[int] = []
        self.identify_ms: list[float] = []      # session request -> verdict, for recognitions that ended in a correct match
        self.busy = 0
        self.flows_done = 0
        self.predictions = 0
        self.events: deque = deque(maxlen=400)
        self.errors: deque = deque(maxlen=120)
        self.inflight: dict[int, int] = {}
        self.inflight_peak = 0
        self.burst: list[dict] = []
        self.ready = 0
        self.released = 0.0
        self.finished = False
        self.summary: dict | None = None
        if not hasattr(self, "timeline"):
            self.timeline: deque = deque(maxlen=3600)

    # -- read whatever the load generators appended since the last call ---------------------------------------------
    def tail(self) -> None:
        rid = self.meta.get("run_id")
        if not rid:
            return
        for f in sorted((RUNS / rid).glob("predictions_w*.jsonl")):
            off = self.offsets.get(f.name, 0)
            try:
                with open(f, "rb") as fh:
                    fh.seek(off)
                    chunk = fh.read()
            except FileNotFoundError:
                continue
            end = chunk.rfind(b"\n")
            if end < 0:
                continue
            self.offsets[f.name] = off + end + 1
            for line in chunk[:end].split(b"\n"):
                if line.strip():
                    try:
                        self.add(json.loads(line))
                    except Exception as e:  # noqa: BLE001
                        print("bad record:", e, file=sys.stderr)

    def add(self, r: dict) -> None:
        t = r.get("type")
        if t == "inflight":
            self.inflight[r["w"]] = r["n"]
            self.inflight_peak = max(self.inflight_peak, sum(self.inflight.values()))
            return
        if t == "flow_done":
            self.flows_done += 1
            return
        if t == "burst":
            self.burst.append(r)
            return
        if t != "prediction":
            return
        self.predictions += 1
        v, cat, step = r["verdict"], r["category"], r["step"]
        self.verdicts[v] = self.verdicts.get(v, 0) + 1
        c = self.by_category.setdefault(cat, {})
        c[v] = c.get(v, 0) + 1
        s = self.by_step.setdefault(step, {"n": 0, "correct": 0, "ms": []})
        s["n"] += 1
        s["correct"] += v in ("correct", "correct_reject")
        if r.get("total_ms") is not None:
            s["ms"].append(r["total_ms"])
            self.total_ms.append(r["total_ms"])
        if v in ("rejected", "error", "incorrect", "false_accept"):
            key = r.get("reason") or (r.get("error") or r.get("outcome") or "?").split(":")[0]
            self.reasons[f"{v}: {key}"] = self.reasons.get(f"{v}: {key}", 0) + 1
        if r.get("match_score") is not None:
            if v == "correct":
                self.scores.append(r["match_score"])
            elif not cat.startswith("genuine"):
                self.impostor_scores.append(r["match_score"])
        if r.get("server_frame_ms") is not None:
            self.server_frame_ms.append(r["server_frame_ms"])
        if v == "correct":
            self.frames_needed.append(r.get("frames_analysed") or 0)
            self.identify_ms.append(r.get("total_ms") or 0)
        self.busy += r.get("busy") or 0
        a = r.get("attendance")
        att_txt = ""
        if a:
            self.attend_ms.append(a["ms"])
            if a["ok"]:
                self.attendance["created" if a["status"] == 201 else "refused_as_expected"] += 1
            else:
                self.attendance["unexpected"] += 1
                if a["status"] == 201 and a.get("employee_code") != r["expected_code"]:
                    self.attendance["wrong_employee"] += 1
            att_txt = f"attendance {a['status']}" + (f" {a.get('refusal')}" if a.get("refusal") else "") + ("" if a["ok"] else " UNEXPECTED")
        label = {"correct": "Correct match", "incorrect": "INCORRECT MATCH", "rejected": "Rejected", "error": "Error",
                 "correct_reject": "Correctly refused", "false_accept": "FALSE ACCEPT"}[v]
        why = r.get("reason") or (r.get("error") if v == "error" else None)
        pred = f" -> {r.get('predicted_code')}" if v in ("incorrect", "false_accept") else ""
        line = {"ts": datetime.fromtimestamp(r["t"]).strftime("%H:%M:%S.%f")[:-3], "who": r.get("label") or "?", "step": step, "verdict": v,
                "text": f"{label}{pred}" + (f" ({why})" if why and v != "correct" else ""), "score": r.get("match_score"), "ms": round(r.get("total_ms") or 0), "att": att_txt}
        self.events.append(line)
        if v in ("incorrect", "false_accept", "error") or (a and not a["ok"]):
            self.errors.append(line)

    # -- numbers ---------------------------------------------------------------------------------------------------
    def metrics(self) -> dict:
        g: dict[str, int] = {}
        for cat, d in self.by_category.items():
            if cat.startswith("genuine"):
                for k, n in d.items():
                    g[k] = g.get(k, 0) + n
        decided = g.get("correct", 0) + g.get("incorrect", 0) + g.get("rejected", 0)
        neg: dict[str, int] = {}
        for cat in ("unknown", "no_face", "two_faces"):
            for k, n in self.by_category.get(cat, {}).items():
                neg[k] = neg.get(k, 0) + n
        neg_decided = neg.get("correct_reject", 0) + neg.get("false_accept", 0)
        unk = self.by_category.get("unknown", {})
        unk_decided = unk.get("correct_reject", 0) + unk.get("false_accept", 0)
        tp = g.get("correct", 0)
        fp = g.get("incorrect", 0) + neg.get("false_accept", 0)
        fn = g.get("rejected", 0) + g.get("incorrect", 0)
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        return {
            "genuine": g, "genuine_decided": decided, "negatives": neg, "negatives_decided": neg_decided,
            "correct_rate": tp / decided if decided else None,
            "incorrect_rate": g.get("incorrect", 0) / decided if decided else None,
            "frr": g.get("rejected", 0) / decided if decided else None,
            "far": neg.get("false_accept", 0) / neg_decided if neg_decided else None,
            "unknown_rejection_rate": unk.get("correct_reject", 0) / unk_decided if unk_decided else None,
            "precision": prec, "recall": rec, "f1": (2 * prec * rec / (prec + rec)) if prec and rec else None,
            "score_mean": _mean(self.scores, 4), "score_min": round(float(np.min(self.scores)), 4) if self.scores else None,
            "score_p05": round(float(np.percentile(self.scores, 5)), 4) if self.scores else None,
            "impostor_score_max": round(float(np.max(self.impostor_scores)), 4) if self.impostor_scores else None,
            "recognition_ms": {"p50": _pct(self.total_ms, 50), "p90": _pct(self.total_ms, 90), "p95": _pct(self.total_ms, 95), "p99": _pct(self.total_ms, 99),
                               "min": _pct(self.total_ms, 0), "max": _pct(self.total_ms, 100), "mean": _mean(self.total_ms)},
            "identify_ms": {"p50": _pct(self.identify_ms, 50), "p90": _pct(self.identify_ms, 90), "p95": _pct(self.identify_ms, 95), "p99": _pct(self.identify_ms, 99),
                            "max": _pct(self.identify_ms, 100), "mean": _mean(self.identify_ms)},
            "server_frame_ms": {"p50": _pct(self.server_frame_ms, 50), "p95": _pct(self.server_frame_ms, 95), "mean": _mean(self.server_frame_ms)},
            "attendance_write_ms": {"p50": _pct(self.attend_ms, 50), "p95": _pct(self.attend_ms, 95), "max": _pct(self.attend_ms, 100)},
            "frames_to_identify": {"p50": _pct(self.frames_needed, 50), "p95": _pct(self.frames_needed, 95)},
        }

    def snapshot(self, environment) -> dict:
        st = environment.stats.total
        hist = [0] * 12   # match-score histogram 0.40 .. 1.00 in steps of 0.05
        for sc in self.scores:
            hist[max(0, min(11, int((sc - 0.40) / 0.05)))] += 1
        return {
            "now": time.time(), "state": environment.runner.state, "meta": self.meta, "finished": self.finished,
            "users": environment.runner.user_count,
            "elapsed": (self.summary or {}).get("duration_s") if self.finished else round(time.time() - self.meta["started"], 1) if self.meta.get("started") else None,
            "locust": {"requests": st.num_requests, "failures": st.num_failures, "rps": round(st.current_rps, 1), "fail_per_s": round(st.current_fail_per_sec, 2),
                       "p50": st.get_current_response_time_percentile(0.5), "p95": st.get_current_response_time_percentile(0.95), "avg": round(st.avg_response_time, 1)},
            "predictions": self.predictions, "verdicts": self.verdicts, "by_category": self.by_category,
            "reasons": dict(sorted(self.reasons.items(), key=lambda kv: -kv[1])[:12]),
            "by_step": {k: {"n": v["n"], "correct": v["correct"], "p50": _pct(v["ms"], 50), "p95": _pct(v["ms"], 95)} for k, v in self.by_step.items()},
            "attendance": self.attendance, "metrics": self.metrics(), "score_hist": hist, "busy_frames": self.busy,
            "flows": {"done": self.flows_done, "planned": self.meta.get("planned", 0)},
            "inflight": {"now": sum(self.inflight.values()), "peak": self.inflight_peak},
            "timeline": list(self.timeline)[-600:], "events": list(self.events)[-250:], "errors": list(self.errors)[-60:],
            "suite": _read_json(SUITE),
        }

    def finish(self, environment) -> None:
        if not self.meta.get("run_id") or self.finished:
            return
        self.finished = True
        run_tl = [x for x in self.timeline if x["t"] >= self.meta["started"]]

        def col(k):
            return [x[k] for x in run_tl if x.get(k) is not None]

        stats = []
        for e in list(environment.stats.entries.values()) + [environment.stats.total]:
            stats.append({"type": e.method or "", "name": e.name, "requests": e.num_requests, "failures": e.num_failures, "avg": round(e.avg_response_time, 1),
                          "median": e.median_response_time, "p90": e.get_response_time_percentile(0.9), "p95": e.get_response_time_percentile(0.95),
                          "p99": e.get_response_time_percentile(0.99), "min": round(e.min_response_time or 0, 1), "max": round(e.max_response_time, 1), "rps": round(e.total_rps, 2)})
        burst = None
        if self.burst:
            ff = [(b["t_first_frame"] - b["t_release"]) * 1000 for b in self.burst if b.get("t_first_frame")]
            burst = {"users_released": len(self.burst), "t_release": self.burst[0]["t_release"],
                     "first_frame_after_release_ms": {"p50": _pct(ff, 50), "p95": _pct(ff, 95), "max": _pct(ff, 100)}}
        self.summary = {
            **self.meta, "ended": time.time(), "duration_s": round(time.time() - self.meta["started"], 1),
            "predictions": self.predictions, "verdicts": self.verdicts, "by_category": self.by_category, "reasons": self.reasons,
            "by_step": {k: {"n": v["n"], "correct": v["correct"], "p50": _pct(v["ms"], 50), "p95": _pct(v["ms"], 95), "max": _pct(v["ms"], 100)} for k, v in self.by_step.items()},
            "attendance": self.attendance, "metrics": self.metrics(), "busy_frames": self.busy, "flows_done": self.flows_done,
            "inflight_peak": self.inflight_peak, "burst": burst, "locust": stats,
            "system": {"cpu_avg": _mean(col("cpu")), "cpu_max": max(col("cpu"), default=None), "ram_avg": _mean(col("ram")), "ram_max": max(col("ram"), default=None),
                       "api_cpu_avg": _mean(col("api_cpu")), "api_cpu_max": max(col("api_cpu"), default=None),
                       "api_rss_mb_start": (col("api_rss") or [None])[0], "api_rss_mb_end": (col("api_rss") or [None])[-1], "api_rss_mb_max": max(col("api_rss"), default=None),
                       "generator_cpu_avg": _mean(col("gen_cpu")), "generator_cpu_max": max(col("gen_cpu"), default=None), "other_cpu_avg": _mean(col("other_cpu")),
                       "logical_cpus": psutil.cpu_count(), "samples": len(run_tl)},
        }
        d = RUNS / self.meta["run_id"]
        (d / "summary.json").write_text(json.dumps(self.summary, indent=1))
        with open(d / "system.jsonl", "w", encoding="utf-8") as fh:
            for x in run_tl:
                fh.write(json.dumps(x) + "\n")


AGG = Agg()


def _read_json(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None


def _find_processes(me: int) -> tuple[list[int], list[int]]:
    """(load-generator pids, test-API process tree). On Windows a virtualenv's python.exe is only a launcher: the
    interpreter doing the work is its child, so the API is measured as a tree."""
    gens = [p.pid for p in psutil.process_iter(["pid", "cmdline"]) if p.info["cmdline"] and any("locustfile.py" in c for c in p.info["cmdline"])] or [me]
    tree: list[int] = []
    try:
        api_pid = int((S.RESULTS / "api.pid").read_text())
        if psutil.pid_exists(api_pid):
            tree = [api_pid] + [c.pid for c in psutil.Process(api_pid).children(recursive=True)]
    except Exception:  # noqa: BLE001
        pass
    return gens, tree


def _monitor(environment) -> None:
    """Once a second: system load, the test API process, the load generators, and Locust's own live numbers."""
    ncpu = psutil.cpu_count() or 1
    procs: dict[int, psutil.Process] = {}
    psutil.cpu_percent(None)
    me = os.getpid()

    def cpu_of(pids: list[int]) -> float:
        total = 0.0
        for pid in pids:
            try:
                p = procs.get(pid)
                if p is None:
                    p = procs[pid] = psutil.Process(pid)
                    p.cpu_percent(None)
                total += p.cpu_percent(None)
            except psutil.Error:
                procs.pop(pid, None)
        return round(total / ncpu, 1)   # share of the whole machine, 0-100

    tick = 0
    gens: list[int] = [me]
    tree: list[int] = []
    pool = gevent.get_hub().threadpool
    while True:
        gevent.sleep(1)
        tick += 1
        try:
            if tick % 10 == 1:
                # Walking the Windows process table takes long enough to stall the master's event loop (and with it
                # the dashboard and the worker heartbeats), so do it rarely and on a helper thread.
                gens, tree = pool.apply(_find_processes, (me,))
            api_cpu = api_rss = None
            try:
                if tree:
                    api_cpu = cpu_of(tree)
                    api_rss = round(sum(procs[i].memory_info().rss for i in tree if i in procs) / 1e6)
            except Exception:  # noqa: BLE001
                pass
            cpu = psutil.cpu_percent(None)
            gen = cpu_of(gens)
            st = environment.stats.total
            running = environment.runner.state in ("spawning", "running")
            if running:
                AGG.tail()
            AGG.timeline.append({"t": round(time.time(), 1), "cpu": cpu, "ram": psutil.virtual_memory().percent, "api_cpu": api_cpu, "api_rss": api_rss, "gen_cpu": gen,
                                 "other_cpu": round(max(0.0, cpu - (api_cpu or 0) - gen), 1), "users": environment.runner.user_count,
                                 "inflight": sum(AGG.inflight.values()) if running else 0, "rps": round(st.current_rps, 1) if running else 0,
                                 "p95": st.get_current_response_time_percentile(0.95) if running else None, "fail": round(st.current_fail_per_sec, 2) if running else 0,
                                 "running": running})
        except Exception as e:  # noqa: BLE001 - monitoring must never stop the test
            print("monitor:", type(e).__name__, e, file=sys.stderr)
