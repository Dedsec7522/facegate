from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from openpyxl import Workbook
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import set_auth_cookies
from app.core.config import settings
from app.core.deps import get_current_user, require_staff
from app.core.rate_limit import client_ip, limit, login_limiter
from app.core.security import create_access_token, decode_token, verify_pin
from app.db.base import get_db
from app.db.models import (
    AttendanceAction,
    AttendanceCorrection,
    BiometricEnrolment,
    EnrolmentStatus,
    AttendanceDay,
    AttendanceEvent,
    AttendanceMethod,
    Department,
    Employee,
    EmployeeStatus,
    Role,
    UserAccount,
    VerificationAttempt,
    VerificationOutcome,
)
from app.schemas.common import AttendanceDayOut, AttendanceEventIn, AttendanceEventOut, CorrectionIn, CorrectionOut, Page, PinAttendanceIn, PortalSessionOut
from app.services.attendance import AttendanceError, apply_correction, attendance_date_for, flag_missing_checkouts, next_expected_action, record_event
from app.services.audit import audit
from app.services.org_settings import get_org_settings

router = APIRouter(prefix="/attendance", tags=["attendance"])
_consumed_tokens: dict[str, float] = {}  # jti -> expiry (single-use guard; per-process)


def _consume(jti: str, exp: float) -> bool:
    now = datetime.now(timezone.utc).timestamp()
    for k, v in list(_consumed_tokens.items()):
        if v < now:
            _consumed_tokens.pop(k, None)
    if jti in _consumed_tokens:
        return False
    _consumed_tokens[jti] = exp
    return True


def _ev_out(e: AttendanceEvent, emp: Employee | None, dep: str | None) -> AttendanceEventOut:
    return AttendanceEventOut(id=e.id, employee_id=e.employee_id, employee_name=emp.full_name if emp else None, employee_code=emp.employee_code if emp else None,
                              department_name=dep, action=e.action.value, method=e.method.value, occurred_at=e.occurred_at, attendance_date=e.attendance_date,
                              match_score=e.match_score, liveness_score=e.liveness_score, voided=e.voided)


def _day_out(d: AttendanceDay, emp: Employee | None, dep: str | None) -> AttendanceDayOut:
    return AttendanceDayOut(id=d.id, employee_id=d.employee_id, employee_name=emp.full_name if emp else None, employee_code=emp.employee_code if emp else None,
                            department_name=dep, attendance_date=d.attendance_date, first_in=d.first_in, last_out=d.last_out, worked_minutes=d.worked_minutes,
                            late_minutes=d.late_minutes, early_leave_minutes=d.early_leave_minutes, status=d.status, is_open=d.is_open)


async def _open_portal_session(db: AsyncSession, request: Request, response: Response, emp: Employee, device_label: str | None) -> PortalSessionOut | None:
    """After a face-verified attendance event, sign the employee's *own* account in so the kiosk can open their dashboard.

    The face check is a single factor, so this deliberately issues only the short access cookie (no refresh session:
    the dashboard closes itself after `access_token_minutes`) and only for employee-role accounts without MFA — it never
    opens the admin console and never bypasses MFA. Returns None when the employee has no qualifying account."""
    user = (await db.execute(select(UserAccount).where(UserAccount.employee_id == emp.id))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not user or not user.is_active or user.role != Role.employee or user.mfa_enabled or (user.locked_until and user.locked_until > now):
        return None
    user.last_login_at = now
    await audit(db, "auth.face_login", actor=user, target_type="employee", target_id=emp.id, detail={"device_label": device_label}, request=request)
    set_auth_cookies(response, create_access_token(user.id, user.role.value, True))
    return PortalSessionOut(role=user.role.value, expires_in_minutes=settings.access_token_minutes)


# ---- kiosk ---------------------------------------------------------------------------------
@router.post("/events", response_model=AttendanceEventOut, status_code=201)
async def create_event(body: AttendanceEventIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    payload = decode_token(body.token, "verify")
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Verification expired — please scan your face again")
    if not _consume(payload["jti"], payload["exp"]):
        raise HTTPException(status.HTTP_409_CONFLICT, "This verification was already used")
    try:
        action = AttendanceAction(body.action)
    except ValueError:
        raise HTTPException(422, "action must be check_in or check_out")
    emp = await db.get(Employee, payload["sub"])
    if not emp:
        raise HTTPException(404, "Employee not found")
    att = (await db.execute(select(VerificationAttempt).where(VerificationAttempt.session_id == payload["sid"]))).scalar_one_or_none()
    org = await get_org_settings(db)
    try:
        res = await record_event(db, employee=emp, action=action, method=AttendanceMethod(payload["method"]), org=org,
                                 verification_attempt_id=att.id if att else None, match_score=att.match_score if att else None,
                                 liveness_score=att.liveness_score if att else None, ip=client_ip(request), device_label=body.device_label)
    except AttendanceError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": e.code, "message": e.message})
    portal = await _open_portal_session(db, request, response, emp, body.device_label) if body.open_portal else None
    await db.commit()
    dep = (await db.get(Department, emp.department_id)).name if emp.department_id else None
    out = _ev_out(res.event, emp, dep)
    out.portal_session = portal
    return out


@router.post("/events/pin", response_model=AttendanceEventOut, status_code=201, dependencies=[Depends(limit(login_limiter))])
async def create_event_pin(body: PinAttendanceIn, request: Request, db: AsyncSession = Depends(get_db)):
    """Non-biometric fallback. Only works for employees whose admin explicitly enabled a PIN; always logged as method=pin."""
    emp = (await db.execute(select(Employee).where(Employee.employee_code == body.employee_code))).scalar_one_or_none()
    if not emp or not emp.pin_fallback_enabled or not emp.pin_hash or not verify_pin(body.pin, emp.pin_salt or "", emp.pin_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid employee code or PIN, or PIN fallback is not enabled")
    try:
        action = AttendanceAction(body.action)
    except ValueError:
        raise HTTPException(422, "action must be check_in or check_out")
    org = await get_org_settings(db)
    try:
        res = await record_event(db, employee=emp, action=action, method=AttendanceMethod.pin, org=org, ip=client_ip(request), device_label=body.device_label)
    except AttendanceError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": e.code, "message": e.message})
    await audit(db, "attendance.pin_fallback", target_type="employee", target_id=emp.id, detail={"action": action.value}, request=request)
    await db.commit()
    dep = (await db.get(Department, emp.department_id)).name if emp.department_id else None
    return _ev_out(res.event, emp, dep)


# ---- admin queries ----------------------------------------------------------------------------
async def _emp_dep(db: AsyncSession, ids: set[str]) -> tuple[dict[str, Employee], dict[str, str]]:
    if not ids:
        return {}, {}
    emps = {e.id: e for e in (await db.execute(select(Employee).where(Employee.id.in_(ids)))).scalars()}
    deps = {d.id: d.name for d in (await db.execute(select(Department))).scalars()}
    return emps, {e.id: deps.get(e.department_id or "", None) for e in emps.values()}


@router.get("/events", response_model=Page[AttendanceEventOut])
async def list_events(
    date_from: date | None = None, date_to: date | None = None, employee_id: str | None = None, department_id: str | None = None,
    method: str | None = None, include_voided: bool = False, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db), _=Depends(require_staff),
):
    stmt = select(AttendanceEvent)
    if date_from:
        stmt = stmt.where(AttendanceEvent.attendance_date >= date_from)
    if date_to:
        stmt = stmt.where(AttendanceEvent.attendance_date <= date_to)
    if employee_id:
        stmt = stmt.where(AttendanceEvent.employee_id == employee_id)
    if department_id:
        stmt = stmt.where(AttendanceEvent.employee_id.in_(select(Employee.id).where(Employee.department_id == department_id)))
    if method:
        stmt = stmt.where(AttendanceEvent.method == AttendanceMethod(method))
    if not include_voided:
        stmt = stmt.where(AttendanceEvent.voided.is_(False))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(AttendanceEvent.occurred_at.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    emps, deps = await _emp_dep(db, {r.employee_id for r in rows})
    return Page(items=[_ev_out(r, emps.get(r.employee_id), deps.get(r.employee_id)) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/days", response_model=Page[AttendanceDayOut])
async def list_days(
    date_from: date | None = None, date_to: date | None = None, employee_id: str | None = None, department_id: str | None = None,
    status_: str | None = Query(default=None, alias="status"), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db), _=Depends(require_staff),
):
    org = await get_org_settings(db)
    await flag_missing_checkouts(db, org)
    stmt = select(AttendanceDay)
    if date_from:
        stmt = stmt.where(AttendanceDay.attendance_date >= date_from)
    if date_to:
        stmt = stmt.where(AttendanceDay.attendance_date <= date_to)
    if employee_id:
        stmt = stmt.where(AttendanceDay.employee_id == employee_id)
    if department_id:
        stmt = stmt.where(AttendanceDay.employee_id.in_(select(Employee.id).where(Employee.department_id == department_id)))
    if status_:
        stmt = stmt.where(AttendanceDay.status == status_)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(AttendanceDay.attendance_date.desc(), AttendanceDay.first_in.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    await db.commit()
    emps, deps = await _emp_dep(db, {r.employee_id for r in rows})
    return Page(items=[_day_out(r, emps.get(r.employee_id), deps.get(r.employee_id)) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/today")
async def today_board(db: AsyncSession = Depends(get_db), _=Depends(require_staff)):
    """Real-time board: every active employee with today's status."""
    org = await get_org_settings(db)
    today = attendance_date_for(datetime.now(timezone.utc), org)
    await flag_missing_checkouts(db, org)
    emps = (await db.execute(select(Employee).where(Employee.status == EmployeeStatus.active).order_by(Employee.last_name))).scalars().all()
    days = {d.employee_id: d for d in (await db.execute(select(AttendanceDay).where(AttendanceDay.attendance_date == today))).scalars()}
    deps = {d.id: d.name for d in (await db.execute(select(Department))).scalars()}
    await db.commit()
    items = []
    for e in emps:
        d = days.get(e.id)
        items.append({"employee_id": e.id, "name": e.full_name, "code": e.employee_code, "department": deps.get(e.department_id or ""),
                      "status": (d.status if d else "absent"), "is_open": d.is_open if d else False, "first_in": d.first_in if d else None,
                      "last_out": d.last_out if d else None, "worked_minutes": d.worked_minutes if d else 0, "late_minutes": d.late_minutes if d else 0})
    summary = {"date": today.isoformat(), "total": len(emps), "present": sum(1 for i in items if i["status"] in ("present", "late", "corrected")),
               "late": sum(1 for i in items if i["late_minutes"] > 0), "absent": sum(1 for i in items if i["status"] == "absent"),
               "on_site": sum(1 for i in items if i["is_open"]), "missing_checkout": sum(1 for i in items if i["status"] == "missing_checkout")}
    return {"summary": summary, "items": items}


@router.get("/feed")
async def live_feed(limit_: int = Query(20, alias="limit", ge=1, le=100), db: AsyncSession = Depends(get_db), _=Depends(require_staff)):
    rows = (await db.execute(select(AttendanceEvent).where(AttendanceEvent.voided.is_(False)).order_by(AttendanceEvent.occurred_at.desc()).limit(limit_))).scalars().all()
    emps, deps = await _emp_dep(db, {r.employee_id for r in rows})
    fails = (await db.execute(select(VerificationAttempt).where(VerificationAttempt.outcome != VerificationOutcome.identified)
                              .order_by(VerificationAttempt.created_at.desc()).limit(10))).scalars().all()
    return {"events": [_ev_out(r, emps.get(r.employee_id), deps.get(r.employee_id)) for r in rows],
            "failed_verifications": [{"id": f.id, "outcome": f.outcome.value, "reason": f.reason, "liveness_score": f.liveness_score,
                                      "match_score": f.match_score, "created_at": f.created_at, "ip": f.ip} for f in fails]}


@router.get("/verification-attempts")
async def verification_attempts(outcome: str | None = None, date_from: date | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
                                db: AsyncSession = Depends(get_db), _=Depends(require_staff)):
    stmt = select(VerificationAttempt)
    if outcome:
        stmt = stmt.where(VerificationAttempt.outcome == VerificationOutcome(outcome))
    if date_from:
        stmt = stmt.where(VerificationAttempt.created_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(VerificationAttempt.created_at.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    emps, _ = await _emp_dep(db, {r.employee_id for r in rows if r.employee_id})
    return {"items": [{"id": r.id, "outcome": r.outcome.value, "reason": r.reason, "employee_id": r.employee_id,
                       "employee_name": emps[r.employee_id].full_name if r.employee_id in emps else None, "match_score": r.match_score,
                       "second_score": r.second_score, "liveness_score": r.liveness_score, "challenge": r.challenge, "frames": r.frames,
                       "duration_ms": r.duration_ms, "ip": r.ip, "created_at": r.created_at, "purpose": r.purpose} for r in rows],
            "total": total, "page": page, "page_size": page_size}


# ---- corrections -----------------------------------------------------------------------------
@router.post("/corrections", response_model=CorrectionOut, status_code=201)
async def create_correction(body: CorrectionIn, request: Request, db: AsyncSession = Depends(get_db), user: UserAccount = Depends(require_staff)):
    emp = await db.get(Employee, body.employee_id)
    if not emp:
        raise HTTPException(404, "Employee not found")
    org = await get_org_settings(db)
    try:
        corr = await apply_correction(db, employee=emp, kind=body.kind, reason=body.reason, actor_id=user.id, org=org, event_id=body.event_id,
                                      action=AttendanceAction(body.action) if body.action else None, occurred_at=body.occurred_at)
    except AttendanceError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": e.code, "message": e.message})
    await audit(db, "attendance.correction", actor=user, target_type="employee", target_id=emp.id,
                detail={"kind": body.kind, "reason": body.reason, "before": corr.before, "after": corr.after}, request=request)
    await db.commit()
    return CorrectionOut.model_validate(corr)


@router.get("/corrections", response_model=list[CorrectionOut])
async def list_corrections(employee_id: str | None = None, limit_: int = Query(100, alias="limit", le=1000), db: AsyncSession = Depends(get_db), _=Depends(require_staff)):
    stmt = select(AttendanceCorrection).order_by(AttendanceCorrection.created_at.desc()).limit(limit_)
    if employee_id:
        stmt = stmt.where(AttendanceCorrection.employee_id == employee_id)
    return [CorrectionOut.model_validate(r) for r in (await db.execute(stmt)).scalars()]


# ---- export -------------------------------------------------------------------------------
@router.get("/export")
async def export(fmt: str = "csv", date_from: date | None = None, date_to: date | None = None, department_id: str | None = None,
                 db: AsyncSession = Depends(get_db), user: UserAccount = Depends(require_staff), request: Request = None):
    date_to = date_to or date.today()
    date_from = date_from or (date_to - timedelta(days=30))
    stmt = select(AttendanceDay).where(and_(AttendanceDay.attendance_date >= date_from, AttendanceDay.attendance_date <= date_to))
    if department_id:
        stmt = stmt.where(AttendanceDay.employee_id.in_(select(Employee.id).where(Employee.department_id == department_id)))
    rows = (await db.execute(stmt.order_by(AttendanceDay.attendance_date, AttendanceDay.employee_id))).scalars().all()
    emps, deps = await _emp_dep(db, {r.employee_id for r in rows})
    header = ["date", "employee_code", "employee", "department", "status", "first_in", "last_out", "worked_minutes", "late_minutes", "early_leave_minutes"]
    data = [[r.attendance_date.isoformat(), emps[r.employee_id].employee_code if r.employee_id in emps else "", emps[r.employee_id].full_name if r.employee_id in emps else "",
             deps.get(r.employee_id) or "", r.status, r.first_in.isoformat() if r.first_in else "", r.last_out.isoformat() if r.last_out else "",
             r.worked_minutes, r.late_minutes, r.early_leave_minutes] for r in rows]
    await audit(db, "attendance.export", actor=user, detail={"fmt": fmt, "from": date_from.isoformat(), "to": date_to.isoformat(), "rows": len(data)}, request=request)
    await db.commit()
    name = f"attendance_{date_from}_{date_to}"
    if fmt == "xlsx":
        wb = Workbook()
        ws = wb.active
        ws.title = "Attendance"
        ws.append(header)
        for row in data:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    w.writerows(data)
    return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


# ---- employee portal --------------------------------------------------------------------------
@router.get("/me/status")
async def my_status(db: AsyncSession = Depends(get_db), user: UserAccount = Depends(get_current_user)):
    if not user.employee_id:
        raise HTTPException(404, "No employee profile linked to this account")
    org = await get_org_settings(db)
    nxt = await next_expected_action(db, user.employee_id, org)
    today = date.fromisoformat(nxt["attendance_date"])
    day = (await db.execute(select(AttendanceDay).where(AttendanceDay.employee_id == user.employee_id, AttendanceDay.attendance_date == today))).scalar_one_or_none()
    emp = await db.get(Employee, user.employee_id)
    enrolled = (await db.execute(select(BiometricEnrolment.id).where(BiometricEnrolment.employee_id == emp.id, BiometricEnrolment.status == EnrolmentStatus.active))).first() is not None
    return {"employee": {"id": emp.id, "name": emp.full_name, "code": emp.employee_code, "enrolled": enrolled}, "next": nxt, "today": _day_out(day, emp, None) if day else None,
            "work_start": org.work_start, "work_end": org.work_end, "timezone": org.timezone}


@router.get("/me/thumbnail")
async def my_thumbnail(db: AsyncSession = Depends(get_db), user: UserAccount = Depends(get_current_user)):
    """The signed-in employee's own enrolment thumbnail (never another employee's)."""
    if not user.employee_id:
        raise HTTPException(404, "No employee profile linked to this account")
    r = (await db.execute(select(BiometricEnrolment).where(BiometricEnrolment.employee_id == user.employee_id, BiometricEnrolment.status == EnrolmentStatus.active))).scalar_one_or_none()
    if not r or not r.thumbnail_jpeg:
        raise HTTPException(404, "No thumbnail")
    return Response(content=r.thumbnail_jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.get("/me/days", response_model=Page[AttendanceDayOut])
async def my_days(date_from: date | None = None, date_to: date | None = None, page: int = Query(1, ge=1), page_size: int = Query(31, ge=1, le=200),
                  db: AsyncSession = Depends(get_db), user: UserAccount = Depends(get_current_user)):
    if not user.employee_id:
        raise HTTPException(404, "No employee profile linked to this account")
    stmt = select(AttendanceDay).where(AttendanceDay.employee_id == user.employee_id)
    if date_from:
        stmt = stmt.where(AttendanceDay.attendance_date >= date_from)
    if date_to:
        stmt = stmt.where(AttendanceDay.attendance_date <= date_to)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(AttendanceDay.attendance_date.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    emp = await db.get(Employee, user.employee_id)
    return Page(items=[_day_out(r, emp, None) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/me/insights")
async def my_insights(days: int = Query(30, ge=7, le=365), db: AsyncSession = Depends(get_db), user: UserAccount = Depends(get_current_user)):
    """Rolling-window attendance statistics for the signed-in employee (times averaged in the organisation's local time)."""
    if not user.employee_id:
        raise HTTPException(404, "No employee profile linked to this account")
    from zoneinfo import ZoneInfo

    org = await get_org_settings(db)
    tz = ZoneInfo(org.timezone)
    today = attendance_date_for(datetime.now(timezone.utc), org)
    since = today - timedelta(days=days - 1)
    rows = (await db.execute(select(AttendanceDay).where(AttendanceDay.employee_id == user.employee_id, AttendanceDay.attendance_date >= since,
                                                        AttendanceDay.attendance_date <= today))).scalars().all()

    def _mod(ts: datetime | None) -> int | None:
        if ts is None:
            return None
        local = (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(tz)
        return local.hour * 60 + local.minute

    present = [r for r in rows if r.status != "absent" and r.first_in is not None]
    ins = [m for m in (_mod(r.first_in) for r in present) if m is not None]
    outs = [m for m in (_mod(r.last_out) for r in present if r.last_out is not None) if m is not None]
    worked = [r.worked_minutes for r in present if r.worked_minutes > 0 and not r.is_open]
    late_days = sum(1 for r in present if r.late_minutes > 0)
    missing = sum(1 for r in rows if r.status == "missing_checkout")
    on_time = (len(present) - late_days) / len(present) if present else None
    return {
        "window_days": days, "from": since.isoformat(), "to": today.isoformat(), "timezone": org.timezone,
        "days_present": len(present), "late_days": late_days, "missing_checkouts": missing,
        "avg_daily_minutes": round(sum(worked) / len(worked)) if worked else None,
        "avg_check_in_minutes": round(sum(ins) / len(ins)) if ins else None,
        "avg_check_out_minutes": round(sum(outs) / len(outs)) if outs else None,
        "on_time_rate": on_time,
        # Penalty points, as in the HR portal: one per late arrival and one per missed logout.
        "black_points": late_days + missing,
        "total_minutes": sum(r.worked_minutes for r in present),
    }


@router.get("/me/events", response_model=list[AttendanceEventOut])
async def my_events(attendance_date: date, db: AsyncSession = Depends(get_db), user: UserAccount = Depends(get_current_user)):
    if not user.employee_id:
        raise HTTPException(404, "No employee profile linked to this account")
    rows = (await db.execute(select(AttendanceEvent).where(AttendanceEvent.employee_id == user.employee_id, AttendanceEvent.attendance_date == attendance_date)
                             .order_by(AttendanceEvent.occurred_at))).scalars().all()
    emp = await db.get(Employee, user.employee_id)
    return [_ev_out(r, emp, None) for r in rows]
