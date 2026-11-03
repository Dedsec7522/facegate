from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import require_admin, require_staff
from app.core.security import hash_password, hash_pin
from app.db.base import get_db
from app.db.models import BiometricEnrolment, Department, Employee, EmployeeStatus, EnrolmentStatus, Role, UserAccount
from app.schemas.common import AccountCreateIn, DepartmentIn, DepartmentOut, EmployeeIn, EmployeeOut, EmployeeUpdate, Page, PinIn
from app.services.audit import audit
from app.services.enrolment import purge_biometrics, revoke_enrolments

router = APIRouter(tags=["employees"])


async def _enrolment_map(db: AsyncSession, ids: list[str]) -> dict[str, BiometricEnrolment]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(BiometricEnrolment).where(BiometricEnrolment.employee_id.in_(ids), BiometricEnrolment.status == EnrolmentStatus.active)
        )
    ).scalars()
    return {r.employee_id: r for r in rows}


def _out(e: Employee, enrol: BiometricEnrolment | None) -> EmployeeOut:
    return EmployeeOut(
        id=e.id, employee_code=e.employee_code, first_name=e.first_name, last_name=e.last_name, email=e.email, job_title=e.job_title,
        department_id=e.department_id, department_name=e.department.name if e.department else None, status=e.status.value,
        pin_fallback_enabled=e.pin_fallback_enabled, enrolled=enrol is not None, enrolment_at=enrol.created_at if enrol else None,
        has_account=e.account is not None, created_at=e.created_at,
    )


# ---- departments --------------------------------------------------------------------------
@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(db: AsyncSession = Depends(get_db), _=Depends(require_staff)):
    rows = await db.execute(
        select(Department, func.count(Employee.id)).outerjoin(Employee, Employee.department_id == Department.id).group_by(Department.id).order_by(Department.name)
    )
    return [DepartmentOut(id=d.id, name=d.name, code=d.code, employee_count=c) for d, c in rows.all()]


@router.post("/departments", response_model=DepartmentOut, status_code=201)
async def create_department(body: DepartmentIn, request: Request, db: AsyncSession = Depends(get_db), user=Depends(require_admin)):
    exists = (await db.execute(select(Department).where(or_(Department.name == body.name, Department.code == body.code.upper())))).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "A department with that name or code already exists")
    d = Department(name=body.name, code=body.code.upper())
    db.add(d)
    await db.flush()
    await audit(db, "department.create", actor=user, target_type="department", target_id=d.id, detail=body.model_dump(), request=request)
    await db.commit()
    return DepartmentOut(id=d.id, name=d.name, code=d.code, employee_count=0)


@router.patch("/departments/{dep_id}", response_model=DepartmentOut)
async def update_department(dep_id: str, body: DepartmentIn, request: Request, db: AsyncSession = Depends(get_db), user=Depends(require_admin)):
    d = await db.get(Department, dep_id)
    if not d:
        raise HTTPException(404, "Department not found")
    d.name, d.code = body.name, body.code.upper()
    await audit(db, "department.update", actor=user, target_type="department", target_id=d.id, detail=body.model_dump(), request=request)
    await db.commit()
    count = (await db.execute(select(func.count(Employee.id)).where(Employee.department_id == d.id))).scalar_one()
    return DepartmentOut(id=d.id, name=d.name, code=d.code, employee_count=count)


@router.delete("/departments/{dep_id}", status_code=204)
async def delete_department(dep_id: str, request: Request, db: AsyncSession = Depends(get_db), user=Depends(require_admin)):
    d = await db.get(Department, dep_id)
    if not d:
        raise HTTPException(404, "Department not found")
    await audit(db, "department.delete", actor=user, target_type="department", target_id=d.id, detail={"name": d.name}, request=request)
    await db.delete(d)
    await db.commit()
    return Response(status_code=204)


# ---- employees ----------------------------------------------------------------------------
@router.get("/employees", response_model=Page[EmployeeOut])
async def list_employees(
    q: str | None = None,
    department_id: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    enrolled: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_staff),
):
    stmt = select(Employee).options(selectinload(Employee.department), selectinload(Employee.account))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Employee.first_name).like(like), func.lower(Employee.last_name).like(like), func.lower(Employee.email).like(like), func.lower(Employee.employee_code).like(like)))
    if department_id:
        stmt = stmt.where(Employee.department_id == department_id)
    if status_:
        stmt = stmt.where(Employee.status == EmployeeStatus(status_))
    if enrolled is not None:
        sub = select(BiometricEnrolment.employee_id).where(BiometricEnrolment.status == EnrolmentStatus.active)
        stmt = stmt.where(Employee.id.in_(sub) if enrolled else Employee.id.not_in(sub))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(Employee.last_name, Employee.first_name).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    enrol = await _enrolment_map(db, [r.id for r in rows])
    return Page(items=[_out(r, enrol.get(r.id)) for r in rows], total=total, page=page, page_size=page_size)


async def _load(db: AsyncSession, emp_id: str) -> Employee:
    e = (await db.execute(select(Employee).options(selectinload(Employee.department), selectinload(Employee.account)).where(Employee.id == emp_id))).scalar_one_or_none()
    if not e:
        raise HTTPException(404, "Employee not found")
    return e


@router.get("/employees/{emp_id}", response_model=EmployeeOut)
async def get_employee(emp_id: str, db: AsyncSession = Depends(get_db), _=Depends(require_staff)):
    e = await _load(db, emp_id)
    return _out(e, (await _enrolment_map(db, [e.id])).get(e.id))


@router.post("/employees", response_model=EmployeeOut, status_code=201)
async def create_employee(body: EmployeeIn, request: Request, db: AsyncSession = Depends(get_db), user=Depends(require_staff)):
    dup = (await db.execute(select(Employee).where(or_(Employee.email == body.email.lower(), Employee.employee_code == body.employee_code)))).first()
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "An employee with that email or code already exists")
    e = Employee(**{**body.model_dump(), "email": body.email.lower()})
    db.add(e)
    await db.flush()
    await audit(db, "employee.create", actor=user, target_type="employee", target_id=e.id, detail={"code": e.employee_code, "email": e.email}, request=request)
    await db.commit()
    return _out(await _load(db, e.id), None)


@router.patch("/employees/{emp_id}", response_model=EmployeeOut)
async def update_employee(emp_id: str, body: EmployeeUpdate, request: Request, db: AsyncSession = Depends(get_db), user=Depends(require_staff)):
    e = await _load(db, emp_id)
    changes = body.model_dump(exclude_unset=True)
    before = {k: getattr(e, k).value if k == "status" else getattr(e, k) for k in changes}
    for k, v in changes.items():
        if k == "status":
            v = EmployeeStatus(v)
        if k == "email" and v:
            v = v.lower()
        setattr(e, k, v)
    await audit(db, "employee.update", actor=user, target_type="employee", target_id=e.id, detail={"before": before, "after": changes}, request=request)
    await db.commit()
    if "status" in changes:
        from app.services.index import rebuild_index  # inactive employees must leave the match index

        await rebuild_index(db)
    return _out(await _load(db, e.id), (await _enrolment_map(db, [e.id])).get(e.id))


@router.post("/employees/{emp_id}/pin", status_code=204)
async def set_pin(emp_id: str, body: PinIn, request: Request, db: AsyncSession = Depends(get_db), user=Depends(require_admin)):
    e = await _load(db, emp_id)
    e.pin_salt = secrets.token_hex(8)
    e.pin_hash = hash_pin(body.pin, e.pin_salt)
    e.pin_fallback_enabled = True
    await audit(db, "employee.pin_enabled", actor=user, target_type="employee", target_id=e.id, request=request)
    await db.commit()
    return Response(status_code=204)


@router.delete("/employees/{emp_id}/pin", status_code=204)
async def clear_pin(emp_id: str, request: Request, db: AsyncSession = Depends(get_db), user=Depends(require_admin)):
    e = await _load(db, emp_id)
    e.pin_salt = e.pin_hash = None
    e.pin_fallback_enabled = False
    await audit(db, "employee.pin_disabled", actor=user, target_type="employee", target_id=e.id, request=request)
    await db.commit()
    return Response(status_code=204)


@router.post("/employees/{emp_id}/account", status_code=201)
async def create_account(emp_id: str, body: AccountCreateIn, request: Request, db: AsyncSession = Depends(get_db), user=Depends(require_admin)):
    e = await _load(db, emp_id)
    if e.account:
        raise HTTPException(status.HTTP_409_CONFLICT, "This employee already has a login account")
    if (await db.execute(select(UserAccount).where(UserAccount.email == e.email))).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    role = Role(body.role)
    acc = UserAccount(email=e.email, password_hash=hash_password(body.password), role=role, employee_id=e.id)
    db.add(acc)
    await db.flush()
    await audit(db, "account.create", actor=user, target_type="user", target_id=acc.id, detail={"email": acc.email, "role": role.value}, request=request)
    await db.commit()
    return {"id": acc.id, "email": acc.email, "role": role.value}


@router.delete("/employees/{emp_id}/biometrics", status_code=200)
async def delete_biometrics(emp_id: str, request: Request, purge: bool = False, db: AsyncSession = Depends(get_db), user=Depends(require_admin)):
    e = await _load(db, emp_id)
    n = await purge_biometrics(db, e.id) if purge else await revoke_enrolments(db, e.id)
    await audit(db, "biometrics.purge" if purge else "biometrics.revoke", actor=user, target_type="employee", target_id=e.id, detail={"count": n}, request=request)
    await db.commit()
    return {"removed": n, "purged": purge}


@router.get("/employees/{emp_id}/enrolments")
async def enrolment_history(emp_id: str, db: AsyncSession = Depends(get_db), _=Depends(require_staff)):
    rows = (await db.execute(select(BiometricEnrolment).where(BiometricEnrolment.employee_id == emp_id).order_by(BiometricEnrolment.created_at.desc()))).scalars().all()
    return [
        {"id": r.id, "status": r.status.value, "created_at": r.created_at, "revoked_at": r.revoked_at, "template_count": r.template_count,
         "quality_score": r.quality_score, "liveness_score": r.liveness_score, "consent_version": r.consent_version, "model_version": r.model_version,
         "created_by": r.created_by, "has_thumbnail": r.thumbnail_jpeg is not None}
        for r in rows
    ]


@router.get("/employees/{emp_id}/thumbnail")
async def enrolment_thumbnail(emp_id: str, db: AsyncSession = Depends(get_db), _=Depends(require_staff)):
    r = (await db.execute(select(BiometricEnrolment).where(BiometricEnrolment.employee_id == emp_id, BiometricEnrolment.status == EnrolmentStatus.active))).scalar_one_or_none()
    if not r or not r.thumbnail_jpeg:
        raise HTTPException(404, "No thumbnail")
    return Response(content=r.thumbnail_jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})
