"""Isolated test environment: its own PostgreSQL database and its own API process (unmodified application code).

    python tools/env.py init        create the test database, run the application's migrations, create the test admin
    python tools/env.py start       start the test API on LT_API_PORT (default 8010)
    python tools/env.py stop        stop the test API
    python tools/env.py snapshot    save the current test database as the baseline (done once, after enrolment)
    python tools/env.py reset       stop API, restore the database from the baseline, start API   (before every stage)
    python tools/env.py destroy     stop the API and drop both test databases

The application is started exactly as in development (`uvicorn app.main:app`) from the untouched `backend/` folder;
only environment variables differ (database URL, port, keys), so the code under test is the real code.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psutil
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_config import settings as S  # noqa: E402

PID_FILE = S.RESULTS / "api.pid"
API_LOG = S.RESULTS / "api.log"
LOG_CONFIG = S.ROOT / "test_config" / "uvicorn_log.json"

# Keys used ONLY by the test instance: templates enrolled here are unreadable by any other instance, and vice versa.
TEST_ENV = {
    "DATABASE_URL": S.SQLALCHEMY_URL,
    "SECRET_KEY": "loadtest-secret-key-not-used-anywhere-else-0123456789abcdef",
    "TEMPLATE_KEY": "loadtest-template-key-not-used-anywhere-else",
    "ENVIRONMENT": "development",
    "COOKIE_SECURE": "false",
}


def _admin_conn(db: str = "postgres") -> psycopg.Connection:
    return psycopg.connect(f"{S.PG_DSN}/{db}", autocommit=True)


def _env() -> dict[str, str]:
    return {**os.environ, **TEST_ENV}


def _backend(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run([str(S.BACKEND_PYTHON), *args], cwd=S.BACKEND, env=_env(), check=check, capture_output=True, text=True)


def health(timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"{S.API_URL}/api/health", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


def api_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text())
        return pid if psutil.pid_exists(pid) else None
    except Exception:  # noqa: BLE001
        return None


def init() -> None:
    with _admin_conn() as c:
        if not c.execute("select 1 from pg_database where datname=%s", (S.PG_DB,)).fetchone():
            c.execute(f'create database "{S.PG_DB}"')
    r = _backend("-m", "alembic", "upgrade", "head")
    print(r.stdout[-300:] or r.stderr[-300:])
    r = _backend("tools/seed.py", "--admin-username", S.ADMIN_USER, "--admin-email", S.ADMIN_EMAIL, "--admin-password", S.ADMIN_PASSWORD)
    print(r.stdout.strip())


def start(wait: float = 90.0) -> None:
    if api_pid() and health():
        print("test API already running")
        return
    S.RESULTS.mkdir(parents=True, exist_ok=True)
    log = open(API_LOG, "a", encoding="utf-8")
    # No --reload: on Windows the reloader uses the select() loop, which cannot hold 500 sockets.
    p = subprocess.Popen([str(S.BACKEND_PYTHON), "-m", "uvicorn", "app.main:app", "--host", S.API_HOST, "--port", str(S.API_PORT),
                          "--log-config", str(LOG_CONFIG)], cwd=S.BACKEND, env=_env(), stdout=log, stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    PID_FILE.write_text(str(p.pid))
    t0 = time.time()
    while time.time() - t0 < wait:
        h = health()
        if h:
            print(f"test API up on {S.API_URL} (pid {p.pid}): {h}")
            return
        if p.poll() is not None:
            raise SystemExit(f"test API exited with code {p.returncode}; see {API_LOG}")
        time.sleep(0.5)
    raise SystemExit("test API did not become healthy in time")


def stop() -> None:
    pid = api_pid()
    if pid:
        try:
            proc = psutil.Process(pid)
            for ch in proc.children(recursive=True):
                ch.kill()
            proc.kill()
            proc.wait(10)
        except psutil.Error:
            pass
    PID_FILE.unlink(missing_ok=True)
    print("test API stopped")


def _drop(c: psycopg.Connection, db: str) -> None:
    c.execute("select pg_terminate_backend(pid) from pg_stat_activity where datname=%s and pid<>pg_backend_pid()", (db,))
    c.execute(f'drop database if exists "{db}"')


def snapshot() -> None:
    stop()
    with _admin_conn() as c:
        _drop(c, S.PG_BASELINE)
        c.execute("select pg_terminate_backend(pid) from pg_stat_activity where datname=%s and pid<>pg_backend_pid()", (S.PG_DB,))
        c.execute(f'create database "{S.PG_BASELINE}" template "{S.PG_DB}"')
    print(f"baseline saved as {S.PG_BASELINE}")


def reset() -> None:
    stop()
    with _admin_conn() as c:
        _drop(c, S.PG_DB)
        c.execute(f'create database "{S.PG_DB}" template "{S.PG_BASELINE}"')
    start()


def destroy() -> None:
    stop()
    with _admin_conn() as c:
        _drop(c, S.PG_DB)
        _drop(c, S.PG_BASELINE)
    print("test databases dropped")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"init": init, "start": start, "stop": stop, "snapshot": snapshot, "reset": reset, "destroy": destroy}.get(cmd)
    if not fn:
        raise SystemExit(__doc__)
    fn()
