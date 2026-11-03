"""Persisting a completed enrolment capture: duplicate check, encryption, supersede, audit, index refresh."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import encrypt_embedding
from app.db.models import BiometricEnrolment, Employee, EnrolmentStatus, FaceTemplate, new_id
from app.services.index import rebuild_index
from app.services.verification import Session
from app.vision.embedder import MODEL_VERSION, normalize
from app.vision.pipeline import encode_jpeg, get_pipeline


class EnrolmentError(Exception):
    def __init__(self, code: str, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.detail = code, message, detail or {}


async def commit_enrolment(db: AsyncSession, s: Session, *, employee: Employee, created_by: str | None, notes: str | None = None) -> BiometricEnrolment:
    if len(s.poses) < 3:
        raise EnrolmentError("incomplete", "At least three frontal samples must be captured before saving.")
    live_avg = float(np.median(s.live_probs)) if s.live_probs else 0.0
    if len(s.live_probs) < settings.pad_min_frames or live_avg < s.pad_threshold:
        raise EnrolmentError("liveness", f"Liveness during enrolment was too low ({live_avg:.2f}). Use the live camera.")

    embs = np.stack([e for e, _, _ in s.poses.values()])
    mean = normalize(embs.mean(axis=0))
    # Captured poses must describe the same person.
    if float((embs @ mean).min()) < 0.40:
        raise EnrolmentError("inconsistent", "The captured poses do not look like the same person. Please restart.")

    # Duplicate identity guard: compare against everyone *else* already enrolled.
    index = get_pipeline().index
    dups = [(e, sc) for e, sc in index.find_duplicates(mean) if e != employee.id]
    if dups:
        other = await db.get(Employee, dups[0][0])
        raise EnrolmentError(
            "duplicate_identity",
            "This face appears to be already enrolled for another employee.",
            {"employee_id": dups[0][0], "employee_name": other.full_name if other else None, "score": round(dups[0][1], 3)},
        )

    # Supersede prior active enrolments (re-enrolment keeps history, drops old templates from the index).
    await db.execute(
        update(BiometricEnrolment)
        .where(BiometricEnrolment.employee_id == employee.id, BiometricEnrolment.status == EnrolmentStatus.active)
        .values(status=EnrolmentStatus.superseded, revoked_at=datetime.now(timezone.utc))
    )
    front = s.poses.get("front") or next(iter(s.poses.values()))
    enrol = BiometricEnrolment(
        id=new_id(),
        employee_id=employee.id,
        status=EnrolmentStatus.active,
        consent_version=s.consent_version or "unknown",
        consent_at=datetime.now(timezone.utc),
        created_by=created_by,
        quality_score=float(np.mean([q for _, q, _ in s.poses.values()])),
        liveness_score=live_avg,
        template_count=len(s.poses),
        thumbnail_jpeg=encode_jpeg(front[2], 70) if settings.keep_enrol_thumbnail else None,
        model_version=MODEL_VERSION,
        notes=notes,
    )
    db.add(enrol)
    for pose, (emb, q, _) in s.poses.items():
        tid = new_id()
        db.add(FaceTemplate(id=tid, enrolment_id=enrol.id, employee_id=employee.id, pose=pose, embedding_enc=encrypt_embedding(emb, tid), quality=float(q)))
    await db.flush()
    await rebuild_index(db)
    return enrol


MAX_TEMPLATES_PER_EMPLOYEE = 10


async def add_adaptive_template(db: AsyncSession, employee_id: str, emb: np.ndarray, score: float) -> bool:
    """After a confident, live-verified identification, keep the session's embedding as an extra template
    so the model follows gradual appearance changes (beard, glasses, hairstyle). Bounded per employee;
    the oldest adaptive template is dropped first. Never touches the admin-captured enrolment samples."""
    enrol = (await db.execute(select(BiometricEnrolment).where(BiometricEnrolment.employee_id == employee_id, BiometricEnrolment.status == EnrolmentStatus.active))).scalar_one_or_none()
    if enrol is None:
        return False
    existing = (await db.execute(select(FaceTemplate).where(FaceTemplate.enrolment_id == enrol.id).order_by(FaceTemplate.created_at))).scalars().all()
    from app.core.crypto import decrypt_embedding

    for t in existing:  # skip if a near-identical adaptive template is already held (no information gain)
        if t.pose == "auto" and float(decrypt_embedding(t.embedding_enc, t.id) @ emb) > 0.92:
            return False
    autos = [t for t in existing if t.pose == "auto"]
    while len(existing) >= MAX_TEMPLATES_PER_EMPLOYEE and autos:
        oldest = autos.pop(0)
        existing.remove(oldest)
        await db.delete(oldest)
    tid = new_id()
    db.add(FaceTemplate(id=tid, enrolment_id=enrol.id, employee_id=employee_id, pose="auto", embedding_enc=encrypt_embedding(emb, tid), quality=float(score)))
    enrol.template_count = len(existing) + 1
    await db.flush()
    await rebuild_index(db)
    return True


async def revoke_enrolments(db: AsyncSession, employee_id: str) -> int:
    res = await db.execute(
        update(BiometricEnrolment)
        .where(BiometricEnrolment.employee_id == employee_id, BiometricEnrolment.status == EnrolmentStatus.active)
        .values(status=EnrolmentStatus.revoked, revoked_at=datetime.now(timezone.utc))
    )
    await db.flush()
    await rebuild_index(db)
    return res.rowcount or 0


async def purge_biometrics(db: AsyncSession, employee_id: str) -> int:
    """Hard-deletes all templates and thumbnails for an employee (retention / erasure requests)."""
    enrols = (await db.execute(select(BiometricEnrolment).where(BiometricEnrolment.employee_id == employee_id))).scalars().all()
    n = 0
    for e in enrols:
        n += len(e.templates)
        await db.delete(e)
    await db.flush()
    await rebuild_index(db)
    return n
