"""FastAPI dependencies: current user resolution and role enforcement (server-side RBAC)."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.base import get_db
from app.db.models import Role, UserAccount

ACCESS_COOKIE = "fg_access"
REFRESH_COOKIE = "fg_refresh"


def _token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(ACCESS_COOKIE)


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> UserAccount:
    token = _token_from_request(request)
    payload = decode_token(token, "access") if token else None
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = await db.get(UserAccount, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account unavailable")
    if user.mfa_enabled and not payload.get("mfa"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA required")
    request.state.user = user
    return user


def require_role(*roles: Role) -> Callable:
    async def _dep(user: UserAccount = Depends(get_current_user)) -> UserAccount:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return _dep


require_admin = require_role(Role.admin)
require_staff = require_role(Role.admin, Role.hr)
require_any = require_role(Role.admin, Role.hr, Role.employee)
