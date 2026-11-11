"""Create the first administrator, sample departments and employees (no biometrics).

    .venv/Scripts/python tools/seed.py                      # default admin: username 'admin', password 'Welcome123'
    .venv/Scripts/python tools/seed.py --admin-username ops --admin-email ops@example.com --admin-password 'ChangeMe-Now-2026'
    .venv/Scripts/python tools/seed.py --demo        # also adds 12 demo employees across 4 departments
    .venv/Scripts/python tools/seed.py --employee-logins   # portal login for every active employee without one:
                                                           # username = employee code (lower case), password Welcome123
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.db.models import Department, Employee, EmployeeStatus, Role, UserAccount  # noqa: E402

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
        existing = (await db.execute(select(UserAccount).where((UserAccount.email == args.admin_email.lower()) | (UserAccount.username == args.admin_username.lower())))).scalar_one_or_none()
        if existing is None:
            db.add(UserAccount(email=args.admin_email.lower(), username=args.admin_username.lower(), password_hash=hash_password(args.admin_password), role=Role.admin))
            print(f"created admin username={args.admin_username} email={args.admin_email}")
        else:
            existing.username = existing.username or args.admin_username.lower()
            if args.reset_password:
                existing.password_hash = hash_password(args.admin_password)
                print("admin password reset")
            print(f"admin already exists (username={existing.username})")
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
        if args.employee_logins:
            # Test / first-run convenience: every active employee without a login gets one. Same rule as the admin
            # console's "Create account": username = lower-cased employee code, role employee, email = the employee's.
            await db.flush()
            emps = (await db.execute(select(Employee).options(selectinload(Employee.account)))).scalars().all()
            accounts = (await db.execute(select(UserAccount))).scalars().all()
            taken_emails = {u.email for u in accounts}
            taken_names = {u.username for u in accounts if u.username}
            m = 0
            for e in emps:
                if e.account is not None or e.status != EmployeeStatus.active:
                    continue
                uname = e.employee_code.lower()
                email = (e.email or f"{uname}@facegate.local").lower()
                if email in taken_emails:
                    email = f"{uname}@facegate.local"
                if uname in taken_names or email in taken_emails:
                    print(f"skipped {e.employee_code}: username or email already taken")
                    continue
                db.add(UserAccount(email=email, username=uname, password_hash=hash_password(args.employee_password), role=Role.employee, employee_id=e.id))
                taken_emails.add(email)
                taken_names.add(uname)
                m += 1
            print(f"created {m} employee logins (username = employee code in lower case, password '{args.employee_password}')")
        await db.commit()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--admin-username", default="admin")
    p.add_argument("--admin-email", default="admin@facegate.local")
    p.add_argument("--admin-password", default="Welcome123")
    p.add_argument("--reset-password", action="store_true", help="overwrite the existing admin's password")
    p.add_argument("--demo", action="store_true")
    p.add_argument("--employee-logins", action="store_true", help="create a portal login for every active employee that has none")
    p.add_argument("--employee-password", default="Welcome123")
    asyncio.run(main(p.parse_args()))
