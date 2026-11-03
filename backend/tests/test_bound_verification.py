"""Portal 1:1 verification: a session bound to an account only ever identifies that account's employee."""
from __future__ import annotations

import time

import numpy as np
import pytest
from httpx import AsyncClient

from app.vision.matcher import TemplateIndex
from app.vision.pipeline import get_pipeline
from app.services.verification import Session, SessionManager

pytestmark = pytest.mark.asyncio


def _unit(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=128).astype(np.float32)
    return v / np.linalg.norm(v)


def _session(bound: str | None) -> Session:
    s = Session(id="b", purpose="attendance", nonce="n", created=time.monotonic(), ip=None, user_agent=None, challenge=None, bound_employee_id=bound)
    s.accept_threshold = 0.42
    return s


def test_bound_session_never_identifies_someone_else():
    pipe = get_pipeline()
    saved = pipe.index
    try:
        idx = TemplateIndex()
        alice, bob = _unit(1), _unit(2)
        idx.load([("alice", alice), ("bob", bob)])
        pipe.index = idx
        m = SessionManager()

        # Bob's face presented in Alice's portal → rejected as mismatch, never "identified as Bob".
        s = _session("alice")
        s.embeddings = [bob, bob, bob]
        r = m._identify(s, 0.9)
        assert r["state"] == "rejected" and r["reason"] == "mismatch" and "employee_id" not in r

        # Alice's own face in her portal → identified as Alice only.
        s = _session("alice")
        s.embeddings = [alice, alice, alice]
        r = m._identify(s, 0.9)
        assert r["state"] == "identified" and r["employee_id"] == "alice"

        # Account with no enrolment → explicit not_enrolled, no guessing.
        s = _session("carol")
        s.embeddings = [alice, alice, alice]
        r = m._identify(s, 0.9)
        assert r["state"] == "rejected" and r["reason"] == "not_enrolled"

        # Unbound kiosk session still does 1:N identification.
        s = _session(None)
        s.embeddings = [bob, bob, bob]
        assert m._identify(s, 0.9)["employee_id"] == "bob"
    finally:
        pipe.index = saved


async def test_bound_session_endpoint_requires_linked_account(client: AsyncClient, admin_client: AsyncClient):
    assert (await client.post("/api/v1/verify/sessions/me")).status_code in (401, 404)
    # the seeded admin has no employee profile
    assert (await admin_client.post("/api/v1/verify/sessions/me")).status_code == 404
    r = await admin_client.post("/api/v1/auth/login", json={"identifier": "test.person@test.local", "password": "Employee-Pass-1234"})
    assert r.status_code == 200
    r = await admin_client.post("/api/v1/verify/sessions/me")
    assert r.status_code == 200 and r.json()["bound"] is True and r.json()["ws_token"] and r.json()["employee"]["code"] == "E1"
    assert (await admin_client.get("/api/v1/attendance/me/status")).json()["employee"]["enrolled"] in (True, False)
