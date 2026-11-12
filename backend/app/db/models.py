"""FaceGate data model. All timestamps are timezone-aware UTC."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    from datetime import timezone

    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    admin = "admin"
    hr = "hr"
    employee = "employee"


class EmployeeStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"


class EnrolmentStatus(str, enum.Enum):
    active = "active"
    superseded = "superseded"
    revoked = "revoked"


class AttendanceAction(str, enum.Enum):
    check_in = "check_in"
    check_out = "check_out"


class AttendanceMethod(str, enum.Enum):
    face = "face"
    pin = "pin"
    manual = "manual"


class VerificationOutcome(str, enum.Enum):
    identified = "identified"
    unknown = "unknown"
    ambiguous = "ambiguous"
    spoof = "spoof"
    challenge_failed = "challenge_failed"
    no_face = "no_face"
    multiple_faces = "multiple_faces"
    timeout = "timeout"
    quality = "quality"


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    employees: Mapped[list["Employee"]] = relationship(back_populates="department")


class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    employee_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    job_title: Mapped[str | None] = mapped_column(String(120))
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"))
    status: Mapped[EmployeeStatus] = mapped_column(Enum(EmployeeStatus), default=EmployeeStatus.active)
    pin_fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    pin_salt: Mapped[str | None] = mapped_column(String(32))
    timezone: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    department: Mapped[Department | None] = relationship(back_populates="employees")
    enrolments: Mapped[list["BiometricEnrolment"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    account: Mapped["UserAccount | None"] = relationship(back_populates="employee", uselist=False)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class UserAccount(Base):
    __tablename__ = "user_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.employee)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    employee_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), unique=True)
    totp_secret_enc: Mapped[str | None] = mapped_column(String(512))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    employee: Mapped[Employee | None] = relationship(back_populates="account")
    refresh_sessions: Mapped[list["RefreshSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("user_accounts.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[UserAccount] = relationship(back_populates="refresh_sessions")


class BiometricEnrolment(Base):
    __tablename__ = "biometric_enrolments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    status: Mapped[EnrolmentStatus] = mapped_column(Enum(EnrolmentStatus), default=EnrolmentStatus.active)
    consent_version: Mapped[str] = mapped_column(String(32))
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("user_accounts.id", ondelete="SET NULL"))
    quality_score: Mapped[float | None] = mapped_column(Float)
    liveness_score: Mapped[float | None] = mapped_column(Float)
    template_count: Mapped[int] = mapped_column(Integer, default=0)
    thumbnail_jpeg: Mapped[bytes | None] = mapped_column(LargeBinary)  # small aligned face, optional
    model_version: Mapped[str] = mapped_column(String(64), default="sface-2021dec")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    employee: Mapped[Employee] = relationship(back_populates="enrolments")
    templates: Mapped[list["FaceTemplate"]] = relationship(back_populates="enrolment", cascade="all, delete-orphan")


class FaceTemplate(Base):
    __tablename__ = "face_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    enrolment_id: Mapped[str] = mapped_column(ForeignKey("biometric_enrolments.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    pose: Mapped[str] = mapped_column(String(16))  # front | left | right | up | down
    embedding_enc: Mapped[bytes] = mapped_column(LargeBinary)  # AES-GCM(float32[dim]), dim 256 for intel-fr-0095 / 128 for sface; aad = template id
    quality: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    enrolment: Mapped[BiometricEnrolment] = relationship(back_populates="templates")


class VerificationAttempt(Base):
    __tablename__ = "verification_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    purpose: Mapped[str] = mapped_column(String(16), default="attendance")  # attendance | enrolment
    outcome: Mapped[VerificationOutcome] = mapped_column(Enum(VerificationOutcome))
    employee_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"), index=True)
    match_score: Mapped[float | None] = mapped_column(Float)
    second_score: Mapped[float | None] = mapped_column(Float)
    liveness_score: Mapped[float | None] = mapped_column(Float)
    challenge: Mapped[str | None] = mapped_column(String(32))
    frames: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AttendanceEvent(Base):
    """Immutable event log. Corrections live in attendance_corrections and never mutate rows here."""

    __tablename__ = "attendance_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    action: Mapped[AttendanceAction] = mapped_column(Enum(AttendanceAction))
    method: Mapped[AttendanceMethod] = mapped_column(Enum(AttendanceMethod))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    attendance_date: Mapped[datetime] = mapped_column(Date, index=True)  # org-local attendance day
    verification_attempt_id: Mapped[str | None] = mapped_column(ForeignKey("verification_attempts.id", ondelete="SET NULL"))
    match_score: Mapped[float | None] = mapped_column(Float)
    liveness_score: Mapped[float | None] = mapped_column(Float)
    device_label: Mapped[str | None] = mapped_column(String(80))
    ip: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("user_accounts.id", ondelete="SET NULL"))  # manual only
    voided: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_att_emp_date", "employee_id", "attendance_date"),)


class AttendanceDay(Base):
    """Derived daily summary, recomputed by the engine after every event or correction."""

    __tablename__ = "attendance_days"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    attendance_date: Mapped[datetime] = mapped_column(Date, index=True)
    first_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worked_minutes: Mapped[int] = mapped_column(Integer, default=0)
    late_minutes: Mapped[int] = mapped_column(Integer, default=0)
    early_leave_minutes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="present")  # present | late | missing_checkout | absent | corrected
    is_open: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("employee_id", "attendance_date", name="uq_att_day"),)


class AttendanceCorrection(Base):
    __tablename__ = "attendance_corrections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    attendance_date: Mapped[datetime] = mapped_column(Date, index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("attendance_events.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))  # add | void | adjust
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("user_accounts.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(36), index=True)
    detail: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_by: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now())
