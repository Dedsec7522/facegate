# FaceGate — self-hosted facial attendance platform

FaceGate identifies enrolled employees from a live camera, verifies they are physically present (passive anti-spoofing + head-turn challenge), and records auditable check-in / check-out events. Everything runs on your own servers: no cloud biometric APIs, templates encrypted at rest, full admin console, employee portal and reporting.

| | |
|---|---|
| Backend | Python 3.12+, FastAPI (async), SQLAlchemy 2 + Alembic, PostgreSQL 16 |
| Vision | OpenCV (YuNet detector, MIT), Intel `face-reidentification-retail-0095` embeddings (Apache-2.0) on OpenVINO, MiniFASNet liveness (Apache-2.0) on ONNX Runtime — CPU only. SFace (Apache-2.0) remains available as a fallback model |
| Frontend | React 19, TypeScript, Vite, Tailwind v4, Motion, Recharts |
| Deployment | Docker Compose, Nginx TLS, nightly backups |

Documentation: [reference analysis](docs/01-reference-analysis.md) · [architecture](docs/02-architecture.md) · [design system](docs/03-design-system.md) · [security & privacy](docs/04-security-and-privacy.md) · [test & benchmark results](docs/05-test-and-benchmark-results.md) · [licences](docs/06-licences-and-dependencies.md) · [comparison with the reference](docs/07-comparison-and-improvements.md)

---

## 1. Local development (Windows / macOS / Linux)

Prerequisites: Python 3.12+, Node 20+, PostgreSQL 16 (Docker or a native install), a webcam. On Windows, `onnxruntime` and `openvino` need the Microsoft VC++ redistributable.

PostgreSQL with Docker:

```bash
docker run -d --name facegate-pg -v facegate-pgdata:/var/lib/postgresql/data -e POSTGRES_USER=facegate -e POSTGRES_PASSWORD=facegate -e POSTGRES_DB=facegate -p 5432:5432 postgres:16-alpine
```

…or without Docker (Windows example; `winget install PostgreSQL.PostgreSQL.16`, then):

```bash
psql -U postgres -h localhost -c "CREATE ROLE facegate LOGIN PASSWORD 'facegate';" -c "CREATE DATABASE facegate OWNER facegate;"
```

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate        # source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env                                  # defaults work for local dev
alembic upgrade head
python tools/seed.py --demo            # creates admin  username: admin  password: Welcome123  (change it after first login)
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev            # http://localhost:5173 (proxies /api to :8000)
```

Then open http://localhost:5173 → **Administrator sign-in** with username `admin` / password `Welcome123` (or the email `admin@facegate.local`) → *Employees* → pick someone → **Enrol face** (three automatic frontal samples; left/right turns optional) → open the **kiosk** and check in, or create the employee a login and use **Login from Office** in their portal.

Models: all weights are committed in `backend/models/` — YuNet (`.onnx`), the Intel face-recognition model (`face-reidentification-retail-0095.xml` + `.bin`, OpenVINO IR, SHA-384 checked against the Open Model Zoo), SFace (`.onnx`, fallback) and MiniFASNet (`minifasnet_*.onnx`).

**Face model and re-enrolment.** `FACE_MODEL` selects the embedding model (`intel-fr-0095`, default, or `sface-2021dec`). Every enrolment records the model that produced its templates and only templates of the running model are loaded, so after changing the model (including upgrading from a release that used SFace) every employee must be **re-enrolled**; the API logs how many active enrolments are affected at start-up.

PAD models: To regenerate them from the vendor checkpoints run `tools/export_pad_onnx.py` with a separate venv that has `torch` (see the script header).

## 2. Production (Ubuntu + Docker Compose)

```bash
cd deploy
cp .env.example .env            # set PUBLIC_HOST, POSTGRES_PASSWORD, SECRET_KEY, TEMPLATE_KEY
mkdir -p certs backups          # put fullchain.pem + privkey.pem in certs/ (Let's Encrypt or your CA)
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api python tools/seed.py --admin-username admin --admin-email you@company.com --admin-password 'a-strong-password'
```

- Nginx terminates TLS on 443, serves the SPA, proxies `/api` (HTTP + WebSocket) and rate-limits logins.
- Sizing: `INFERENCE_WORKERS=0` (default) runs one inference worker per physical core. The per-frame cost dropped roughly 5x with the Intel embedder, half-resolution detection and the per-session embedding cap (see `docs/05` §7), so each core handles several times more concurrent verifications than before. A verification session is in-process, so scale beyond one node with a sticky-session load balancer. Re-run `benchmarks/load_test.py` on the production host before sizing for a 300-person peak.
- Backups: the `backup` service writes a gzipped `pg_dump` nightly to `deploy/backups/` (14-day retention). Restore with `gunzip -c file.sql.gz | docker compose exec -T db psql -U facegate facegate`.
- Rotate `TEMPLATE_KEY` only with a planned re-enrolment: templates are unrecoverable without it by design.

## 3. Daily use

| Role | Where | What |
|---|---|---|
| Employee | `/kiosk` | Start verification → follow the head-turn prompt → choose Check in / Check out. Optional admin-enabled PIN fallback. |
| Employee | `/portal` | **Login from Office / Logout from Office** with a face check bound to the signed-in account (1:1 — only your own enrolled face can log your account in or out), today's times, history and event timeline (needs an account created by an admin). |
| Admin / HR | `/admin` | Dashboard, employees & departments, enrolment, live attendance board, corrections, reports & exports, settings, MFA, users, audit log. |

## 4. Tests and benchmarks

```bash
cd backend && .venv/Scripts/python -m pytest -q                 # 22 tests: engine, vision, API, e2e stream, bound verification
# vision + e2e tests need face images in backend/tests/data/synth_face_*.jpg (git-ignored; ≥ 3 different people, sharp at 640 px)
.venv/Scripts/python benchmarks/latency.py                       # per-stage latency on this machine
.venv/Scripts/python benchmarks/load_test.py --clients 300 --concurrency 10   # 300 sessions through 10 kiosks
cd ../frontend && npm run build                                   # tsc + Vite production build
```

Results from the development machine are recorded in [docs/05-test-and-benchmark-results.md](docs/05-test-and-benchmark-results.md).

Liveness policy is per channel (*Settings → Verification*): the signed-in portal defaults to **advisory** (instant, ~0.5 s), the anonymous kiosk to **passive** (anti-spoof gate with a head-turn only when unsure), and **strict** forces a head turn everywhere.

## 5. Configuration

All settings are environment variables (see `backend/.env.example`). Attendance rules and verification thresholds can also be changed at runtime by an administrator under *Settings & Security* and are stored in the database.

| Variable | Default | Meaning |
|---|---|---|
| `FACE_MODEL` | intel-fr-0095 | embedding model: `intel-fr-0095` (OpenVINO, 256-d) or `sface-2021dec` (ONNX Runtime, 128-d). Changing it requires re-enrolment |
| `MATCH_ACCEPT_THRESHOLD` | 0.45 | cosine similarity required to identify; below → `unknown`. Calibrated on LFW for `intel-fr-0095` (≈ 5·10⁻⁵ false accepts per comparison); use ~0.42 with SFace |
| `MATCH_MARGIN` | 0.08 | required gap to the second-best identity; smaller → `ambiguous` |
| `PAD_LIVE_THRESHOLD` | 0.45 | median live-probability that passes on passive evidence alone (typical live check ≈ 0.5–1 s) |
| `PAD_SPOOF_THRESHOLD` | 0.20 | below this the session is rejected; between the two thresholds the server asks for a one-off head turn (step-up) |
| `PAD_REJECT_MIN_FRAMES` | 14 | frames of evidence before a session is rejected as spoof |
| `INFERENCE_DEVICE` | cpu | CPU only — no GPU is used or required |
| `INFERENCE_WORKERS` | 0 | bounded CPU inference pool; `0` = one worker per physical core |
| `DETECT_MAX_SIDE` | 320 | frames are downscaled to this for face detection only (alignment and embedding use full resolution); `0` disables |
| `EMBED_MAX_FRAMES` | 6 | a verification session stops computing embeddings once it holds this many frontal ones |
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
