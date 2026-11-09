from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.crypto import decrypt_str, encrypt_str
from app.core.deps import ACCESS_COOKIE, REFRESH_COOKIE, get_current_user
from app.core.rate_limit import client_ip, limit, login_limiter
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh,
    new_refresh_token,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.db.base import get_db
from app.db.models import Employee, RefreshSession, UserAccount
from app.schemas.common import LoginIn, MfaConfirmIn, MfaSetupOut, PasswordChangeIn, UserOut
from app.services.audit import audit

router = APIRouter(prefix="/auth", tags=["auth"])
_DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=2$c29tZXNhbHRzb21lc2FsdA$Zb0mN1qg1xO4dG1cQ7m0GZ2m7T8bK3m0y2Q4m8q9p1k"


def set_auth_cookies(resp: Response, access: str, refresh: str | None = None) -> None:
    common = {"httponly": True, "secure": settings.cookie_secure, "samesite": "strict", "domain": settings.cookie_domain, "path": "/"}
    resp.set_cookie(ACCESS_COOKIE, access, max_age=settings.access_token_minutes * 60, **common)
    if refresh:
        resp.set_cookie(REFRESH_COOKIE, refresh, max_age=settings.refresh_token_days * 86400, **{**common, "path": f"{settings.api_prefix}/auth"})


def _clear_cookies(resp: Response) -> None:
    resp.delete_cookie(ACCESS_COOKIE, path="/", domain=settings.cookie_domain)
    resp.delete_cookie(REFRESH_COOKIE, path=f"{settings.api_prefix}/auth", domain=settings.cookie_domain)


async def _user_out(db: AsyncSession, user: UserAccount) -> UserOut:
    name = None
    if user.employee_id:
        emp = await db.get(Employee, user.employee_id)
        name = emp.full_name if emp else None
    return UserOut(id=user.id, email=user.email, username=user.username, role=user.role.value, mfa_enabled=user.mfa_enabled, employee_id=user.employee_id, employee_name=name)


@router.post("/login", response_model=UserOut, dependencies=[Depends(limit(login_limiter))])
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ident = (body.identifier or body.email or "").strip().lower()
    if not ident:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Email or username is required")
    user = (await db.execute(select(UserAccount).where(or_(UserAccount.email == ident, UserAccount.username == ident)))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    generic = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username/email or password")
    if user is None:
        verify_password(body.password, _DUMMY_HASH)  # keep timing similar for unknown emails
        raise generic
    if user.locked_until and user.locked_until > now:
        raise HTTPException(status.HTTP_423_LOCKED, f"Account locked. Try again after {user.locked_until.strftime('%H:%M UTC')}.")
    if not user.is_active or not verify_password(body.password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= settings.login_max_attempts:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_logins = 0
            await audit(db, "auth.lockout", actor=user, request=request)
        await audit(db, "auth.login_failed", actor=user, request=request)
        await db.commit()
        raise generic

    if user.mfa_enabled:
        if not body.totp_code:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA code required", headers={"X-MFA-Required": "1"})
        if not verify_totp(decrypt_str(user.totp_secret_enc or ""), body.totp_code):
            user.failed_logins += 1
            await audit(db, "auth.mfa_failed", actor=user, request=request)
            await db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MFA code", headers={"X-MFA-Required": "1"})

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    raw, h = new_refresh_token()
    db.add(RefreshSession(user_id=user.id, token_hash=h, expires_at=now + timedelta(days=settings.refresh_token_days),
                          user_agent=(request.headers.get("user-agent") or "")[:255], ip=client_ip(request)))
    await audit(db, "auth.login", actor=user, request=request)
    await db.commit()
    set_auth_cookies(response, create_access_token(user.id, user.role.value, True), raw)
    return await _user_out(db, user)


@router.post("/refresh", response_model=UserOut)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No session")
    sess = (await db.execute(select(RefreshSession).where(RefreshSession.token_hash == hash_refresh(raw)))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if sess is None or sess.revoked_at or sess.expires_at < now:
        _clear_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = await db.get(UserAccount, sess.user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account unavailable")
    sess.revoked_at = now  # rotate
    new_raw, new_hash = new_refresh_token()
    db.add(RefreshSession(user_id=user.id, token_hash=new_hash, expires_at=now + timedelta(days=settings.refresh_token_days),
                          user_agent=sess.user_agent, ip=client_ip(request)))
    await db.commit()
    set_auth_cookies(response, create_access_token(user.id, user.role.value, True), new_raw)
    return await _user_out(db, user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        sess = (await db.execute(select(RefreshSession).where(RefreshSession.token_hash == hash_refresh(raw)))).scalar_one_or_none()
        if sess:
            sess.revoked_at = datetime.now(timezone.utc)
            await db.commit()
    _clear_cookies(response)
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
async def me(user: UserAccount = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _user_out(db, user)


@router.post("/password", status_code=204)
async def change_password(body: PasswordChangeIn, request: Request, user: UserAccount = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    await audit(db, "auth.password_changed", actor=user, request=request)
    await db.commit()
    return Response(status_code=204)


@router.post("/mfa/setup", response_model=MfaSetupOut)
async def mfa_setup(user: UserAccount = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    secret = new_totp_secret()
    user.totp_secret_enc = encrypt_str(secret)  # pending until confirmed
    await db.commit()
    uri = totp_uri(secret, user.email)
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=6)
    buf = io.BytesIO()
    img.save(buf)
    return MfaSetupOut(secret=secret, otpauth_uri=uri, qr_svg=buf.getvalue().decode())


@router.post("/mfa/confirm", response_model=UserOut)
async def mfa_confirm(body: MfaConfirmIn, request: Request, user: UserAccount = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user.totp_secret_enc or not verify_totp(decrypt_str(user.totp_secret_enc), body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code — check your authenticator app and try again")
    user.mfa_enabled = True
    await audit(db, "auth.mfa_enabled", actor=user, request=request)
    await db.commit()
    return await _user_out(db, user)


@router.post("/mfa/disable", response_model=UserOut)
async def mfa_disable(body: MfaConfirmIn, request: Request, user: UserAccount = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user.mfa_enabled or not verify_totp(decrypt_str(user.totp_secret_enc or ""), body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code")
    user.mfa_enabled = False
    user.totp_secret_enc = None
    await audit(db, "auth.mfa_disabled", actor=user, request=request)
    await db.commit()
    return await _user_out(db, user)
