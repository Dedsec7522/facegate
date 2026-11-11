"""Attendance engine state machine: check-in/out ordering, duplicates, overnight day boundary, lateness, corrections."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import AttendanceAction, AttendanceMethod, Employee
from app.services.attendance import AttendanceError, apply_correction, attendance_date_for, next_expected_action, record_event
from app.services.org_settings import defaults




TODAY = date.today()


def org(tz: str = "UTC"):
    o = defaults()
    o.timezone = tz
    o.day_start, o.work_start, o.work_end = "04:00", "09:00", "17:30"
    o.late_grace_minutes, o.duplicate_scan_seconds = 10, 120
    o.relogin_cooldown_hours = 0  # the cycle test below re-enters the same day; the cooldown has its own test
    return o


def utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_attendance_day_overnight_boundary():
    o = org("Europe/London")
    # 02:30 UTC on 11 Nov is before day_start 04:00 → belongs to 10 Nov
    assert attendance_date_for(utc(2026, 11, 11, 2, 30), o) == date(2026, 11, 10)
    assert attendance_date_for(utc(2026, 11, 11, 4, 0), o) == date(2026, 11, 11)
    # BST: 23:30 UTC on 1 Jul = 00:30 local on 2 Jul, still before day_start → 1 Jul
    assert attendance_date_for(utc(2026, 7, 1, 23, 30), o) == date(2026, 7, 1)


async def _employee(db) -> Employee:
    """A fresh employee per test so engine tests never share attendance state (rolled back afterwards)."""
    import uuid

    code = f"ENG-{uuid.uuid4().hex[:6]}"
    emp = Employee(employee_code=code, first_name="Engine", last_name=code, email=f"{code}@test.local")
    db.add(emp)
    await db.flush()
    return emp


async def test_checkin_checkout_cycle_and_rules(db):
    o = org()
    emp = await _employee(db)
    day = utc(TODAY.year, TODAY.month, TODAY.day, 9, 25)  # 09:25 UTC = 09:25 GMT → 15 min late after 10 min grace
    with pytest.raises(AttendanceError) as e:
        await record_event(db, employee=emp, action=AttendanceAction.check_out, method=AttendanceMethod.face, org=o, occurred_at=day)
    assert e.value.code == "not_checked_in"

    r = await record_event(db, employee=emp, action=AttendanceAction.check_in, method=AttendanceMethod.face, org=o, occurred_at=day)
    assert r.day.status == "late" and r.late_minutes == 15 and r.day.is_open

    with pytest.raises(AttendanceError) as e:  # duplicate scan inside the window
        await record_event(db, employee=emp, action=AttendanceAction.check_in, method=AttendanceMethod.face, org=o, occurred_at=utc(TODAY.year, TODAY.month, TODAY.day, 9, 26))
    assert e.value.code == "duplicate"

    with pytest.raises(AttendanceError) as e:  # already checked in (outside duplicate window)
        await record_event(db, employee=emp, action=AttendanceAction.check_in, method=AttendanceMethod.face, org=o, occurred_at=utc(TODAY.year, TODAY.month, TODAY.day, 10, 0))
    assert e.value.code == "already_checked_in"

    nxt = await next_expected_action(db, emp.id, o, now=utc(TODAY.year, TODAY.month, TODAY.day, 12, 0))
    assert nxt["next"] == "check_out"

    r2 = await record_event(db, employee=emp, action=AttendanceAction.check_out, method=AttendanceMethod.face, org=o, occurred_at=utc(TODAY.year, TODAY.month, TODAY.day, 17, 0))
    assert r2.day.worked_minutes == 7 * 60 + 35 and not r2.day.is_open and r2.day.early_leave_minutes == 30

    # Second session the same day (lunch break pattern) accumulates minutes
    await record_event(db, employee=emp, action=AttendanceAction.check_in, method=AttendanceMethod.face, org=o, occurred_at=utc(TODAY.year, TODAY.month, TODAY.day, 18, 0))
    r3 = await record_event(db, employee=emp, action=AttendanceAction.check_out, method=AttendanceMethod.face, org=o, occurred_at=utc(TODAY.year, TODAY.month, TODAY.day, 19, 0))
    assert r3.day.worked_minutes == 7 * 60 + 35 + 60


async def test_relogin_cooldown_blocks_early_login(db):
    o = org()
    o.relogin_cooldown_hours = 10
    emp = await _employee(db)
    y, mo, d = TODAY.year, TODAY.month, TODAY.day
    await record_event(db, employee=emp, action=AttendanceAction.check_in, method=AttendanceMethod.face, org=o, occurred_at=utc(y, mo, d, 9, 0))
    await record_event(db, employee=emp, action=AttendanceAction.check_out, method=AttendanceMethod.face, org=o, occurred_at=utc(y, mo, d, 17, 0))
    nxt = await next_expected_action(db, emp.id, o, now=utc(y, mo, d, 18, 0))
    assert nxt["next"] == "check_in" and nxt["login_allowed_at"] == (utc(y, mo, d, 17, 0) + timedelta(hours=10)).isoformat() and nxt["cooldown_hours"] == 10
    with pytest.raises(AttendanceError) as e:  # 1 h after logout: refused with a clear message
        await record_event(db, employee=emp, action=AttendanceAction.check_in, method=AttendanceMethod.face, org=o, occurred_at=utc(y, mo, d, 18, 0))
    assert e.value.code == "cooldown" and "log in again from" in e.value.message
    # 10 h after the logout (03:00, still the same attendance day since the day starts at 04:00) it is allowed again
    r = await record_event(db, employee=emp, action=AttendanceAction.check_in, method=AttendanceMethod.face, org=o, occurred_at=utc(y, mo, d, 17, 0) + timedelta(hours=10))
    assert r.day.is_open
    nxt = await next_expected_action(db, emp.id, o, now=utc(y, mo, d, 17, 0) + timedelta(hours=10, minutes=5))
    assert nxt["next"] == "check_out" and nxt["login_allowed_at"] is None


async def test_inactive_employee_rejected(db):
    o = org()
    emp = await _employee(db)
    from app.db.models import EmployeeStatus

    emp.status = EmployeeStatus.inactive
    with pytest.raises(AttendanceError) as e:
        await record_event(db, employee=emp, action=AttendanceAction.check_in, method=AttendanceMethod.face, org=o, occurred_at=utc(TODAY.year, TODAY.month, TODAY.day, 9, 0))
    assert e.value.code == "inactive"
    emp.status = EmployeeStatus.active


async def test_corrections_are_audited_and_recompute(db):
    o = org()
    emp = await _employee(db)
    r = await record_event(db, employee=emp, action=AttendanceAction.check_in, method=AttendanceMethod.face, org=o, occurred_at=utc(TODAY.year, TODAY.month, TODAY.day, 9, 0))
    with pytest.raises(AttendanceError):
        await apply_correction(db, employee=emp, kind="void", reason="x", actor_id="admin", org=o, event_id=r.event.id)
    corr = await apply_correction(db, employee=emp, kind="adjust", reason="Badge reader outage, verified by manager", actor_id="admin", org=o,
                                  event_id=r.event.id, occurred_at=utc(TODAY.year, TODAY.month, TODAY.day, 8, 55))
    assert corr.before["occurred_at"].endswith("T09:00:00+00:00") and corr.after["occurred_at"].endswith("T08:55:00+00:00")
    assert r.event.voided is True
    added = await apply_correction(db, employee=emp, kind="add", reason="Forgot to check out, confirmed by line manager", actor_id="admin", org=o,
                                   action=AttendanceAction.check_out, occurred_at=utc(TODAY.year, TODAY.month, TODAY.day, 17, 30))
    assert added.after["action"] == "check_out"
    nxt = await next_expected_action(db, emp.id, o, now=utc(TODAY.year, TODAY.month, TODAY.day, 20, 0))
    assert nxt["next"] == "check_in"
