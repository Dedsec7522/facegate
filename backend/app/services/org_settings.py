"""Organisation-level attendance settings: DB row `app_settings['attendance']` overrides config defaults."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AppSetting

KEY = "attendance"


@dataclass(slots=True)
class OrgSettings:
    timezone: str
    day_start: str
    work_start: str
    work_end: str
    late_grace_minutes: int
    duplicate_scan_seconds: int
    auto_close_after_hours: int
    match_accept_threshold: float
    pad_live_threshold: float
    require_challenge: bool
    kiosk_liveness: str  # advisory | passive | strict
    portal_liveness: str  # advisory | passive | strict
    adaptive_templates: bool
    consent_version: str

    def t(self, field: str) -> time:
        hh, mm = getattr(self, field).split(":")
        return time(int(hh), int(mm))


def defaults() -> OrgSettings:
    return OrgSettings(
        timezone=settings.org_timezone,
        day_start=settings.day_start,
        work_start=settings.work_start,
        work_end=settings.work_end,
        late_grace_minutes=settings.late_grace_minutes,
        duplicate_scan_seconds=settings.duplicate_scan_seconds,
        auto_close_after_hours=settings.auto_close_after_hours,
        match_accept_threshold=settings.match_accept_threshold,
        pad_live_threshold=settings.pad_live_threshold,
        require_challenge=False,
        kiosk_liveness="advisory",  # instant by default; switch to passive/strict in Settings for anti-spoof gating
        portal_liveness="advisory",  # signed-in 1:1: identify instantly; PAD is logged, a frozen stream is still rejected
        adaptive_templates=True,
        consent_version="2026-11",
    )


async def get_org_settings(db: AsyncSession) -> OrgSettings:
    base = defaults()
    row = await db.get(AppSetting, KEY)
    if row and isinstance(row.value, dict):
        for k, v in row.value.items():
            if hasattr(base, k) and v is not None:
                setattr(base, k, v)
    return base


async def update_org_settings(db: AsyncSession, patch: dict, updated_by: str | None) -> OrgSettings:
    current = await get_org_settings(db)
    for k, v in patch.items():
        if hasattr(current, k) and v is not None:
            setattr(current, k, v)
    row = await db.get(AppSetting, KEY)
    if row is None:
        row = AppSetting(key=KEY, value=asdict(current), updated_by=updated_by)
        db.add(row)
    else:
        row.value = asdict(current)
        row.updated_by = updated_by
    await db.flush()
    return current
