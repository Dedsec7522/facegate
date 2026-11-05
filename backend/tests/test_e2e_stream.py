"""End-to-end: enrol a synthetic face through the real service layer, then drive the kiosk WebSocket
with JPEG frames and assert identification, unknown rejection, replay protection and the recorded event.

The head-turn challenge needs a moving head, which a static image cannot provide, so these tests run
with `require_challenge=false` (an admin-configurable setting); the challenge logic itself is covered
by `test_challenge_state_machine` using synthetic yaw sequences."""
from __future__ import annotations

import glob
import json
import time

import cv2
import numpy as np
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import AttendanceEvent, Employee, VerificationAttempt
from app.services.enrolment import EnrolmentError, commit_enrolment
from app.services.verification import ENROL_POSES, Session, SessionManager, manager
from app.vision.pipeline import get_pipeline
from tests.conftest import DATA

FILES = sorted(glob.glob(str(DATA / "synth_face_*.jpg")))
pytestmark = pytest.mark.skipif(len(FILES) < 2, reason="synthetic face images not present")


def _frame(path: str, jitter: int = 0) -> tuple[np.ndarray, bytes]:
    img = cv2.resize(cv2.imread(path), (640, 640))
    img = cv2.convertScaleAbs(img, alpha=1.0, beta=jitter)
    # A live face is never perfectly still: nudge the frame a few pixels so the frozen-stream check sees motion.
    img = np.roll(img, shift=(jitter * 2, jitter * 3), axis=(0, 1))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return img, buf.tobytes()


async def _enrol(db, emp: Employee, path: str) -> None:
    pipe = get_pipeline()
    s = Session(id="enrol-test", purpose="enrolment", nonce="n", created=time.monotonic(), ip=None, user_agent=None, challenge=None,
                employee_id=emp.id, consent_version="test")
    img, _ = _frame(path)
    for pose in ENROL_POSES:
        a = pipe.analyse(img)
        assert a.state == "ok"
        s.poses[pose] = (a.embedding, a.quality.score, a.aligned)
        s.live_probs.append(a.live_prob)
    s.live_probs += [0.99] * settings.pad_min_frames  # synthetic stills score high on the passive PAD already; pad to min frames
    await commit_enrolment(db, s, employee=emp, created_by=None)


async def test_enrol_identify_reject_and_record(admin_client: AsyncClient):
    async with SessionLocal() as db:
        emp = (await db.execute(select(Employee).where(Employee.employee_code == "E1"))).scalar_one()
        emp_id = emp.id
        await _enrol(db, emp, FILES[0])
        await db.commit()
        # Duplicate-identity guard: enrolling the same face for a different employee must fail.
        other = Employee(employee_code="E-DUP", first_name="Dup", last_name="Face", email="dup@test.local")
        db.add(other)
        await db.flush()
        with pytest.raises(EnrolmentError) as e:
            await _enrol(db, other, FILES[0])
        assert e.value.code == "duplicate_identity"
        await db.rollback()

    assert get_pipeline().index.size == len(ENROL_POSES)
    r = await admin_client.patch("/api/v1/settings", json={"require_challenge": False, "duplicate_scan_seconds": 0})
    assert r.status_code == 200

    from app.main import app
    from starlette.testclient import TestClient

    with TestClient(app) as tc:
        # ---- known face → identified, token issued, event recorded, replay rejected
        s = tc.post("/api/v1/verify/sessions").json()
        assert s["challenge"] is None
        with tc.websocket_connect(f"/api/v1/verify/stream/{s['session_id']}") as ws:
            ws.send_text(json.dumps({"nonce": s["nonce"]}))
            final = None
            for i in range(12):
                ws.send_bytes(_frame(FILES[0], jitter=(i % 3) - 1)[1])
                msg = ws.receive_json()
                if msg["state"] in ("identified", "rejected"):
                    final = msg
                    break
                time.sleep(1 / settings.max_stream_fps)
        assert final and final["state"] == "identified", final
        assert final["employee"]["code"] == "E1" and final["token"] and final["match_score"] > 0.8
        action = final["next"]["next"]  # the engine tells the kiosk which action is valid now
        ev = tc.post("/api/v1/attendance/events", json={"token": final["token"], "action": action})
        assert ev.status_code == 201 and ev.json()["method"] == "face", ev.text
        assert tc.post("/api/v1/attendance/events", json={"token": final["token"], "action": action}).status_code == 409  # replay

        # ---- wrong nonce is refused
        s2 = tc.post("/api/v1/verify/sessions").json()
        with tc.websocket_connect(f"/api/v1/verify/stream/{s2['session_id']}") as ws:
            ws.send_text(json.dumps({"nonce": "bogus"}))
            assert ws.receive_json()["state"] == "error"

        # ---- unknown face → rejected:unknown, no token
        s3 = tc.post("/api/v1/verify/sessions").json()
        with tc.websocket_connect(f"/api/v1/verify/stream/{s3['session_id']}") as ws:
            ws.send_text(json.dumps({"nonce": s3["nonce"]}))
            final = None
            for i in range(12):
                ws.send_bytes(_frame(FILES[1], jitter=(i % 3) - 1)[1])
                msg = ws.receive_json()
                if msg["state"] in ("identified", "rejected"):
                    final = msg
                    break
                time.sleep(1 / settings.max_stream_fps)
        assert final and final["state"] == "rejected" and final["reason"] == "unknown" and "token" not in final

        # ---- no face → guidance, never a decision
        s4 = tc.post("/api/v1/verify/sessions").json()
        with tc.websocket_connect(f"/api/v1/verify/stream/{s4['session_id']}") as ws:
            ws.send_text(json.dumps({"nonce": s4["nonce"]}))
            blank = cv2.imencode(".jpg", np.full((480, 640, 3), 120, np.uint8))[1].tobytes()
            ws.send_bytes(blank)
            msg = ws.receive_json()
            assert msg["state"] == "no_face" and "Position your face" in msg["guidance"]

    async with SessionLocal() as db:
        attempts = (await db.execute(select(VerificationAttempt))).scalars().all()
        outcomes = {a.outcome.value for a in attempts}
        assert {"identified", "unknown"} <= outcomes
        events = (await db.execute(select(AttendanceEvent).where(AttendanceEvent.employee_id == emp_id))).scalars().all()
        assert any(e.method.value == "face" and e.verification_attempt_id for e in events)


def test_challenge_state_machine():
    m = SessionManager()
    s = Session(id="c", purpose="attendance", nonce="n", created=time.monotonic(), ip=None, user_agent=None, challenge="turn_left")
    for yaw in [0, 2, 5, 12, 20, 26, 22, 10, 4, 1]:  # turn left (positive yaw) then back to centre
        m._advance_challenge(s, yaw)
    assert s.challenge_state == "passed"

    s2 = Session(id="c2", purpose="attendance", nonce="n", created=time.monotonic(), ip=None, user_agent=None, challenge="turn_right")
    for yaw in [0, 1, 3, 2, 1, 0, 2]:  # never turns
        m._advance_challenge(s2, yaw)
    assert s2.challenge_state == "pending"

    s3 = Session(id="c3", purpose="attendance", nonce="n", created=time.monotonic(), ip=None, user_agent=None, challenge="turn_right")
    for yaw in [0, 30, 32, 35, 33, 31, 34, 32]:  # sustained wrong direction
        s3.yaw_history.append(yaw)
        m._advance_challenge(s3, yaw)
    assert s3.challenge_state == "failed"
