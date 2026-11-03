"""Test fixtures: an isolated SQLite database per test session, an app client, and helpers."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_facegate.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-test-secret-key-test-secret-key"
os.environ["TEMPLATE_KEY"] = "dGVzdC10ZW1wbGF0ZS1rZXktMzItYnl0ZXMtbG9uZyEhISE="

import asyncio  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db import models  # noqa: E402,F401
from app.db.base import Base, SessionLocal, engine  # noqa: E402
from app.db.models import Department, Employee, Role, UserAccount  # noqa: E402

DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        dep = Department(name="Engineering", code="ENG")
        db.add(dep)
        await db.flush()
        db.add(UserAccount(email="admin@test.local", password_hash=hash_password("Admin-Pass-1234"), role=Role.admin))
        emp = Employee(employee_code="E1", first_name="Test", last_name="Person", email="test.person@test.local", department_id=dep.id)
        db.add(emp)
        await db.flush()
        db.add(UserAccount(email=emp.email, password_hash=hash_password("Employee-Pass-1234"), role=Role.employee, employee_id=emp.id))
        await db.commit()
    yield
    await engine.dispose()
    try:
        os.remove("test_facegate.db")
    except OSError:
        pass


@pytest_asyncio.fixture
async def db():
    async with SessionLocal() as s:
        yield s
        await s.rollback()


@pytest_asyncio.fixture
async def client():
    from app.core.rate_limit import login_limiter
    from app.main import app

    login_limiter._hits.clear()  # every test starts with a fresh login budget (ASGI test client has no stable IP)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def admin_client(client: AsyncClient):
    r = await client.post("/api/v1/auth/login", json={"email": "admin@test.local", "password": "Admin-Pass-1234"})
    assert r.status_code == 200, r.text
    return client
