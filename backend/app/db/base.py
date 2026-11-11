from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {}
    # Sized for a sign-in rush: a login holds its connection while Argon2 runs (~15-50 ms), and the kiosk stream
    # writes an attempt per session. Postgres's default max_connections is 100; keep pool + overflow under it.
    return {"pool_pre_ping": True, "pool_size": 20, "max_overflow": 40, "pool_timeout": 60}


engine = create_async_engine(settings.database_url, **_engine_kwargs(settings.database_url))
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
