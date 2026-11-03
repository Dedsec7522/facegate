# FaceGate — self-hosted facial attendance platform

FaceGate identifies enrolled employees from a live camera, verifies they are physically present (passive anti-spoofing + head-turn challenge), and records auditable check-in / check-out events. Everything runs on your own servers: no cloud biometric APIs, templates encrypted at rest, full admin console, employee portal and reporting.

| | |
|---|---|
| Backend | Python 3.12+, FastAPI (async), SQLAlchemy 2 + Alembic, PostgreSQL 16 |
| Vision | OpenCV (YuNet detector, MIT), SFace embeddings (Apache-2.0) and MiniFASNet liveness (Apache-2.0) on ONNX Runtime — CPU only, ~40 ms/frame |
| Frontend | React 19, TypeScript, Vite, Tailwind v4, Motion, Recharts |
| Deployment | Docker Compose, Nginx TLS, nightly backups |

Documentation: [reference analysis](docs/01-reference-analysis.md) · [architecture](docs/02-architecture.md) · [design system](docs/03-design-system.md) · [security & privacy](docs/04-security-and-privacy.md) · [test & benchmark results](docs/05-test-and-benchmark-results.md) · [licences](docs/06-licences-and-dependencies.md) · [comparison with the reference](docs/07-comparison-and-improvements.md)

---

## 1. Local development (Windows / macOS / Linux)

Prerequisites: Python 3.12+, Node 20+, Docker (for Postgres), a webcam.

```bash
docker run -d --name facegate-pg -e POSTGRES_USER=facegate -e POSTGRES_PASSWORD=facegate -e POSTGRES_DB=facegate -p 5432:5432 postgres:16-alpine
```

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate        # source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env                                  # defaults work for local dev
alembic upgrade head
python tools/seed.py --demo --admin-email admin@facegate.local --admin-password 'Admin-Password-2026!'
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev            # http://localhost:5173 (proxies /api to :8000)
```

Then open http://localhost:5173 → **Administrator sign-in** with the seeded account → *Employees* → pick someone → **Enrol face** → open the **kiosk** and check in.

PAD models: `backend/models/minifasnet_*.onnx` are committed. To regenerate them from the vendor checkpoints run `tools/export_pad_onnx.py` with a separate venv that has `torch` (see the script header).

## 2. Production (Ubuntu + Docker Compose)

```bash
cd deploy
cp .env.example .env            # set PUBLIC_HOST, POSTGRES_PASSWORD, SECRET_KEY, TEMPLATE_KEY
mkdir -p certs backups          # put fullchain.pem + privkey.pem in certs/ (Let's Encrypt or your CA)
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api python tools/seed.py --admin-email you@company.com --admin-password 'a-strong-password'
```

- Nginx terminates TLS on 443, serves the SPA, proxies `/api` (HTTP + WebSocket) and rate-limits logins.
- Sizing: one API container with `INFERENCE_WORKERS = CPU cores` processes roughly 25 frames/s per core; a 4-core node comfortably serves ~10 kiosks verifying at once (see the benchmark doc). Scale by adding nodes behind a sticky-session load balancer (verification sessions are in-process).
- Backups: the `backup` service writes a gzipped `pg_dump` nightly to `deploy/backups/` (14-day retention). Restore with `gunzip -c file.sql.gz | docker compose exec -T db psql -U facegate facegate`.
- Rotate `TEMPLATE_KEY` only with a planned re-enrolment: templates are unrecoverable without it by design.

## 3. Daily use

| Role | Where | What |
|---|---|---|
| Employee | `/kiosk` | Start verification → follow the head-turn prompt → choose Check in / Check out. Optional admin-enabled PIN fallback. |
| Employee | `/portal` | Own attendance status, history and event timeline (needs an account created by an admin). |
| Admin / HR | `/admin` | Dashboard, employees & departments, enrolment, live attendance board, corrections, reports & exports, settings, MFA, users, audit log. |

## 4. Tests and benchmarks

```bash
cd backend && .venv/Scripts/python -m pytest -q                 # 19 tests: engine, vision, API, e2e stream
.venv/Scripts/python benchmarks/latency.py                       # per-stage latency on this machine
.venv/Scripts/python benchmarks/load_test.py --clients 300 --concurrency 10   # 300 sessions through 10 kiosks
cd ../frontend && npm run build                                   # tsc + Vite production build
```

Results from the development machine are recorded in [docs/05-test-and-benchmark-results.md](docs/05-test-and-benchmark-results.md).

## 5. Configuration

All settings are environment variables (see `backend/.env.example`). Attendance rules and verification thresholds can also be changed at runtime by an administrator under *Settings & Security* and are stored in the database.

| Variable | Default | Meaning |
|---|---|---|
| `MATCH_ACCEPT_THRESHOLD` | 0.42 | cosine similarity required to identify; below → `unknown` |
| `MATCH_MARGIN` | 0.08 | required gap to the second-best identity; smaller → `ambiguous` |
| `PAD_LIVE_THRESHOLD` | 0.80 | mean live-probability over ≥ `PAD_MIN_FRAMES` frames |
| `INFERENCE_WORKERS` | 4 | bounded CPU inference pool |
| `KEEP_ENROL_THUMBNAIL` | true | keep one 112 px aligned thumbnail per enrolment for admins |
| `VERIFY_SESSIONS_PER_MINUTE` | 120 | per-IP kiosk session limit |

## 6. Repository layout

```
backend/   app/{api,core,db,schemas,services,vision}  alembic/  tests/  benchmarks/  tools/  models/
frontend/  src/{app,components,lib,pages}
deploy/    docker-compose.yml  api.Dockerfile  web.Dockerfile  nginx/  .env.example
docs/      01…07 design, security, results, licences, comparison
```

Licence of this application code: MIT (see `LICENSE`). Third-party model and package licences are listed in `docs/06-licences-and-dependencies.md`.
