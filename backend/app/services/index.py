"""Loads active, decrypted face templates from the DB into the in-memory TemplateIndex."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_embedding
from app.db.models import BiometricEnrolment, Employee, EmployeeStatus, EnrolmentStatus, FaceTemplate
from app.vision.pipeline import get_pipeline


async def rebuild_index(db: AsyncSession) -> int:
    stmt = (
        select(FaceTemplate.id, FaceTemplate.employee_id, FaceTemplate.embedding_enc)
        .join(BiometricEnrolment, BiometricEnrolment.id == FaceTemplate.enrolment_id)
        .join(Employee, Employee.id == FaceTemplate.employee_id)
        .where(BiometricEnrolment.status == EnrolmentStatus.active, Employee.status == EmployeeStatus.active)
    )
    rows = []
    for tid, emp_id, blob in (await db.execute(stmt)).all():
        try:
            rows.append((emp_id, decrypt_embedding(blob, tid)))
        except Exception:  # wrong key or corrupted row — skip rather than crash the service
            continue
    get_pipeline().index.load(rows)
    return len(rows)
