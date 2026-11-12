"""Locust load test for FaceGate: people browsing the portal and console, plus kiosk face check-ins over WebSocket.

Three kinds of simulated user, each with its own source address (X-Forwarded-For), as if each were on its own device:

  PortalUser  employee signs in (Argon2id) and opens their dashboard: status, calendar, insights, today's events
  AdminUser   HR/admin signs in and refreshes the live console: today, feed, employees, attendance days
  KioskUser   a person checks in at a kiosk: create a session, stream JPEG face frames at ~10 fps over
              /verify/stream/{id} until the server answers identified / rejected (full detect, quality, PAD, embed, match)

Accounts come from GET /auth/test-accounts (development only) and sign in with FACEGATE_PASSWORD (seed default
Welcome123), so run it against a development API seeded with `tools/seed.py --demo --employee-logins`. Accounts are
shared when there are more users than accounts. Kiosk frames are tests/data/synth_face_*.jpg with brightness jitter;
faces that are not enrolled end as rejected:unknown, which still runs the whole pipeline.

Needs: pip install locust websocket-client opencv-python-headless   (not part of the API's requirements)

    # web UI on http://localhost:8089
    locust -f benchmarks/locustfile.py --host http://127.0.0.1:8000
    # headless, 400 users, 20 new users/s, 3 minutes, HTML report
    locust -f benchmarks/locustfile.py --host http://127.0.0.1:8000 --headless -u 400 -r 20 -t 3m --html report.html
    # Windows has no --processes (fork): start one master and N workers instead
    locust -f benchmarks/locustfile.py --master --headless --expect-workers 4 -u 400 -r 20 -t 3m --host http://127.0.0.1:8000
    locust -f benchmarks/locustfile.py --worker --host http://127.0.0.1:8000     # x4, in separate shells

Per-IP limits (login 60/min, verify sessions 120/min) apply per X-Forwarded-For address, so each simulated device
has its own budget. Uvicorn honours that header only from a trusted proxy address (default 127.0.0.1), so run the
generator on the API's own machine, or start the API with FORWARDED_ALLOW_IPS=<generator ip>. Behind the Docker nginx
the header is overwritten with the real address and nginx's own limits apply: test the API directly (port 8000). KIOSK_WEIGHT / PORTAL_WEIGHT / ADMIN_WEIGHT change the mix.
"""
from __future__ import annotations

import itertools
import json
import os
import random
import threading
import time
from datetime import date
from pathlib import Path

import cv2
import requests
import websocket  # websocket-client; gevent monkey-patches its socket
from locust import HttpUser, between, events, task

API = "/api/v1"
PASSWORD = os.environ.get("FACEGATE_PASSWORD", "Welcome123")
DATA = Path(__file__).resolve().parents[1] / "tests" / "data"
MAX_FRAMES = int(os.environ.get("KIOSK_MAX_FRAMES", "40"))  # ~4 s of camera before giving up on a session
FPS = 10.0

_cycle: dict[str, itertools.cycle] = {}
_lock = threading.Lock()
_faces: list[list[bytes]] = []  # one list of jittered frames per face image
_ip_seq = itertools.count(random.randint(0, 1 << 22))  # workers are separate processes: random base per process


def _next_ip() -> str:
    n = next(_ip_seq)
    return f"10.{(n >> 16) & 255}.{(n >> 8) & 255}.{(n & 255) or 1}"


def _load_faces() -> list[list[bytes]]:
    faces = []
    for f in sorted(DATA.glob("synth_face_*.jpg")):
        img = cv2.resize(cv2.imread(str(f)), (640, 480))
        out = []
        for i in range(10):
            v = cv2.convertScaleAbs(img, alpha=1.0, beta=(i % 5) - 2)  # frames are never byte-identical
            ok, buf = cv2.imencode(".jpg", v, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                out.append(buf.tobytes())
        faces.append(out)
    return faces


@events.init.add_listener
def _init(environment, **_):
    _faces.extend(_load_faces())


def _load_accounts(host: str) -> None:
    accounts: dict[str, list[str]] = {"employee": [], "staff": []}
    try:
        for r in requests.get(f"{host}{API}/auth/test-accounts", timeout=10).json():
            accounts["employee" if r["role"] == "employee" else "staff"].append(r["username"])
    except Exception:  # noqa: BLE001 - fall back to env / admin below
        pass
    accounts["employee"] = accounts["employee"] or [u for u in os.environ.get("EMPLOYEE_USERS", "").split(",") if u]
    accounts["staff"] = accounts["staff"] or ["admin"]
    for k, v in accounts.items():
        _cycle[k] = itertools.cycle(v)


def _pick(kind: str, host: str) -> str:
    with _lock:
        if not _cycle:
            _load_accounts(host)
        return next(_cycle[kind])


class _Signed(HttpUser):
    abstract = True
    kind = "employee"

    def on_start(self):
        self.client.headers["X-Forwarded-For"] = _next_ip()
        self.username = _pick(self.kind, self.host)
        with self.client.post(f"{API}/auth/login", json={"identifier": self.username, "password": PASSWORD},
                              name="POST /auth/login", catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"{r.status_code} {r.text[:120]}")


class PortalUser(_Signed):
    weight = int(os.environ.get("PORTAL_WEIGHT", "6"))
    wait_time = between(2, 6)
    kind = "employee"

    @task(3)
    def dashboard(self):
        self.client.get(f"{API}/auth/me", name="GET /auth/me")
        self.client.get(f"{API}/attendance/me/status", name="GET /attendance/me/status")

    @task(2)
    def calendar(self):
        self.client.get(f"{API}/attendance/me/days?page_size=31", name="GET /attendance/me/days")

    @task(2)
    def insights(self):
        self.client.get(f"{API}/attendance/me/insights?days=30", name="GET /attendance/me/insights")

    @task(1)
    def day_events(self):
        self.client.get(f"{API}/attendance/me/events?attendance_date={date.today().isoformat()}", name="GET /attendance/me/events")


class AdminUser(_Signed):
    weight = int(os.environ.get("ADMIN_WEIGHT", "1"))
    wait_time = between(3, 8)
    kind = "staff"

    @task(3)
    def live(self):
        self.client.get(f"{API}/attendance/today", name="GET /attendance/today")
        self.client.get(f"{API}/attendance/feed", name="GET /attendance/feed")

    @task(1)
    def employees(self):
        self.client.get(f"{API}/employees?page_size=50", name="GET /employees")

    @task(1)
    def days(self):
        self.client.get(f"{API}/attendance/days?page_size=50", name="GET /attendance/days")


class KioskUser(HttpUser):
    """One person at a kiosk: a full face check-in, then the next person after a short gap."""
    weight = int(os.environ.get("KIOSK_WEIGHT", "3"))
    wait_time = between(3, 10)

    def on_start(self):
        self.client.headers["X-Forwarded-For"] = _next_ip()

    def _report(self, name: str, ms: float, length: int = 0, exc: Exception | None = None):
        self.environment.events.request.fire(request_type="WS", name=name, response_time=ms, response_length=length,
                                             exception=exc, context={})

    @task
    def check_in(self):
        r = self.client.post(f"{API}/verify/sessions", name="POST /verify/sessions")
        if r.status_code != 200 or not _faces:
            return
        s = r.json()
        ws_url = self.host.replace("http", "ws", 1) + f"{API}/verify/stream/{s['session_id']}"
        t0 = time.perf_counter()
        outcome, exc = "incomplete", None
        try:
            ws = websocket.create_connection(ws_url, timeout=60, header=[f"X-Forwarded-For: {self.client.headers['X-Forwarded-For']}"])
        except Exception as e:  # noqa: BLE001
            self._report("WS connect", (time.perf_counter() - t0) * 1000, exc=e)
            return
        try:
            ws.send(json.dumps({"nonce": s["nonce"]}))
            frames = random.choice(_faces)  # one person per session: mixing faces is (rightly) rejected as inconsistent
            sent = 0
            while sent < MAX_FRAMES:
                frame = frames[sent % len(frames)]
                ts = time.perf_counter()
                ws.send_binary(frame)
                msg = json.loads(ws.recv())
                rtt = (time.perf_counter() - ts) * 1000
                state = msg.get("state")
                if state == "error":
                    raise RuntimeError(msg.get("message", "error"))
                if state in ("busy", "throttled"):  # load shed / over the fps cap: back off, the frame was not analysed
                    self._report(f"WS frame ({state})", rtt)
                    time.sleep(0.3)
                    continue
                self._report("WS frame (analysed)", rtt, len(frame))
                sent += 1
                if state in ("identified", "rejected"):
                    outcome = f"{state}:{msg.get('reason') or ''}".rstrip(":")
                    break
                time.sleep(max(0.0, 1 / FPS - rtt / 1000))
        except Exception as e:  # noqa: BLE001
            exc = e
        finally:
            ws.close()
        self._report(f"WS check-in -> {'error' if exc else outcome}", (time.perf_counter() - t0) * 1000, exc=exc)
