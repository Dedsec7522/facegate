from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import client_ip
from app.db.models import AuditLog, UserAccount


async def audit(
    db: AsyncSession,
    action: str,
    *,
    actor: UserAccount | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            ip=client_ip(request) if request else None,
        )
    )
