"""Kiosk verification: session creation + WebSocket frame stream. Enrolment capture stream (admin-only)."""
from __future__ import annotations

import json
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_staff
from app.core.rate_limit import client_ip, limit, verify_session_limiter
from app.core.security import create_access_token, create_verification_token, decode_token
from app.db.base import SessionLocal, get_db
from app.db.models import AttendanceDay, Employee, EmployeeStatus, Role, UserAccount, VerificationAttempt, VerificationOutcome
from app.services.attendance import next_expected_action
from app.services.enrolment import EnrolmentError, add_adaptive_template, commit_enrolment
from app.services.org_settings import get_org_settings
from app.services.verification import manager
from app.vision.pipeline import get_pipeline
from app.services.audit import audit

router = APIRouter(prefix="/verify", tags=["verify"])


@router.post("/sessions", dependencies=[Depends(limit(verify_session_limiter))])
async def create_session(request: Request, db: AsyncSession = Depends(get_db)):
    org = await get_org_settings(db)
    s = await manager.create("attendance", ip=client_ip(request), user_agent=(request.headers.get("user-agent") or "")[:255],
                             require_challenge=org.require_challenge, pad_threshold=org.pad_live_threshold, accept_threshold=org.match_accept_threshold,
                             liveness_policy=org.kiosk_liveness)
    return manager.public(s)


@router.post("/sessions/me")
async def create_bound_session(request: Request, db: AsyncSession = Depends(get_db), user: UserAccount = Depends(get_current_user)):
    """Portal: a verification session bound to the signed-in employee (1:1). The face shown must match
    THIS account's enrolment; the resulting token can only record attendance for this employee."""
    if not user.employee_id:
        raise HTTPException(404, "No employee profile is linked to this account")
    emp = await db.get(Employee, user.employee_id)
    if not emp or emp.status != EmployeeStatus.active:
        raise HTTPException(404, "Active employee not found")
    org = await get_org_settings(db)
    s = await manager.create("attendance", ip=client_ip(request), user_agent=(request.headers.get("user-agent") or "")[:255],
                             require_challenge=org.require_challenge, pad_threshold=org.pad_live_threshold, accept_threshold=org.match_accept_threshold,
                             bound_employee_id=emp.id, liveness_policy=org.portal_liveness)
    return {**manager.public(s), "ws_token": create_access_token(user.id, user.role.value, True), "employee": {"id": emp.id, "name": emp.full_name, "code": emp.employee_code}}


@router.post("/enrolment-sessions")
async def create_enrolment_session(request: Request, employee_id: str, consent: bool = False, db: AsyncSession = Depends(get_db), user: UserAccount = Depends(require_staff)):
    if not consent:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Biometric consent must be confirmed before enrolment")
    emp = await db.get(Employee, employee_id)
    if not emp or emp.status != EmployeeStatus.active:
        raise HTTPException(404, "Active employee not found")
    org = await get_org_settings(db)
    s = await manager.create("enrolment", ip=client_ip(request), user_agent=(request.headers.get("user-agent") or "")[:255], require_challenge=False,
                             pad_threshold=org.pad_live_threshold, employee_id=emp.id, consent_version=org.consent_version)
    # Bind the admin's identity to the socket via a short-lived token (WS cannot rely on SameSite cookies in every browser).
    return {**manager.public(s), "ws_token": create_access_token(user.id, user.role.value, True)}


async def _record_attempt(result: dict, s, purpose: str) -> str | None:
    outcome_map = {"identified": VerificationOutcome.identified, "unknown": VerificationOutcome.unknown, "ambiguous": VerificationOutcome.ambiguous,
                   "spoof": VerificationOutcome.spoof, "challenge_failed": VerificationOutcome.challenge_failed, "timeout": VerificationOutcome.timeout,
                   "inconsistent": VerificationOutcome.quality, "no_face": VerificationOutcome.no_face, "multiple_faces": VerificationOutcome.multiple_faces}
    key = "identified" if result.get("state") == "identified" else result.get("reason", "quality")
    async with SessionLocal() as db:
        att = VerificationAttempt(
            session_id=s.id, purpose=purpose, outcome=outcome_map.get(key, VerificationOutcome.quality), employee_id=result.get("employee_id"),
            match_score=result.get("match_score"), second_score=result.get("second_score"), liveness_score=result.get("liveness_score"),
            challenge=s.challenge, frames=s.frames, duration_ms=int(s.age * 1000), reason=result.get("reason"), ip=s.ip, user_agent=s.user_agent,
        )
        db.add(att)
        await db.commit()
        return att.id


OTHERS_CACHE_SECONDS = 5.0


async def _enrich_others(s, resp: dict) -> None:
    """Label the bystanders the pipeline identified with their name and whether they are signed in right now.
    Looked up once per employee per session (refreshed every few seconds), so it costs nothing on most frames."""
    others = resp.get("others") or []
    if not others:
        return
    now = time.monotonic()
    missing = {o["employee_id"] for o in others
               if o.get("employee_id") and (o["employee_id"] not in s.others_cache or now - s.others_cache[o["employee_id"]][0] > OTHERS_CACHE_SECONDS)}
    if missing:
        async with SessionLocal() as db:
            org = await get_org_settings(db)
            for eid in missing:
                emp = await db.get(Employee, eid)
                info = None
                if emp is not None:
                    nxt = await next_expected_action(db, eid, org)
                    info = {"name": emp.full_name, "code": emp.employee_code, "signed_in": nxt["next"] == "check_out",
                            "since": nxt["last_event"]["occurred_at"] if nxt["last_event"] else None}
                s.others_cache[eid] = (now, info)
    for o in others:
        info = s.others_cache.get(o.get("employee_id") or "", (0.0, None))[1]
        o.update(info or {"name": None, "code": None, "signed_in": None, "since": None})


@router.websocket("/stream/{session_id}")
async def stream(ws: WebSocket, session_id: str):
    s = manager.get(session_id)
    if s is None or s.purpose != "attendance":
        await ws.close(code=4404)
        return
    await ws.accept()
    try:
        hello = json.loads(await ws.receive_text())
        if hello.get("nonce") != s.nonce:
            await ws.send_json({"state": "error", "message": "Session nonce mismatch"})
            await ws.close(code=4403)
            return
        if s.bound_employee_id:
            # The socket must belong to the same signed-in account the session was bound to.
            payload = decode_token(hello.get("token", ""), "access")
            async with SessionLocal() as db:
                acct = await db.get(UserAccount, payload["sub"]) if payload else None
            if not acct or acct.employee_id != s.bound_employee_id:
                await ws.send_json({"state": "error", "message": "This verification session belongs to another account"})
                await ws.close(code=4403)
                return
        pipe = get_pipeline()
        while not s.done:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if not data:
                continue
            if not manager.rate_ok(s):
                await ws.send_json({"state": "throttled", "frame": s.frames})  # the client waits for a reply per frame; never drop silently
                continue
            if pipe.busy:
                await ws.send_json({"state": "busy", "guidance": "The system is busy — hold still", "frame": s.frames})
                continue
            bgr = await pipe.decode_async(data)
            if bgr is None:
                await ws.send_json({"state": "error", "message": "Bad frame"})
                continue
            resp = await manager.process_attendance_frame(s, bgr)
            await _enrich_others(s, resp)
            if s.done and s.result:
                att_id = await _record_attempt(s.result, s, "attendance")
                if s.result.get("state") == "identified":
                    async with SessionLocal() as db:
                        emp = await db.get(Employee, s.result["employee_id"])
                        org = await get_org_settings(db)
                        nxt = await next_expected_action(db, emp.id, org)
                        day_row = (await db.execute(select(AttendanceDay).where(AttendanceDay.employee_id == emp.id, AttendanceDay.attendance_date == date.fromisoformat(nxt["attendance_date"])))).scalar_one_or_none()
                        today = {"first_in": day_row.first_in.isoformat() if day_row and day_row.first_in else None, "last_out": day_row.last_out.isoformat() if day_row and day_row.last_out else None,
                                 "worked_minutes": day_row.worked_minutes if day_row else 0} if day_row else None
                        # Adaptive templates: only after a confident, live-verified match with a clear margin.
                        if org.adaptive_templates and s.probe is not None and (s.result.get("match_score") or 0) >= 0.65 \
                                and (s.result.get("second_score") or 0) < s.result["match_score"] - 0.15:
                            try:
                                if await add_adaptive_template(db, emp.id, s.probe, s.result["match_score"]):
                                    await db.commit()
                            except Exception:  # never let template maintenance break a check-in
                                await db.rollback()
                    resp = {**resp, "attempt_id": att_id, "token": create_verification_token(s.id, emp.id, "face"),
                            "employee": {"id": emp.id, "name": emp.full_name, "code": emp.employee_code, "department": None}, "next": nxt, "today": today}
                else:
                    resp = {**resp, "attempt_id": att_id}
            await ws.send_json(resp)
    except WebSocketDisconnect:
        pass
    finally:
        if not s.done:
            manager.drop(s.id)


@router.websocket("/enrol-stream/{session_id}")
async def enrol_stream(ws: WebSocket, session_id: str):
    s = manager.get(session_id)
    if s is None or s.purpose != "enrolment":
        await ws.close(code=4404)
        return
    await ws.accept()
    try:
        hello = json.loads(await ws.receive_text())
        payload = decode_token(hello.get("token", ""), "access")
        if hello.get("nonce") != s.nonce or not payload or payload.get("role") not in (Role.admin.value, Role.hr.value):
            await ws.close(code=4403)
            return
        pipe = get_pipeline()
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("text"):
                cmd = json.loads(msg["text"])
                if cmd.get("cmd") == "save":
                    async with SessionLocal() as db:
                        emp = await db.get(Employee, s.employee_id)
                        actor = await db.get(UserAccount, payload["sub"])
                        try:
                            enrol = await commit_enrolment(db, s, employee=emp, created_by=actor.id if actor else None, notes=cmd.get("notes"))
                            liveness_low = (enrol.liveness_score or 0.0) < s.pad_threshold  # saved on the admin's in-person confirmation
                            await audit(db, "enrolment.create", actor=actor, target_type="employee", target_id=emp.id,
                                        detail={"enrolment_id": enrol.id, "templates": enrol.template_count, "quality": enrol.quality_score, "liveness": enrol.liveness_score, "liveness_low": liveness_low})
                            await db.commit()
                            await ws.send_json({"state": "saved", "enrolment_id": enrol.id, "template_count": enrol.template_count,
                                                "quality_score": round(enrol.quality_score or 0, 3), "liveness_score": round(enrol.liveness_score or 0, 3), "liveness_low": liveness_low})
                        except EnrolmentError as e:
                            await db.rollback()
                            await ws.send_json({"state": "error", "reason": e.code, "message": e.message, "detail": e.detail})
                    manager.drop(s.id)
                    break
                if cmd.get("cmd") == "restart":
                    s.poses.clear()
                    s.pose_hold.clear()
                    s.live_probs.clear()
                    s.created = time.monotonic()
                    await ws.send_json({"state": "restarted"})
                continue
            data = msg.get("bytes")
            if not data:
                continue
            if not manager.rate_ok(s):
                await ws.send_json({"state": "throttled", "frame": s.frames})
                continue
            if pipe.busy:
                await ws.send_json({"state": "busy", "guidance": "The system is busy — hold still", "frame": s.frames})
                continue
            bgr = await pipe.decode_async(data)
            if bgr is None:
                continue
            s.created = max(s.created, time.monotonic() - 60)  # keep an active enrolment session alive
            await ws.send_json(await manager.process_enrolment_frame(s, bgr))
    except WebSocketDisconnect:
        pass
    finally:
        manager.drop(s.id)


@router.get("/status")
async def status_(user: UserAccount = Depends(get_current_user)):
    pipe = get_pipeline()
    return {"active_sessions": manager.active, "index_templates": pipe.index.size, "index_employees": len(pipe.index.employees()), "busy": pipe.busy}
