"""Attendance engine: event validation, attendance-day resolution, daily summaries, corrections."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AttendanceAction,
    AttendanceCorrection,
    AttendanceDay,
    AttendanceEvent,
    AttendanceMethod,
    Employee,
    EmployeeStatus,
)
from app.services.org_settings import OrgSettings


class AttendanceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class EventResult:
    event: AttendanceEvent
    day: AttendanceDay
    late_minutes: int
    worked_minutes: int


def attendance_date_for(ts: datetime, org: OrgSettings) -> date:
    """Organisation-local attendance day. Times before `day_start` belong to the previous day so an
    overnight shift (in 22:00, out 06:00) stays on a single attendance day."""
    local = ts.astimezone(ZoneInfo(org.timezone))
    ds = org.t("day_start")
    if (local.hour, local.minute) < (ds.hour, ds.minute):
        return (local - timedelta(days=1)).date()
    return local.date()


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite (used in tests) drops tzinfo; everything in the engine is UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _local_dt(d: date, t, org: OrgSettings) -> datetime:
    return datetime.combine(d, t, tzinfo=ZoneInfo(org.timezone))


async def open_session_state(db: AsyncSession, employee_id: str, day: date) -> tuple[AttendanceEvent | None, list[AttendanceEvent]]:
    """Returns (last_non_voided_event, all_events_for_day) ordered by time."""
    res = await db.execute(
        select(AttendanceEvent)
        .where(and_(AttendanceEvent.employee_id == employee_id, AttendanceEvent.attendance_date == day, AttendanceEvent.voided.is_(False)))
        .order_by(AttendanceEvent.occurred_at)
    )
    events = list(res.scalars())
    for e in events:
        e.occurred_at = _aware(e.occurred_at)
    return (events[-1] if events else None), events


async def next_expected_action(db: AsyncSession, employee_id: str, org: OrgSettings, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    day = attendance_date_for(now, org)
    last, events = await open_session_state(db, employee_id, day)
    if last is None or last.action == AttendanceAction.check_out:
        return {"next": "check_in", "last_event": None if last is None else _event_dict(last), "attendance_date": day.isoformat()}
    return {"next": "check_out", "last_event": _event_dict(last), "attendance_date": day.isoformat()}


def _event_dict(e: AttendanceEvent) -> dict:
    return {"id": e.id, "action": e.action.value, "occurred_at": e.occurred_at.isoformat(), "method": e.method.value}


async def record_event(
    db: AsyncSession,
    *,
    employee: Employee,
    action: AttendanceAction,
    method: AttendanceMethod,
    org: OrgSettings,
    occurred_at: datetime | None = None,
    verification_attempt_id: str | None = None,
    match_score: float | None = None,
    liveness_score: float | None = None,
    ip: str | None = None,
    device_label: str | None = None,
    created_by: str | None = None,
    allow_duplicate_window: bool = False,
) -> EventResult:
    if employee.status != EmployeeStatus.active:
        raise AttendanceError("inactive", "This employee account is inactive.")
    now = occurred_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    day = attendance_date_for(now, org)
    last, events = await open_session_state(db, employee.id, day)

    if last is not None and not allow_duplicate_window:
        delta = (now - last.occurred_at).total_seconds()
        if 0 <= delta < org.duplicate_scan_seconds:
            raise AttendanceError("duplicate", f"An event was already recorded {int(delta)} seconds ago.")

    if action == AttendanceAction.check_in:
        if last is not None and last.action == AttendanceAction.check_in:
            raise AttendanceError("already_checked_in", "You are already checked in. Choose Check Out instead.")
    else:
        if last is None or last.action == AttendanceAction.check_out:
            raise AttendanceError("not_checked_in", "No open check-in found for today. Choose Check In instead.")
        if now < last.occurred_at:
            raise AttendanceError("out_of_order", "Check-out cannot be earlier than the check-in.")

    event = AttendanceEvent(
        employee_id=employee.id,
        action=action,
        method=method,
        occurred_at=now,
        attendance_date=day,
        verification_attempt_id=verification_attempt_id,
        match_score=match_score,
        liveness_score=liveness_score,
        ip=ip,
        device_label=device_label,
        created_by=created_by,
    )
    db.add(event)
    await db.flush()
    day_row = await recompute_day(db, employee.id, day, org)
    return EventResult(event, day_row, day_row.late_minutes, day_row.worked_minutes)


async def recompute_day(db: AsyncSession, employee_id: str, day: date, org: OrgSettings) -> AttendanceDay:
    _, events = await open_session_state(db, employee_id, day)
    row = (
        await db.execute(select(AttendanceDay).where(and_(AttendanceDay.employee_id == employee_id, AttendanceDay.attendance_date == day)))
    ).scalar_one_or_none()
    if row is None:
        row = AttendanceDay(employee_id=employee_id, attendance_date=day)
        db.add(row)

    worked = 0
    open_in: datetime | None = None
    first_in: datetime | None = None
    last_out: datetime | None = None
    for e in events:
        if e.action == AttendanceAction.check_in:
            open_in = e.occurred_at
            first_in = first_in or e.occurred_at
        elif open_in is not None:
            worked += int((e.occurred_at - open_in).total_seconds() // 60)
            last_out = e.occurred_at
            open_in = None

    work_start = _local_dt(day, org.t("work_start"), org)
    work_end = _local_dt(day, org.t("work_end"), org)
    late = 0
    if first_in is not None:
        late = max(0, int((first_in - work_start).total_seconds() // 60) - org.late_grace_minutes)
        late = late if (first_in - work_start).total_seconds() > org.late_grace_minutes * 60 else 0
    early = 0
    if last_out is not None and open_in is None and events and events[-1].action == AttendanceAction.check_out:
        early = max(0, int((work_end - last_out).total_seconds() // 60))

    row.first_in = first_in
    row.last_out = last_out
    row.worked_minutes = worked
    row.late_minutes = late
    row.early_leave_minutes = early
    row.is_open = open_in is not None
    if not events:
        row.status = "absent"
    elif open_in is not None and datetime.now(timezone.utc) - open_in > timedelta(hours=org.auto_close_after_hours):
        row.status = "missing_checkout"
    elif late > 0:
        row.status = "late"
    else:
        row.status = "present"
    await db.flush()
    return row


async def flag_missing_checkouts(db: AsyncSession, org: OrgSettings) -> int:
    """Marks open days older than `auto_close_after_hours` as missing_checkout. Returns count flagged."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=org.auto_close_after_hours)
    res = await db.execute(select(AttendanceDay).where(and_(AttendanceDay.is_open.is_(True), AttendanceDay.first_in < cutoff)))
    n = 0
    for row in res.scalars():
        if row.status != "missing_checkout":
            row.status = "missing_checkout"
            n += 1
    await db.flush()
    return n


async def apply_correction(
    db: AsyncSession,
    *,
    employee: Employee,
    kind: str,
    reason: str,
    actor_id: str,
    org: OrgSettings,
    event_id: str | None = None,
    action: AttendanceAction | None = None,
    occurred_at: datetime | None = None,
) -> AttendanceCorrection:
    """add: insert a manual event; void: mark an event voided; adjust: void + add at a new time."""
    if len(reason.strip()) < 5:
        raise AttendanceError("reason_required", "A meaningful reason is required for corrections.")
    before = after = None
    target_day: date | None = None

    if kind in ("void", "adjust"):
        ev = await db.get(AttendanceEvent, event_id) if event_id else None
        if ev is None or ev.employee_id != employee.id:
            raise AttendanceError("not_found", "Event not found for this employee.")
        before = _event_dict(ev)
        ev.voided = True
        target_day = ev.attendance_date
        await db.flush()
        if kind == "adjust":
            action, occurred_at = action or ev.action, occurred_at or ev.occurred_at

    if kind in ("add", "adjust"):
        if action is None or occurred_at is None:
            raise AttendanceError("invalid", "action and occurred_at are required.")
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        day = attendance_date_for(occurred_at, org)
        new = AttendanceEvent(
            employee_id=employee.id,
            action=action,
            method=AttendanceMethod.manual,
            occurred_at=occurred_at,
            attendance_date=day,
            created_by=actor_id,
        )
        db.add(new)
        await db.flush()
        after = _event_dict(new)
        target_day = target_day or day
        if day != target_day:
            await recompute_day(db, employee.id, day, org)

    corr = AttendanceCorrection(
        employee_id=employee.id,
        attendance_date=target_day,
        event_id=event_id,
        kind=kind,
        before=before,
        after=after,
        reason=reason,
        created_by=actor_id,
    )
    db.add(corr)
    if target_day:
        row = await recompute_day(db, employee.id, target_day, org)
        if row.status in ("present", "late"):
            row.status = "corrected" if kind != "add" or before else row.status
    await db.flush()
    return corr
