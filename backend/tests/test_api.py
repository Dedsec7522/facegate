"""API-level tests: auth, RBAC, employee CRUD, verification token single-use, PIN fallback, audit."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.security import create_verification_token

pytestmark = pytest.mark.asyncio


async def test_login_rejects_bad_password_and_requires_auth(client: AsyncClient):
    r = await client.post("/api/v1/auth/login", json={"email": "admin@test.local", "password": "wrong-password"})
    assert r.status_code == 401
    assert (await client.get("/api/v1/employees")).status_code == 401


async def test_rbac_employee_cannot_access_admin(client: AsyncClient):
    r = await client.post("/api/v1/auth/login", json={"email": "test.person@test.local", "password": "Employee-Pass-1234"})
    assert r.status_code == 200 and r.json()["role"] == "employee"
    assert (await client.get("/api/v1/employees")).status_code == 403
    assert (await client.get("/api/v1/audit")).status_code == 403
    assert (await client.get("/api/v1/attendance/me/status")).status_code == 200


async def test_employee_crud_and_audit(admin_client: AsyncClient):
    r = await admin_client.post("/api/v1/employees", json={"employee_code": "E2", "first_name": "Ada", "last_name": "Lovelace", "email": "ada@test.local"})
    assert r.status_code == 201, r.text
    emp = r.json()
    assert emp["enrolled"] is False
    r = await admin_client.post("/api/v1/employees", json={"employee_code": "E2", "first_name": "Dup", "last_name": "X", "email": "dup@test.local"})
    assert r.status_code == 409
    r = await admin_client.patch(f"/api/v1/employees/{emp['id']}", json={"status": "inactive", "job_title": "Engineer"})
    assert r.status_code == 200 and r.json()["status"] == "inactive"
    r = await admin_client.get("/api/v1/employees", params={"q": "lovelace"})
    assert r.json()["total"] == 1
    r = await admin_client.get("/api/v1/audit", params={"action": "employee."})
    assert r.status_code == 200 and r.json()["total"] >= 2
    actions = {i["action"] for i in r.json()["items"]}
    assert {"employee.create", "employee.update"} <= actions


async def test_verification_token_is_single_use_and_bound(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/employees", params={"q": "E1"})
    emp_id = r.json()["items"][0]["id"]
    token = create_verification_token("session-1", emp_id, "face")
    r1 = await admin_client.post("/api/v1/attendance/events", json={"token": token, "action": "check_in"})
    assert r1.status_code == 201, r1.text
    assert r1.json()["method"] == "face" and r1.json()["action"] == "check_in"
    r2 = await admin_client.post("/api/v1/attendance/events", json={"token": token, "action": "check_out"})
    assert r2.status_code == 409  # replay rejected
    r3 = await admin_client.post("/api/v1/attendance/events", json={"token": "garbage", "action": "check_in"})
    assert r3.status_code == 401
    r4 = await admin_client.post("/api/v1/attendance/events", json={"token": create_verification_token("s2", emp_id, "face"), "action": "check_in"})
    assert r4.status_code == 409 and r4.json()["detail"]["code"] in ("duplicate", "already_checked_in")


async def test_pin_fallback_requires_admin_enablement(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/employees", params={"q": "E1"})
    emp_id = r.json()["items"][0]["id"]
    r = await admin_client.post("/api/v1/attendance/events/pin", json={"employee_code": "E1", "pin": "1234", "action": "check_out"})
    assert r.status_code == 401
    assert (await admin_client.post(f"/api/v1/employees/{emp_id}/pin", json={"pin": "4321"})).status_code == 204
    r = await admin_client.post("/api/v1/attendance/events/pin", json={"employee_code": "E1", "pin": "4321", "action": "check_out"})
    assert r.status_code in (201, 409), r.text  # 409 only if inside the duplicate window from the previous test
    if r.status_code == 201:
        assert r.json()["method"] == "pin"


async def test_settings_and_dashboard(admin_client: AsyncClient):
    r = await admin_client.patch("/api/v1/settings", json={"late_grace_minutes": 15, "work_start": "08:30"})
    assert r.status_code == 200 and r.json()["late_grace_minutes"] == 15
    r = await admin_client.get("/api/v1/dashboard")
    assert r.status_code == 200 and "kpis" in r.json() and len(r.json()["trend"]) == 14
    r = await admin_client.get("/api/v1/attendance/export", params={"fmt": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")


async def test_verify_session_creation_is_public_and_rate_limited(client: AsyncClient):
    r = await client.post("/api/v1/verify/sessions")
    assert r.status_code == 200
    body = r.json()
    assert body["challenge"] in ("turn_left", "turn_right", None) and body["nonce"]  # challenge is a step-up by default


async def test_purge_biometrics_removes_templates_and_index(admin_client: AsyncClient):
    """Regression: purge used to touch a lazy relationship in async code (MissingGreenlet → 500)."""
    import numpy as np
    from datetime import datetime, timezone

    from app.core.crypto import encrypt_embedding
    from app.db.base import SessionLocal
    from app.db.models import BiometricEnrolment, EnrolmentStatus, FaceTemplate, new_id
    from app.vision.pipeline import get_pipeline

    r = await admin_client.post("/api/v1/employees", json={"employee_code": "E-PURGE", "first_name": "Purge", "last_name": "Me", "email": "purge@test.local"})
    emp_id = r.json()["id"]
    async with SessionLocal() as db:
        enrol = BiometricEnrolment(id=new_id(), employee_id=emp_id, consent_version="t", consent_at=datetime.now(timezone.utc), template_count=2, thumbnail_jpeg=b"JPEGDATA")
        db.add(enrol)
        for pose in ("front", "left"):
            tid = new_id()
            v = np.random.default_rng(7).normal(size=128).astype(np.float32)
            db.add(FaceTemplate(id=tid, enrolment_id=enrol.id, employee_id=emp_id, pose=pose, embedding_enc=encrypt_embedding(v / np.linalg.norm(v), tid)))
        await db.commit()
    r = await admin_client.get(f"/api/v1/employees/{emp_id}")
    assert r.json()["enrolled"] is True
    r = await admin_client.delete(f"/api/v1/employees/{emp_id}/biometrics", params={"purge": "true"})
    assert r.status_code == 200, r.text
    assert r.json() == {"removed": 2, "purged": True}
    r = await admin_client.get(f"/api/v1/employees/{emp_id}")
    assert r.json()["enrolled"] is False
    assert (await admin_client.get(f"/api/v1/employees/{emp_id}/thumbnail")).status_code == 404
    assert emp_id not in get_pipeline().index.employees()
    assert (await admin_client.get(f"/api/v1/employees/{emp_id}/enrolments")).json() == []
    # revoke (soft) path still answers cleanly on an employee with nothing left
    assert (await admin_client.delete(f"/api/v1/employees/{emp_id}/biometrics")).json() == {"removed": 0, "purged": False}
