"""Create the first administrator, sample departments and employees (no biometrics).

    .venv/Scripts/python tools/seed.py --admin-email admin@example.com --admin-password 'ChangeMe-Now-2026'
    .venv/Scripts/python tools/seed.py --demo        # also adds 12 demo employees across 4 departments
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.db.models import Department, Employee, Role, UserAccount  # noqa: E402

DEMO_DEPS = [("Engineering", "ENG"), ("Operations", "OPS"), ("Sales", "SAL"), ("People & Culture", "HR")]
DEMO_EMPLOYEES = [
    ("E1001", "Amara", "Okafor", "ENG", "Software Engineer"), ("E1002", "Liam", "Chen", "ENG", "Platform Engineer"),
    ("E1003", "Sofia", "Rossi", "ENG", "QA Analyst"), ("E1004", "Noah", "Patel", "OPS", "Operations Lead"),
    ("E1005", "Zara", "Hussain", "OPS", "Facilities Coordinator"), ("E1006", "Ethan", "Murphy", "SAL", "Account Executive"),
    ("E1007", "Mei", "Tanaka", "SAL", "Sales Development Rep"), ("E1008", "Lucas", "Silva", "SAL", "Account Manager"),
    ("E1009", "Priya", "Nair", "HR", "People Partner"), ("E1010", "Oliver", "Brown", "HR", "Talent Acquisition"),
    ("E1011", "Hana", "Kim", "ENG", "Data Engineer"), ("E1012", "Diego", "Martinez", "OPS", "Security Officer"),
]


async def main(args: argparse.Namespace) -> None:
    async with SessionLocal() as db:
        existing = (await db.execute(select(UserAccount).where(UserAccount.email == args.admin_email.lower()))).scalar_one_or_none()
        if existing is None:
            db.add(UserAccount(email=args.admin_email.lower(), password_hash=hash_password(args.admin_password), role=Role.admin))
            print(f"created admin {args.admin_email}")
        else:
            print("admin already exists")
        if args.demo:
            deps = {d.code: d for d in (await db.execute(select(Department))).scalars()}
            for name, code in DEMO_DEPS:
                if code not in deps:
                    d = Department(name=name, code=code)
                    db.add(d)
                    deps[code] = d
            await db.flush()
            codes = {e.employee_code for e in (await db.execute(select(Employee))).scalars()}
            n = 0
            for code, fn, ln, dep, title in DEMO_EMPLOYEES:
                if code in codes:
                    continue
                db.add(Employee(employee_code=code, first_name=fn, last_name=ln, email=f"{fn}.{ln}@example.com".lower(), job_title=title, department_id=deps[dep].id))
                n += 1
            print(f"added {n} demo employees")
        await db.commit()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--admin-email", default="admin@facegate.local")
    p.add_argument("--admin-password", default="Admin-Password-2026!")
    p.add_argument("--demo", action="store_true")
    asyncio.run(main(p.parse_args()))
