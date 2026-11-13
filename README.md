# FaceGate — self-hosted facial attendance platform

FaceGate identifies enrolled employees from a live camera, verifies they are physically present (passive anti-spoofing + head-turn challenge), and records auditable check-in / check-out events. Everything runs on your own servers: no cloud biometric APIs, templates encrypted at rest, full admin console, employee portal and reporting.

| | |
|---|---|
| Backend | Python 3.12+, FastAPI (async), SQLAlchemy 2 + Alembic, PostgreSQL 16 |
| Vision | OpenCV (YuNet detector, MIT), Intel `face-reidentification-retail-0095` embeddings (Apache-2.0) on OpenVINO, MiniFASNet liveness (Apache-2.0) and the Intel Open Model Zoo `anti-spoof-mn3` photo/screen detector (MIT) on ONNX Runtime — CPU only. SFace (Apache-2.0) remains available as a fallback model |
| Frontend | React 19, TypeScript, Vite, Tailwind v4, Motion, Recharts |
| Deployment | Docker Compose, Nginx TLS, nightly backups |

Documentation: [reference analysis](docs/01-reference-analysis.md) · [architecture](docs/02-architecture.md) · [design system](docs/03-design-system.md) · [security & privacy](docs/04-security-and-privacy.md) · [test & benchmark results](docs/05-test-and-benchmark-results.md) · [licences](docs/06-licences-and-dependencies.md) · [comparison with the reference](docs/07-comparison-and-improvements.md)

---

## 1. Local development (Windows / macOS / Linux)

### Prerequisites

| Need | Why | Windows (winget) | macOS / Linux |
|---|---|---|---|
| Git | clone / push | `winget install --id Git.Git -e` | Xcode CLT / `apt install git` |
| Python 3.12+ | backend, tools, tests | `winget install --id Python.Python.3.12 -e` | `brew install python@3.12` / `apt install python3.12-venv` |
| Node 20+ (22/26 LTS fine) | frontend (Vite) | `winget install --id OpenJS.NodeJS.LTS -e` | `brew install node` / nodesource |
| Docker Desktop (or Postgres 16) | database | Docker Desktop must be **running** | Docker / `brew install postgresql@16` |
| VC++ redistributable (Windows only) | `onnxruntime`, `openvino` | `winget install --id Microsoft.VCRedist.2015+.x64 -e` | not needed |
| A webcam | enrolment, kiosk, portal face login | | |

No GPU, no accounts, no API keys: all models are committed in `backend/models/` and everything runs on the CPU.

Windows notes: winget puts Git and Python under `%LOCALAPPDATA%\Programs\…` and Node under `C:\Program Files\nodejs`; a terminal opened *after* installing sees them on PATH, an older shell (including an AI coding session's shell) may not and must use full paths. Run the backend from PowerShell or Git Bash; `.venv\Scripts\python.exe -m …` always works without activating the venv.

### First run

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
python tools/seed.py --employee-logins # optional: portal login for every employee (username = employee code, password Welcome123)
python -m uvicorn app.main:app --reload --reload-dir app --port 8000   # --reload-dir: don't watch .venv
```

```bash
cd frontend && npm install && npm run dev            # http://localhost:5173 (proxies /api to :8000)
```

Then open http://localhost:5173 → **Administrator sign-in** with username `admin` / password `Welcome123` (or the email `admin@facegate.local`) → *Employees* → pick someone → **Enrol face** (three automatic frontal samples; left/right turns optional) → open the **kiosk** and check in, or create the employee a login and use **Login from Office** in their portal.

To try the employee dashboard: **Sign in** on the landing page, *Employee* tab, with the employee code as username, e.g. `e1001` / `Welcome123` after `seed.py --employee-logins`. In development the sign-in page also shows one-click test accounts (served by `GET /api/v1/auth/test-accounts`, which answers only when `ENVIRONMENT=development`).

Set the **organisation time zone** once: *Settings → Attendance rules → Country / region* (e.g. India → `Asia/Kolkata`). Every time in the UI is shown in that zone, whatever the PC's own clock zone is set to; the server stores UTC. Until then the `ORG_TIMEZONE` from `.env` applies.

Checklist for a fresh machine / session: Docker Desktop running → `docker start facegate-pg` (or the `docker run` above) → API on 8000 → `npm run dev` on 5173 → sign in as `admin` / `Welcome123`.

Models: all weights are committed in `backend/models/` — YuNet (`.onnx`), the Intel face-recognition model (`face-reidentification-retail-0095.xml` + `.bin`, OpenVINO IR, SHA-384 checked against the Open Model Zoo), SFace (`.onnx`, fallback), MiniFASNet (`minifasnet_*.onnx`) and the replay detector `anti-spoof-mn3.onnx` (12 MB, SHA-384 checked against the Open Model Zoo).

**Face model and re-enrolment.** `FACE_MODEL` selects the embedding model (`intel-fr-0095`, default, or `sface-2021dec`). Every enrolment records the model that produced its templates and only templates of the running model are loaded, so after changing the model (including upgrading from a release that used SFace) every employee must be **re-enrolled**; the API logs how many active enrolments are affected at start-up.

PAD models: To regenerate them from the vendor checkpoints run `tools/export_pad_onnx.py` with a separate venv that has `torch` (see the script header).

## 2. Production (Ubuntu + Docker Compose)

```bash
cd deploy
cp .env.example .env            # set PUBLIC_HOST, POSTGRES_PASSWORD, SECRET_KEY, TEMPLATE_KEY
mkdir -p certs backups          # put fullchain.pem + privkey.pem in certs/ (Let's Encrypt or your CA)
docker compose build
# migrate + seed in one-off containers first: the API refuses to start against an empty database
docker compose run --rm --no-deps api alembic upgrade head
docker compose run --rm --no-deps api python tools/seed.py --admin-username admin --admin-email you@company.com --admin-password 'a-strong-password'
docker compose up -d
```

- Nginx terminates TLS on 443, serves the SPA, proxies `/api` (HTTP + WebSocket) and rate-limits logins. It is the only route to the API and **overwrites** `X-Forwarded-For` with the real client address, so per-IP limits and audit IPs cannot be spoofed with a client-sent header.
- Sizing: `INFERENCE_WORKERS=0` (default) runs one inference worker per physical core. The per-frame cost dropped roughly 5x with the Intel embedder and half-resolution detection (see `docs/05` §7), so each core handles several times more concurrent verifications than before. A verification session is in-process, so scale beyond one node with a sticky-session load balancer. Re-run `benchmarks/load_test.py` on the production host before sizing for a 300-person peak.
- Backups: the `backup` service writes a gzipped `pg_dump` nightly to `deploy/backups/` (14-day retention). Restore with `gunzip -c file.sql.gz | docker compose exec -T db psql -U facegate facegate`.
- Rotate `TEMPLATE_KEY` only with a planned re-enrolment: templates are unrecoverable without it by design.

## 3. Daily use

| Role | Where | What |
|---|---|---|
| Employee | `/kiosk` | Start verification → identified in about a second → the one action the engine allows (Login or Logout) is recorded automatically after a 3 s countdown (tap to do it now, or *Not you? Cancel*). Bystanders in the frame are labelled with name and signed-in state but never recorded; a partially covered face (mask, scarf, cap over the eyes, one eye or one side hidden) is refused with an error, and a photo or phone screen held up to the camera is refused as "Photo or screen detected". In a dark room the screen lights a white border as a lamp. Optional admin-enabled PIN fallback. |
| Employee | `/portal` | **Login from Office / Logout from Office** with a face check bound to the signed-in account (1:1 — only your own enrolled face can log your account in or out), today's times, a month **calendar** (green present, red absent, yellow leave), insights and the event timeline (needs an account: `seed.py --employee-logins` or *Employees → Create account*). |
| Admin / HR | `/admin` | Dashboard, employees & departments, enrolment, live attendance board, corrections, reports & exports, settings, MFA, users, audit log. |

## 4. Tests and benchmarks

```bash
cd backend && .venv/Scripts/python -m pytest -q                 # 30 tests: engine, vision, API, e2e stream, bound verification, session binding, inference admission
# vision + e2e tests need face images in backend/tests/data/synth_face_*.jpg (git-ignored; ≥ 3 different people, sharp at 640 px)
.venv/Scripts/python benchmarks/latency.py                       # per-stage latency on this machine
.venv/Scripts/python benchmarks/load_test.py --clients 300 --concurrency 10   # 300 sessions through 10 kiosks
.venv/Scripts/python benchmarks/load_test.py --clients 500 --concurrency 500 --face any_face.jpg --base http://127.0.0.1:8001  # see "Capacity"
cd ../frontend && npm run build                                   # tsc + Vite production build
```

**Mixed real-time load test with [Locust](https://locust.io)** (MIT; install it in its own venv, it is not an API dependency:
`pip install locust websocket-client opencv-python-headless`). `benchmarks/locustfile.py` simulates employees signing in and
using the portal, admins refreshing the console, and people checking in at kiosks (JPEG frames over the WebSocket, full
detect → liveness → embed → match). Each simulated user gets its own source address, so per-IP limits behave as with real
devices; run the generator on the API's machine (Uvicorn trusts `X-Forwarded-For` only from 127.0.0.1) or set
`FORWARDED_ALLOW_IPS` to the generator's address, and target the API on port 8000, not nginx.

```bash
cd backend
locust -f benchmarks/locustfile.py --host http://127.0.0.1:8000                     # live web UI on http://localhost:8089
locust -f benchmarks/locustfile.py --host http://127.0.0.1:8000 --headless -u 400 -r 20 -t 3m --html report.html
# Windows has no --processes: one master plus N workers (separate shells) for 300+ users
locust -f benchmarks/locustfile.py --master --headless --expect-workers 4 -u 400 -r 20 -t 3m --host http://127.0.0.1:8000
locust -f benchmarks/locustfile.py --worker --host http://127.0.0.1:8000
```

`PORTAL_WEIGHT` / `ADMIN_WEIGHT` / `KIOSK_WEIGHT` (default 6 / 1 / 3) set the mix; `KIOSK_WEIGHT=0` tests the web tier alone.

Results from the development machine are recorded in [docs/05-test-and-benchmark-results.md](docs/05-test-and-benchmark-results.md).

**Full Locust suite with ground truth** lives in [`attendance-load-testing/`](attendance-load-testing/README.md): ten staged
tests from 10 to 500 simultaneous employees, a 500-person burst, a sustained run, an accuracy pass and a liveness pass, each
verdict compared with the known identity and every stored attendance row validated afterwards. It runs against its own API
process (port 8010) and its own Postgres container, never the real data, and its live dashboard is embedded in the admin
console under *Locust load test*. The report in `attendance-load-testing/reports/final_report.html` is from 12–13 Nov 2026 on
the development laptop with about half the CPU taken by another process: only the 10-user stage met the 2 s p95 target, and
the suite's verdict for that machine is **not ready** for hundreds of simultaneous kiosks. That run predates the replay
detector and the stricter covering rules; re-run it on the production host.

Liveness policy is per channel (*Settings → Verification*). Both channels default to **advisory** (instant, ~0.5 s; the
MiniFASNet score is logged, not enforced); **passive** adds the anti-spoof gate with a head turn only when unsure; **strict**
forces a head turn everywhere. Independently of the policy, the **replay detector** scores every frame and refuses a session
that looks like a photo or a screen, with no extra frames and no head turn.

Limits, stated plainly: the replay detector was measured on photographs (0.8 % of genuine LFW frames fall below 0.45) and has
not yet been validated against live phone or print replays on a real camera; tune `REPLAY_SPOOF_THRESHOLD` from the logged
`replay_real` scores. Partial covering is a colour heuristic: on synthetic covers it accepts 1–2 % of masked faces, 4–6 % with
one eye covered, 14–16 % with half the face hidden, wrongly flags about 4 % of uncovered frames (the scan just uses the next
frame), and does **not** catch a skin-coloured cover such as a hand over the mouth.

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
| `REPLAY_CHECK` | true | run the `anti-spoof-mn3` photo/screen detector on every frame (~7 ms) |
| `REPLAY_SPOOF_THRESHOLD` | 0.30 | a session whose median "real face" probability is below this after `REPLAY_MIN_FRAMES` (3) frontal frames is rejected as `replay`, under every liveness policy |
| `BUSY_HOLD_SECONDS` | 1.0 | how long a frame waits for a free inference slot before the server answers `busy` |
| `INFERENCE_DEVICE` | cpu | CPU only — no GPU is used or required |
| `INFERENCE_WORKERS` | 0 | bounded CPU inference pool; `0` = one worker per physical core |
| `DETECT_MAX_SIDE` | 320 | two-stage detection: faces are found on a copy downscaled to this size, then landmarks are refined on a full-resolution crop around each face (coarse landmarks skew head pose and alignment); `0` = single full-resolution pass |
| `KEEP_ENROL_THUMBNAIL` | true | keep one 112 px aligned thumbnail per enrolment for admins |
| `VERIFY_SESSIONS_PER_MINUTE` | 120 | per-IP kiosk session limit |
| `RELOGIN_COOLDOWN_HOURS` | 10 | a login is refused until this long after the employee's last logout (0 disables; also in *Settings*) |
| `ORG_TIMEZONE` | Europe/London | default organisation zone until an admin picks a region in *Settings* |
| `LOGIN_PER_MINUTE_PER_IP` | 60 | password sign-ins per minute from one address (an office NAT is one address); accounts still lock after 5 failed attempts |
| `FORWARDED_ALLOW_IPS` | 127.0.0.1 | Uvicorn setting: proxies whose `X-Forwarded-For` is believed. The app never reads that header itself; Docker uses `*` because nginx overwrites it and is the only way in |

## 6. Capacity (measured 11 Nov 2026, one Windows laptop: 8 logical cores, Docker Desktop Postgres, load generator on the same machine)

| Scenario | Result |
|---|---|
| 500 password sign-ins fired at once | 500 / 500 succeed, ~16 logins/s sustained, last one answered after 31 s; 100 at once finish in 6 s |
| 500 face check-ins through 10 kiosks | 500 / 500 identified, 2.2 s per person (p95 3.2 s), all done in 115 s |
| 500 face check-ins through 50 kiosks | 500 / 500 identified, 13.6 s per person (queueing), 17 frames/s |
| 500 face streams truly simultaneous (500 kiosks) | exceeds one node: ~80 % identified, the rest time out in the queue |

The vision pipeline tops out at ~35 frames/s on this CPU (2–4 threads); ~5 frames identify a person, so one node handles roughly 6–7 check-ins per second at best. 400–500 people arriving through a handful of kiosks over a few minutes is comfortable; 500 kiosks streaming at the same instant is not, and needs more nodes behind a sticky-session load balancer (§2). Measure on the production host with `benchmarks/load_test.py` (use `--face` with any face photo) against an instance started **without** `--reload` (see CLAUDE.md gotchas for the Windows socket cap and the load-generator pitfall).

**Mixed load with Locust (12 Nov 2026, same laptop, 16 logical CPUs, ~50 % of the CPU taken by an unrelated background process,
so treat these as a lower bound):**

| Scenario (3 min / 2 min, 20 new users/s) | Result |
|---|---|
| 400 users at once: 240 employees on the portal, 40 admins, 120 people checking in at kiosks simultaneously | 28,938 requests, 0.45 % failed (idle keep-alive connections closed by the server, not errors); 280 logins, 0 failed; pages median ~2.5 s; 1,017 face check-ins completed, 0 failed, 9–14 s each; vision pipeline saturated at ~38 analysed frames/s, the rest answered `busy` and retried |
| 400 web-only users (no kiosks) | ~98 requests/s, pages median 0.6–1 s, logins median 1.1 s, 0.6 % failed (same keep-alive closes) |

120 kiosks streaming at the same moment is ~1,200 frames/s of demand against ~38 frames/s of capacity, so check-ins queue
but finish; real arrivals are spread out. The face pipeline, not the web tier, is what to size for.

## 7. Repository layout

```
backend/   app/{api,core,db,schemas,services,vision}  alembic/  tests/  benchmarks/  tools/  models/
frontend/  src/{app,components,lib,pages}
deploy/    docker-compose.yml  api.Dockerfile  web.Dockerfile  nginx/  .env.example
docs/      01…07 design, security, results, licences, comparison
attendance-load-testing/   Locust suite with ground truth, its own API instance and database (see its README)
```

Licence of this application code: MIT (see `LICENSE`). Third-party model and package licences are listed in `docs/06-licences-and-dependencies.md`.
