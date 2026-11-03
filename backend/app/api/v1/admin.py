"""Dashboard stats, reports/analytics, settings, audit log."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin, require_staff
from app.db.base import get_db
from app.db.models import AttendanceDay, AuditLog, BiometricEnrolment, Department, Employee, EmployeeStatus, EnrolmentStatus, UserAccount, VerificationAttempt, VerificationOutcome
from app.schemas.common import SettingsPatch
from app.services.attendance import attendance_date_for
from app.services.audit import audit
from app.services.org_settings import get_org_settings, update_org_settings
from app.vision.pipeline import get_pipeline

router = APIRouter(tags=["admin"])


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db), _=Depends(require_staff)):
    org = await get_org_settings(db)
    today = attendance_date_for(datetime.now(timezone.utc), org)
    week_ago = today - timedelta(days=13)
    total = (await db.execute(select(func.count(Employee.id)).where(Employee.status == EmployeeStatus.active))).scalar_one()
    enrolled = (await db.execute(select(func.count(func.distinct(BiometricEnrolment.employee_id))).where(BiometricEnrolment.status == EnrolmentStatus.active))).scalar_one()
    days_today = (await db.execute(select(AttendanceDay).where(AttendanceDay.attendance_date == today))).scalars().all()
    present = sum(1 for d in days_today if d.status in ("present", "late", "corrected", "missing_checkout"))
    late = sum(1 for d in days_today if d.late_minutes > 0)
    on_site = sum(1 for d in days_today if d.is_open)

    # Portable trend computation (works on SQLite and Postgres).
    rows = (await db.execute(select(AttendanceDay).where(AttendanceDay.attendance_date >= week_ago))).scalars().all()
    by_day: dict[date, dict] = {}
    for d in rows:
        b = by_day.setdefault(d.attendance_date, {"present": 0, "late": 0, "worked": 0})
        b["present"] += 1 if d.status != "absent" else 0
        b["late"] += 1 if d.late_minutes > 0 else 0
        b["worked"] += d.worked_minutes
    trend = []
    for i in range(14):
        day = week_ago + timedelta(days=i)
        b = by_day.get(day, {"present": 0, "late": 0, "worked": 0})
        trend.append({"date": day.isoformat(), "present": b["present"], "late": b["late"], "absent": max(0, total - b["present"]),
                      "avg_hours": round(b["worked"] / 60 / b["present"], 2) if b["present"] else 0})

    deps = (await db.execute(select(Department.id, Department.name, func.count(Employee.id)).outerjoin(Employee, (Employee.department_id == Department.id) & (Employee.status == EmployeeStatus.active)).group_by(Department.id))).all()
    dep_today = {}
    emp_dep = {e.id: e.department_id for e in (await db.execute(select(Employee.id, Employee.department_id))).all()}
    for d in days_today:
        if d.status != "absent":
            dep_today[emp_dep.get(d.employee_id)] = dep_today.get(emp_dep.get(d.employee_id), 0) + 1
    departments = [{"id": i, "name": n, "headcount": c, "present_today": dep_today.get(i, 0)} for i, n, c in deps]

    since = datetime.now(timezone.utc) - timedelta(days=7)
    att_rows = (await db.execute(select(VerificationAttempt.outcome, func.count(VerificationAttempt.id)).where(VerificationAttempt.created_at >= since).group_by(VerificationAttempt.outcome))).all()
    outcomes = {o.value: c for o, c in att_rows}
    pipe = get_pipeline()
    return {
        "date": today.isoformat(),
        "kpis": {"employees": total, "enrolled": enrolled, "present_today": present, "late_today": late, "on_site_now": on_site,
                 "absent_today": max(0, total - present), "attendance_rate": round(present / total * 100, 1) if total else 0.0},
        "trend": trend,
        "departments": departments,
        "verification_7d": {"total": sum(outcomes.values()), **outcomes},
        "engine": {"index_templates": pipe.index.size, "index_employees": len(pipe.index.employees()), "workers": pipe.executor._max_workers},
    }


@router.get("/reports/summary")
async def report_summary(date_from: date, date_to: date, department_id: str | None = None, db: AsyncSession = Depends(get_db), _=Depends(require_staff)):
    stmt = select(AttendanceDay).where(AttendanceDay.attendance_date >= date_from, AttendanceDay.attendance_date <= date_to)
    if department_id:
        stmt = stmt.where(AttendanceDay.employee_id.in_(select(Employee.id).where(Employee.department_id == department_id)))
    rows = (await db.execute(stmt)).scalars().all()
    emps = {e.id: e for e in (await db.execute(select(Employee))).scalars()}
    deps = {d.id: d.name for d in (await db.execute(select(Department))).scalars()}
    per_emp: dict[str, dict] = {}
    per_day: dict[str, dict] = {}
    for r in rows:
        e = per_emp.setdefault(r.employee_id, {"employee_id": r.employee_id, "name": emps[r.employee_id].full_name if r.employee_id in emps else "?",
                                                 "code": emps[r.employee_id].employee_code if r.employee_id in emps else "", "department": deps.get(emps[r.employee_id].department_id) if r.employee_id in emps else None,
                                                 "days_present": 0, "days_late": 0, "worked_minutes": 0, "late_minutes": 0, "missing_checkouts": 0})
        if r.status != "absent":
            e["days_present"] += 1
        if r.late_minutes > 0:
            e["days_late"] += 1
        e["worked_minutes"] += r.worked_minutes
        e["late_minutes"] += r.late_minutes
        e["missing_checkouts"] += 1 if r.status == "missing_checkout" else 0
        d = per_day.setdefault(r.attendance_date.isoformat(), {"date": r.attendance_date.isoformat(), "present": 0, "late": 0, "worked_minutes": 0, "missing_checkouts": 0})
        d["present"] += 1 if r.status != "absent" else 0
        d["late"] += 1 if r.late_minutes > 0 else 0
        d["worked_minutes"] += r.worked_minutes
        d["missing_checkouts"] += 1 if r.status == "missing_checkout" else 0
    working_days = len(per_day)
    total_emp = (await db.execute(select(func.count(Employee.id)).where(Employee.status == EmployeeStatus.active))).scalar_one()
    return {"from": date_from.isoformat(), "to": date_to.isoformat(), "working_days": working_days, "active_employees": total_emp,
            "totals": {"present_days": sum(e["days_present"] for e in per_emp.values()), "late_days": sum(e["days_late"] for e in per_emp.values()),
                       "worked_hours": round(sum(e["worked_minutes"] for e in per_emp.values()) / 60, 1), "missing_checkouts": sum(e["missing_checkouts"] for e in per_emp.values())},
            "per_employee": sorted(per_emp.values(), key=lambda x: x["name"]), "per_day": sorted(per_day.values(), key=lambda x: x["date"])}


@router.get("/settings")
async def get_settings_(db: AsyncSession = Depends(get_db), _=Depends(require_staff)):
    return asdict(await get_org_settings(db))


@router.patch("/settings")
async def patch_settings(body: SettingsPatch, request: Request, db: AsyncSession = Depends(get_db), user: UserAccount = Depends(require_admin)):
    patch = body.model_dump(exclude_unset=True)
    if patch.get("timezone"):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(patch["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(422, f"Unknown timezone '{patch['timezone']}' — use an IANA name such as Europe/London")
    org = await update_org_settings(db, patch, user.id)
    await audit(db, "settings.update", actor=user, target_type="settings", detail=patch, request=request)
    await db.commit()
    return asdict(org)


@router.get("/audit")
async def audit_log(action: str | None = None, actor: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
                    db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if actor:
        stmt = stmt.where(AuditLog.actor_email.like(f"%{actor}%"))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {"items": [{"id": r.id, "actor_email": r.actor_email, "action": r.action, "target_type": r.target_type, "target_id": r.target_id,
                       "detail": r.detail, "ip": r.ip, "created_at": r.created_at} for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/users")
async def list_users(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    rows = (await db.execute(select(UserAccount).order_by(UserAccount.email))).scalars().all()
    return [{"id": u.id, "email": u.email, "username": u.username, "role": u.role.value, "is_active": u.is_active, "mfa_enabled": u.mfa_enabled, "employee_id": u.employee_id,
             "last_login_at": u.last_login_at, "locked_until": u.locked_until} for u in rows]
