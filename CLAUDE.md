# FaceGate — context for Claude sessions

Self-hosted, CPU-only face-recognition attendance platform. FastAPI backend, React/TypeScript
frontend, PostgreSQL, Docker/Nginx deploy. Original code: the OpenCV Zoo YuNet repository was
used **only as research**; nothing from it is copied or a runtime dependency (see
`docs/01-reference-analysis.md` and `docs/07-comparison-and-improvements.md`).

Read `README.md` first for setup and daily use; this file covers what a new session needs to
work on the code without re-discovering it.

## Hard constraints (from the product owner)

- **No GPU, no paid APIs, no cloud biometrics.** OpenVINO / ONNX Runtime on the CPU only;
  `cv2.ocl.setUseOpenCL(False)` is deliberate.
- **Commercial-use licences only** for every model (MIT / Apache-2.0). InsightFace/ArcFace packs, SCRFD,
  EdgeFace and WebFace-trained AdaFace weights are non-commercial — don't adopt them.
- **Real liveness, honestly described.** No blink-only or fake anti-spoofing claims, no hidden
  bypasses. The liveness policy is configurable per channel (`advisory | passive | strict`) and
  the UI says what each mode guarantees.
- **Instant, reliable scans.** Enrolment is three automatic frontal samples (no head rotations
  required); verification must not make people move their head unless policy is `strict` or the
  passive check is unsure.
- **Portal 1:1 binding.** `POST /verify/sessions/me` binds the session to the signed-in
  employee; a different face returns `mismatch`. Nobody can log another person's account in/out.
- **One common sign-in** for everyone; role (`admin | hr | employee`) decides the landing page.
  Login accepts username *or* email (`identifier`). Default dev admin: `admin` / `Welcome123`.
  Employee usernames = lower-cased employee code (e.g. `tka001`). `tools/seed.py --employee-logins` gives every
  employee a portal login (password `Welcome123`); the sign-in page has Administrator / Employee tabs (`/login?as=employee`)
  and, only when `/api/health` reports `development`, one-click test accounts.
- **Enrolled faces persist** (encrypted templates in Postgres, in-RAM index rebuilt on start).
- Light-purple design (brand `#6D28D9`), light mode default, smooth Motion animations.

## Layout

```
backend/
  app/main.py              FastAPI app, lifespan loads vision models + template index
  app/core/                 config (pydantic-settings), deps (RBAC), security (Argon2id, JWT), rate_limit
  app/db/models.py          SQLAlchemy 2 models; alembic/ holds migrations
  app/api/v1/               auth, employees, verify (REST + WebSocket streams), attendance, admin
  app/services/             attendance engine, enrolment, verification SessionManager, index, audit, org_settings
  app/vision/               detector (YuNet), align, quality, embedder (Intel 0095 on OpenVINO; SFace fallback), pad (MiniFASNet), matcher, pipeline
  models/                   committed weights: YuNet (MIT), face-reidentification-retail-0095 .xml/.bin (Apache-2.0),
                            SFace (Apache-2.0, fallback), MiniFASNet V1SE + V2 (Apache-2.0),
                            anti-spoof-mn3 (MIT, Open Model Zoo; replay detector)
  tools/seed.py             admin/demo seeding;  tools/export_pad_onnx.py  one-off torch→ONNX export
  tests/                    pytest (SQLite via aiosqlite); benchmarks/ latency, 300-client load test, locustfile.py (mixed Locust test)
frontend/
  src/lib/                  api.ts (fetch wrapper, cookie auth), auth.tsx, theme.tsx, motion.ts, format.ts, types.ts
  src/components/           ui/ (Button, Card, Badge, Dialog…), layout/ (AdminShell, PortalShell, ThemeToggle), camera/
  src/pages/                auth/Login, kiosk/Kiosk, portal/Portal, admin/* (Dashboard, Employees, Enrolment, Attendance, Reports, Settings)
  src/index.css             Tailwind v4 tokens; `@custom-variant dark` is bound to data-theme, not the OS
deploy/                     docker-compose, Dockerfiles, nginx, .env.example
docs/01–07                  architecture, design system, security, test/benchmark results, licences, comparison
```

## Key mechanics

- **Verification stream**: client sends JPEG frames over WS `/verify/stream/{id}` at ~10 fps;
  server caps at 15 fps and *acknowledges* throttled frames with `{"state":"throttled"}` (never
  drop silently — the client awaits a reply per frame). Terminal states: `identified` (carries a
  single-use 90 s `token`, `next` expected action and `today` times) or `rejected` (`reason`).
- **Attendance engine** (`services/attendance.py`): org timezone (`Asia/Kolkata` in the dev DB),
  attendance day starts 04:00, duplicate window, missing check-out auto-flag after N hours,
  immutable events + audited corrections, `AttendanceDay` summaries. If the engine refuses an
  action ("No open check-in"), the UI should only offer the valid one — not fight the engine.
- **Embedding model** (`FACE_MODEL`): default `intel-fr-0095` — Intel Open Model Zoo
  `face-reidentification-retail-0095`, 256-d, 128×128 BGR input aligned to its own 5-point template
  (`align.REFERENCE_INTEL_UNIT`), run on OpenVINO with one infer request per worker thread, no flip TTA.
  Fallback `sface-2021dec` (128-d, ONNX Runtime, flip TTA). LFW via our own YuNet + alignment: Intel
  99.50 % / TAR 98.87 % @ FAR 0.1 % vs SFace+flip 99.08 % / 97.97 %, at ~5x lower cost.
- **Templates are model-specific.** `BiometricEnrolment.model_version` records the producing model;
  `rebuild_index` loads only the running model's templates and logs stale enrolments. Changing
  `FACE_MODEL` = re-enrol everyone. Adaptive templates are never added to another model's enrolment.
- **Matching**: cosine on L2-normalised embeddings; accept ≥ 0.45 (LFW-calibrated for Intel, ≈ 5e-5 FAR
  per comparison) with margin 0.08 (`identified | unknown | ambiguous`). Adaptive templates (max
  10/employee) are added after confident matches. An admin-saved threshold in the DB overrides the default.
- **Throughput knobs**: `INFERENCE_WORKERS=0` → one worker per physical core; `cv2.setNumThreads(1)`
  (parallelism comes from the pool); two-stage detection — faces found on a `DETECT_MAX_SIDE`=320 copy, then
  landmarks re-detected on a full-resolution crop (coarse landmarks gave 4–11° yaw bias and worse alignment);
  every frontal frame of a session is embedded (no cap: the consistency check must cover the frames that
  supply the liveness evidence, or a photo could provide the identity and another live face the liveness).
- **Templates** are AES-256-GCM encrypted with `TEMPLATE_KEY` (AAD = template id). Rotating the
  key means re-enrolling everyone — by design.
- **Kiosk hand-off to the dashboard**: the kiosk posts `open_portal: true` with the attendance event. If the employee has an
  active `employee`-role account without MFA, the server also sets the access cookie only (no refresh session, so it ends after
  `ACCESS_TOKEN_MINUTES`), audits `auth.face_login`, returns `portal_session`, and the kiosk navigates to `/portal` after the
  greeting. Never opens the admin console and never bypasses MFA.
- **Several people in frame**: the subject is the largest face (closest to the camera); everyone else comes back in
  `others` with box + identity (one embedding each, no PAD) and, on the attendance stream, name / `signed_in` / `since`
  from a per-session cache (`_enrich_others`). Only a second face within `PRIMARY_FACE_MARGIN` (0.85) of the subject's
  size refuses the frame (`multiple_faces`: "step closer"). Bystanders are never checked in.
- **Replay detector** (`pad.replay_real_prob`, `REPLAY_CHECK`): Intel OMZ `anti-spoof-mn3` (MIT, trained on CelebA-Spoof)
  scores every frame next to MiniFASNet (~7 ms, no extra frames, no head turn). A session whose median "real" probability is
  below `REPLAY_SPOOF_THRESHOLD` (0.30) after 3 frontal frames is rejected with reason `replay` under EVERY liveness policy,
  advisory included. Added because MiniFASNet scored a phone-screen photo in a dark room 0.80 live. Genuine LFW photos: 0.8 %
  of frames below 0.45 (MiniFASNet 8.5 %). It reads under-exposed faces as spoofs, so crops with mean < 90 are brightened
  first (never dim a bright crop: that makes real faces look fake). Not yet validated on live replays; both scores are logged
  per verdict (`verify attendance: ... liveness= replay_real=`) for tuning.
- **Low light**: the server still refuses a face darker than 40. Kiosk and portal respond with `FillLight` (white screen
  border as a lamp) and `useCamera.boostLowLight` (exposure/brightness constraints where the webcam exposes them, restored after).
- **Inference admission** (`pipeline.Admission`): a frame waits up to `BUSY_HOLD_SECONDS` (1.0) for a slot instead of an
  instant "busy" (kiosks re-send immediately, which flooded the event loop); waiters with more collected evidence go first.
- **Partial covering** is a colour heuristic, not a trained model (`quality.occlusion`): nose + lip patches not
  skin-toned while a forehead/bridge/temple patch is → `covered`; both eye patches far darker than it AND flat (std < 22: a real eye keeps sclera/iris contrast) → `eyes_covered`
  (LFW: 1.1 % false flags vs 8.9 % on darkness alone; 97 % of drawn sunglasses caught);
  silent when no reference patch is skin-toned. `FrameAlerts` renders it as an error in kiosk, portal and enrolment.
  `_partial_cover` adds three rules: lips + chin non-skin but bright (mask worn low) → `covered`; one eye patch flat while
  the other is not → `eyes_covered`; one cheek skin, the other not → `covered`. Synthetic covers accepted: mask 1–2 %,
  low mask 12 %, one eye 4–6 %, half face 14–16 %; uncovered frames flagged 4 % (was 2 %). A skin-coloured cover (hand
  over the mouth) is NOT caught (96 % accepted): do not claim otherwise.
- **Load-test suite** (`attendance-load-testing/`, own README): Locust master + workers against a separate API on 8010
  and Postgres container `facegate-loadtest-pg` (5544); never the dev DB. `tools/run_suite.py` runs the stages,
  `validate_db.py` checks stored rows, `make_reports.py` writes `reports/`. Admin → *Locust load test*
  (`pages/admin/LoadTest.tsx`) only embeds its dashboard (`VITE_LOADTEST_URL`, default :8089). Build frames in the gevent
  threadpool, never on the worker loop (workers missed heartbeats and Locust stopped the run). Don't run pytest or other
  CPU-heavy work while a stage is running. `reports/final_report.html` is the 12–13 Nov 2026 run, before the replay
  detector and `Admission`; verdict there was NOT READY (only the 10-user stage met p95 2 s).
- **Error pages** (`pages/errors/`): animated 404 / route-error screens wired in `app/router.tsx`.
- **Time zone**: the organisation zone (Settings → Attendance rules, a country/region picker in `RegionPicker.tsx`
  over the offline table `lib/regions.ts`; no IP geolocation) is served publicly by `/api/health` and set into
  `lib/format.ts` (`setDisplayTimeZone`) at start-up, so every displayed time is organisation wall-clock, never the
  device's. Server timestamps are UTC. Changing zone/work hours recomputes the last 31 days (`recompute_recent_days`).
- **Re-login cooldown** (`relogin_cooldown_hours`, default 10, 0 disables; Settings → Attendance rules): after a
  check-out the next check-in is refused (`AttendanceError("cooldown")`, HTTP 409) until the gap has passed. It counts
  from the latest non-voided check-out on any day, so same-day re-entry (lunch break) is impossible unless it is 0.
  `next_expected_action` returns `login_allowed_at` / `last_checkout_at` / `cooldown_hours` so kiosk and portal show the
  block instead of offering a login.
- **Leave** is a day status set only by an admin correction (`kind: leave | clear_leave`, `occurred_at` = any time on
  the day, refused when the day has events); `recompute_day` preserves it. Absent days have no row (or an `absent`
  row): the portal calendar derives them client-side for Mon–Fri on or after the employee record's `since` date.
- **Portal insights** `GET /attendance/me/insights?days=30` averages check-in/out times in the
  org timezone; "black points" = late arrivals + missed logouts.

## Working on it

Fresh machine: README §1 lists every prerequisite with the winget / brew command (Git, Python 3.12, Node LTS, Docker
Desktop running, VC++ redistributable on Windows). Sequence: Postgres container `facegate-pg` → `backend/.venv` +
`pip install -r requirements.txt` → `.env` from `.env.example` with generated `SECRET_KEY` / `TEMPLATE_KEY` →
`alembic upgrade head` → `tools/seed.py --demo --employee-logins` → API on 8000 → `npm install && npm run dev` (5173).
On Windows, winget installs are not on an already-open shell's PATH: use `%LOCALAPPDATA%\Programs\Git\cmd\git.exe`,
`%LOCALAPPDATA%\Programs\Python\Python312\python.exe`, `C:\Program Files\nodejs` (or open a new terminal).
Test accounts: `admin` / `Welcome123`; employees = lower-cased employee code / `Welcome123`.

```bash
# backend (Python 3.12+; a .venv already exists on the dev machine)
cd backend && .venv/Scripts/python -m pytest -q          # must stay green (30 tests)
.venv/Scripts/python -m uvicorn app.main:app --reload --reload-dir app --port 8000  # some dev machines use 8001 (frontend/.env.local)
# frontend (Node 20+)
cd frontend && npm run dev                                 # Vite on 5173, proxies /api → FACEGATE_API_URL or :8000
npx tsc --noEmit -p tsconfig.app.json && npm run lint      # type check + oxlint (no eslint config here)
npm run build
```

- Postgres for dev: Docker container `facegate-pg` (see README). Tests do not need it.
- Browser checks: `.claude/launch.json` defines the `frontend` preview. Browser automation has no
  webcam, so face flows are verified with `backend/tests/test_e2e_stream.py` (synthetic frames
  with micro-motion jitter) and by the user live.
- The API process does not hot-reload unless started with `--reload`; restart it after backend
  edits.
- Commit messages: plain imperative summaries, no attribution lines.

## Gotchas learned the hard way

- `onnxruntime` and `openvino` on Windows need the VC++ redistributable.
- `.env.example` once shipped `PAD_LIVE_THRESHOLD=0.80`, far above what a real webcam scores (0.4–0.85; glasses, caps
  and dim offices sit at the low end) — keep it at the 0.45 default. Enrolment is admin-supervised, so `commit_enrolment`
  rejects only a clear spoof (median < `PAD_SPOOF_THRESHOLD`) and flags low-but-live medians (`liveness_low`) instead of blocking.
- The OpenCV Zoo **int8** SFace files are ~7x *slower* than fp32 on ONNX Runtime (ConvInteger) and the
  `int8bq` file doesn't load in ORT at all. The old opset-8 ArcFace R100 ONNX fails ORT's BatchNorm check
  (OpenVINO reads it) and costs ~360 ms/face — too slow.
- Vision/e2e tests skip without `tests/data/synth_face_*.jpg` (git-ignored). Real photos used there may
  score low on passive PAD (LFW photos: ~0.42) and fail the e2e enrolment liveness gate; run that test with `PAD_LIVE_THRESHOLD=0.3` when using such images.
- Uvicorn `--reload` watches `.venv` too — start it with `--reload-dir app`.
- **Windows dev server cannot hold >~500 sockets**: with `--reload` uvicorn uses the select()-based loop (512 fd cap) and the
  worker dies with `ValueError: too many file descriptors in select()`; the reloader does not restart it (touch a file in
  `app/` to revive). Load-test against a second instance started *without* `--reload` (Proactor loop), e.g. `--port 8001`.
  Production (Linux/Docker, epoll) has no such cap.
- **Load generators on Windows**: a fresh TCP connection per request costs ~200 ms and serialises (~4 req/s); use one
  keep-alive client (`benchmarks/load_test.py` and the login probe do), or run the generator from a Linux container.
- Argon2id is at OWASP cost (19 MiB, t=2, p=1): ~70 verifies/s on an 8-thread laptop vs ~13/s at the old 64 MiB/t=3 (memory-
  bandwidth bound, no thread scaling). Old hashes verify and are re-hashed on the next login; verification runs via
  `asyncio.to_thread` so it never blocks the event loop.
- Benchmark on an otherwise idle CPU; background load skews every stage.
- `zoneinfo` on Windows needs the `tzdata` package (already in requirements).
- **Client IP**: `client_ip` returns `request.client.host` only — never parse `X-Forwarded-For` in the app (the first entry is
  client-chosen and bypassed every per-IP limit). Uvicorn resolves it from trusted proxies (`FORWARDED_ALLOW_IPS`, default
  127.0.0.1); nginx must *overwrite* it (`$remote_addr`), not append, because the API runs with `--forwarded-allow-ips '*'`.
  Load generators on localhost may still send a distinct `X-Forwarded-For` per simulated device (`benchmarks/locustfile.py`).
- SFace's ONNX graph has a fixed batch of 1 — flip test-time augmentation is two runs, not a batch.
- Async SQLAlchemy: never touch lazy relationships after the session's greenlet context; use bulk
  deletes (see `purge_biometrics`).
- Tailwind v4 `@theme` vars resolve at `:root`; surface/ink tokens live in `@theme inline` so
  `.theme-dark` subtrees (kiosk, login panel) can override them.
- Liveness scores for a real webcam sit around 0.6–0.85; use medians and patience, not a single
  high threshold.
- Don't run the vendored `tools/third_party/minifasnet/MiniFASNet.py`; the export script has its
  own architecture definition that loads the published state_dict.
