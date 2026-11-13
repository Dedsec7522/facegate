"""The kiosk's face check-in protocol, exactly as the browser speaks it, with every measurement recorded.

  POST /api/v1/verify/sessions                      -> {session_id, nonce, ...}
  WS   /api/v1/verify/stream/{session_id}           -> send {"nonce"}; then one JPEG per message, one JSON reply per frame
       reply states: collecting | quality | no_face | multiple_faces | busy | throttled | identified | rejected | error
  POST /api/v1/attendance/events {token, action}    -> 201 with the stored event, or 409 {code, message}

Pacing copies frontend/src/components/camera/useVerificationStream.ts: a 10 fps timer that sends a frame on each tick
unless the previous frame is still unanswered. There is no extra back-off after a "busy" reply, because the real page
has none; a busy server therefore keeps receiving frames from every waiting kiosk, as it would in production.

`verify()` returns a plain dict (the "prediction record"). Under Locust the sockets are gevent-patched and cooperative.
"""
from __future__ import annotations

import json
import math
import time

import websocket

from test_config import settings as S

TERMINAL = ("identified", "rejected")


def ws_url(session_id: str, kind: str = "stream") -> str:
    return S.API_URL.replace("http", "ws", 1) + f"{S.API}/verify/{kind}/{session_id}"


def verify(session: dict, frames: list[bytes], xff: str, *, inflight=None, on_frame=None, max_frames: int | None = None, fps: float | None = None) -> dict:
    """Stream `frames` (cycled) for an already created verification session until the server reaches a verdict."""
    period = 1.0 / (fps or S.FPS)
    limit = max_frames or S.MAX_FRAMES
    rec: dict = {"session_id": session["session_id"], "liveness_policy": session.get("liveness_policy"), "outcome": "error", "reason": None,
                 "predicted_employee_id": None, "predicted_code": None, "match_score": None, "second_score": None, "liveness_score": None,
                 "token": None, "next": None, "frames_analysed": 0, "busy": 0, "throttled": 0, "frame_rtt_ms": [], "server_ms": [],
                 "states": {}, "error": None, "t_first_frame": None}
    t0 = time.perf_counter()
    try:
        ws = websocket.create_connection(ws_url(session["session_id"]), timeout=45, header=[f"X-Forwarded-For: {xff}"])
    except Exception as e:  # noqa: BLE001
        ms = (time.perf_counter() - t0) * 1000
        rec.update(error=f"connect: {type(e).__name__}: {e}"[:200], connect_ms=ms, total_ms=ms)
        return rec
    rec["connect_ms"] = (time.perf_counter() - t0) * 1000
    if inflight is not None:
        inflight.enter()
    try:
        ws.send(json.dumps({"nonce": session["nonce"]}))
        sent = 0
        t_stream = time.perf_counter()
        while True:
            if sent >= limit or time.perf_counter() - t0 > S.SESSION_DEADLINE_S:
                # "frames": the server analysed every frame and never accepted one as evidence (its quality gate kept
                # refusing); "deadline": the client gave up waiting, which under load means the server was too slow.
                rec["outcome"] = "incomplete"
                rec["incomplete"] = "frames" if sent >= limit else "deadline"
                break
            ts = time.perf_counter()
            if rec["t_first_frame"] is None:
                rec["t_first_frame"] = time.time()
            ws.send_binary(frames[sent % len(frames)])
            msg = json.loads(ws.recv())
            rtt = (time.perf_counter() - ts) * 1000
            state = msg.get("state")
            rec["states"][state] = rec["states"].get(state, 0) + 1
            if state == "error":
                rec["error"] = str(msg.get("message", "error"))[:200]
                break
            if state in ("busy", "throttled"):   # not analysed: the server shed load, or its fps cap applied
                rec[state] += 1
                if on_frame and state == "busy":
                    on_frame("busy", rtt)
            else:
                sent += 1
                rec["frames_analysed"] = sent
                rec["frame_rtt_ms"].append(round(rtt, 1))
                tm = msg.get("timings_ms")
                if tm:
                    rec["server_ms"].append(sum(tm.values()))
                if on_frame:
                    on_frame("analysed", rtt)
                if state in TERMINAL:
                    emp = msg.get("employee") or {}
                    rec.update(outcome=state, reason=msg.get("reason"), predicted_employee_id=msg.get("employee_id"), predicted_code=emp.get("code"),
                               match_score=msg.get("match_score"), second_score=msg.get("second_score"), liveness_score=msg.get("liveness_score"),
                               token=msg.get("token"), next=(msg.get("next") or {}).get("next"), attempt_id=msg.get("attempt_id"))
                    break
            # wait for the next tick of the 10 fps timer, like setInterval in the browser
            elapsed = time.perf_counter() - t_stream
            time.sleep(max(0.0, math.ceil(elapsed / period + 1e-9) * period - elapsed))
    except Exception as e:  # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"[:200]
    finally:
        if inflight is not None:
            inflight.leave()
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass
    rec["total_ms"] = (time.perf_counter() - t0) * 1000
    return rec


def xff_for(n: int) -> str:
    """A distinct private source address per simulated device, so per-IP limits behave as they would for real kiosks."""
    return f"10.{(n >> 16) & 255}.{(n >> 8) & 255}.{(n & 255) or 1}"
