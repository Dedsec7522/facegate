"""All tunables for the load-testing harness. Every value can be overridden with an environment variable of the same
name, so nothing here has to be edited to point the tests somewhere else."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # attendance-load-testing/
REPO = ROOT.parent                                  # the FaceGate repository (read-only for this harness)
BACKEND = REPO / "backend"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# --- system under test: a SEPARATE API process on its own port, talking to its own throwaway database -----------
API_HOST = _env("LT_API_HOST", "127.0.0.1")
API_PORT = int(_env("LT_API_PORT", "8010"))
API_URL = _env("LT_API_URL", f"http://{API_HOST}:{API_PORT}")
API = "/api/v1"
BACKEND_PYTHON = Path(_env("LT_BACKEND_PYTHON", str(BACKEND / ".venv" / "Scripts" / "python.exe")))

# --- isolated PostgreSQL (Docker container `facegate-loadtest-pg`; never the application's own database) --------
PG_CONTAINER = _env("LT_PG_CONTAINER", "facegate-loadtest-pg")
PG_HOST = _env("LT_PG_HOST", "127.0.0.1")
PG_PORT = int(_env("LT_PG_PORT", "5544"))
PG_USER = _env("LT_PG_USER", "loadtest")
PG_PASSWORD = _env("LT_PG_PASSWORD", "loadtest-local-only")
PG_DB = _env("LT_PG_DB", "facegate_lt")              # the database the test API uses
PG_BASELINE = _env("LT_PG_BASELINE", "facegate_lt_base")  # snapshot taken right after enrolment; every stage starts from it
PG_DSN = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}"
SQLALCHEMY_URL = f"postgresql+asyncpg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"

# --- test administrator (exists only in the test database) -----------------------------------------------------
ADMIN_USER = _env("LT_ADMIN_USER", "loadtest-admin")
ADMIN_EMAIL = _env("LT_ADMIN_EMAIL", "loadtest-admin@loadtest.example.com")
ADMIN_PASSWORD = _env("LT_ADMIN_PASSWORD", "LoadTest-Only-2026")

# --- dataset ---------------------------------------------------------------------------------------------------
LFW_DIR = Path(_env("LT_LFW_DIR", ""))               # extracted LFW folder (one sub-folder per person); only needed to build
DATASET = ROOT / "test_datasets"
FACES = DATASET / "faces"
MANIFEST = DATASET / "manifest.json"
EMPLOYEES = int(_env("LT_EMPLOYEES", "500"))
UNKNOWN_FACES = int(_env("LT_UNKNOWN_FACES", "100"))
SEED = int(_env("LT_SEED", "20261112"))

# --- camera simulation -----------------------------------------------------------------------------------------
FRAME_SIZE = (640, 480)                              # a webcam frame (width, height)
FPS = float(_env("LT_FPS", "10"))                    # what the real kiosk sends
JPEG_QUALITY = 80
MAX_FRAMES = int(_env("LT_MAX_FRAMES", "60"))        # analysed frames before the client gives up on a session
SESSION_DEADLINE_S = float(_env("LT_SESSION_DEADLINE_S", "70"))  # server TTL is 60 s

# --- attendance flow -------------------------------------------------------------------------------------------
DUPLICATE_WINDOW_S = int(_env("LT_DUPLICATE_WINDOW_S", "120"))   # the application's default duplicate_scan_seconds
CHECKOUT_AFTER_S = float(_env("LT_CHECKOUT_AFTER_S", "125"))     # wait this long after check-in before checking out

# --- outputs ---------------------------------------------------------------------------------------------------
RESULTS = ROOT / "test_results"
REPORTS = ROOT / "reports"
LOCUST_WEB = _env("LT_LOCUST_WEB", "http://127.0.0.1:8089")
