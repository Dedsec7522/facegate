from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.base import SessionLocal
from app.services.attendance import flag_missing_checkouts
from app.services.index import rebuild_index
from app.services.org_settings import get_org_settings
from app.vision.pipeline import get_pipeline

log = logging.getLogger("facegate")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def _housekeeping() -> None:
    while True:
        try:
            async with SessionLocal() as db:
                org = await get_org_settings(db)
                n = await flag_missing_checkouts(db, org)
                await db.commit()
                if n:
                    log.info("flagged %d missing check-outs", n)
        except Exception as e:  # keep the loop alive
            log.warning("housekeeping failed: %s", e)
        await asyncio.sleep(600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pipe = get_pipeline()  # loads models once
    async with SessionLocal() as db:
        n = await rebuild_index(db)
    log.info("vision ready: %d templates in index, %d workers", n, settings.inference_workers)
    task = asyncio.create_task(_housekeeping())
    yield
    task.cancel()
    pipe.executor.shutdown(wait=False)


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan, docs_url="/api/docs" if not settings.is_prod else None, redoc_url=None, openapi_url="/api/openapi.json" if not settings.is_prod else None)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
    resp.headers["Cache-Control"] = resp.headers.get("Cache-Control", "no-store")
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.get("/api/health")
async def health():
    pipe = get_pipeline()
    # The organisation time zone is public (not sensitive) so the anonymous kiosk can display organisation wall-clock
    # times whatever the device's own clock zone is set to.
    from app.db.base import SessionLocal
    from app.services.org_settings import get_org_settings

    tz = settings.org_timezone
    try:
        async with SessionLocal() as db:
            tz = (await get_org_settings(db)).timezone
    except Exception:  # noqa: BLE001 - health must answer even if the DB is down; the UI then uses the configured default
        pass
    return {"status": "ok", "index_templates": pipe.index.size, "environment": settings.environment, "timezone": tz}


app.include_router(api_router, prefix=settings.api_prefix)
