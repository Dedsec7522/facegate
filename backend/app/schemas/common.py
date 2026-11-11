from __future__ import annotations

from datetime import date, datetime
from typing import Generic, TypeVar

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Plain pattern rather than EmailStr: internal corporate domains such as .local must be accepted.
EmailStr = Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=255)]

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# ---- auth -------------------------------------------------------------------------------
class LoginIn(BaseModel):
    identifier: str | None = Field(default=None, max_length=255)  # email or username
    email: str | None = Field(default=None, max_length=255)  # legacy alias
    password: str = Field(min_length=8, max_length=128)
    totp_code: str | None = Field(default=None, max_length=8)


class UserOut(ORM):
    id: str
    email: str
    username: str | None = None
    role: str
    mfa_enabled: bool
    employee_id: str | None = None
    employee_name: str | None = None


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class MfaConfirmIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


# ---- org ---------------------------------------------------------------------------------
class DepartmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    code: str = Field(min_length=1, max_length=20)


class DepartmentOut(ORM):
    id: str
    name: str
    code: str
    employee_count: int = 0


class EmployeeIn(BaseModel):
    employee_code: str = Field(min_length=1, max_length=32)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    job_title: str | None = Field(default=None, max_length=120)
    department_id: str | None = None
    timezone: str | None = None


class EmployeeUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=80)
    last_name: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None
    job_title: str | None = Field(default=None, max_length=120)
    department_id: str | None = None
    status: str | None = None
    timezone: str | None = None


class EmployeeOut(ORM):
    id: str
    employee_code: str
    first_name: str
    last_name: str
    email: str
    job_title: str | None
    department_id: str | None
    department_name: str | None = None
    status: str
    pin_fallback_enabled: bool
    enrolled: bool = False
    enrolment_at: datetime | None = None
    has_account: bool = False
    created_at: datetime


class PinIn(BaseModel):
    pin: str = Field(min_length=4, max_length=8, pattern=r"^\d+$")


class AccountCreateIn(BaseModel):
    password: str = Field(min_length=10, max_length=128)
    role: str = "employee"


# ---- attendance --------------------------------------------------------------------------
class AttendanceEventIn(BaseModel):
    token: str
    action: str  # check_in | check_out
    device_label: str | None = Field(default=None, max_length=80)
    open_portal: bool = False  # also sign the employee's own account in (short, refresh-less session) so the kiosk can open their dashboard


class PortalSessionOut(BaseModel):
    role: str
    expires_in_minutes: int


class PinAttendanceIn(BaseModel):
    employee_code: str
    pin: str = Field(min_length=4, max_length=8)
    action: str
    device_label: str | None = None


class AttendanceEventOut(ORM):
    id: str
    employee_id: str
    employee_name: str | None = None
    employee_code: str | None = None
    department_name: str | None = None
    action: str
    method: str
    occurred_at: datetime
    attendance_date: date
    match_score: float | None
    liveness_score: float | None
    voided: bool
    portal_session: PortalSessionOut | None = None  # set only when the request asked for one and the account qualifies


class AttendanceDayOut(ORM):
    id: str
    employee_id: str
    employee_name: str | None = None
    employee_code: str | None = None
    department_name: str | None = None
    attendance_date: date
    first_in: datetime | None
    last_out: datetime | None
    worked_minutes: int
    late_minutes: int
    early_leave_minutes: int
    status: str
    is_open: bool


class CorrectionIn(BaseModel):
    employee_id: str
    kind: str  # add | void | adjust | leave | clear_leave
    reason: str = Field(min_length=5, max_length=500)
    event_id: str | None = None
    action: str | None = None
    occurred_at: datetime | None = None


class CorrectionOut(ORM):
    id: str
    employee_id: str
    attendance_date: date | None
    event_id: str | None
    kind: str
    before: dict | None
    after: dict | None
    reason: str
    created_by: str
    created_at: datetime


class SettingsPatch(BaseModel):
    timezone: str | None = None
    day_start: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    work_start: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    work_end: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    late_grace_minutes: int | None = Field(default=None, ge=0, le=180)
    duplicate_scan_seconds: int | None = Field(default=None, ge=0, le=3600)
    auto_close_after_hours: int | None = Field(default=None, ge=1, le=48)
    relogin_cooldown_hours: int | None = Field(default=None, ge=0, le=48)
    match_accept_threshold: float | None = Field(default=None, ge=0.2, le=0.9)
    pad_live_threshold: float | None = Field(default=None, ge=0.3, le=0.99)
    require_challenge: bool | None = None
    kiosk_liveness: str | None = Field(default=None, pattern=r"^(advisory|passive|strict)$")
    portal_liveness: str | None = Field(default=None, pattern=r"^(advisory|passive|strict)$")
    adaptive_templates: bool | None = None
    consent_version: str | None = None
