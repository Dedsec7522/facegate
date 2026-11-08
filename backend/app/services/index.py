"""Loads active, decrypted face templates from the DB into the in-memory TemplateIndex."""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_embedding
from app.db.models import BiometricEnrolment, Employee, EmployeeStatus, EnrolmentStatus, FaceTemplate
from app.vision.pipeline import get_pipeline

log = logging.getLogger("facegate")


async def rebuild_index(db: AsyncSession) -> int:
    version = get_pipeline().embedder.version
    # Embeddings from different models live in different spaces: only the running model's templates are usable.
    stale = (await db.execute(
        select(func.count(BiometricEnrolment.id))
        .join(Employee, Employee.id == BiometricEnrolment.employee_id)
        .where(BiometricEnrolment.status == EnrolmentStatus.active, Employee.status == EmployeeStatus.active,
               BiometricEnrolment.model_version != version)
    )).scalar_one()
    if stale:
        log.warning("%d active enrolment(s) were made with another face model than %s and must be re-enrolled", stale, version)
    stmt = (
        select(FaceTemplate.id, FaceTemplate.employee_id, FaceTemplate.embedding_enc)
        .join(BiometricEnrolment, BiometricEnrolment.id == FaceTemplate.enrolment_id)
        .join(Employee, Employee.id == FaceTemplate.employee_id)
        .where(BiometricEnrolment.status == EnrolmentStatus.active, Employee.status == EmployeeStatus.active,
               BiometricEnrolment.model_version == version)
    )
    rows = []
    for tid, emp_id, blob in (await db.execute(stmt)).all():
        try:
            rows.append((emp_id, decrypt_embedding(blob, tid)))
        except Exception:  # wrong key or corrupted row — skip rather than crash the service
            continue
    get_pipeline().index.load(rows)
    return len(rows)
