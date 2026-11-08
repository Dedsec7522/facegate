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
  Employee usernames = lower-cased employee code (e.g. `tka001`).
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
                            SFace (Apache-2.0, fallback), MiniFASNet V1SE + V2 (Apache-2.0)
  tools/seed.py             admin/demo seeding;  tools/export_pad_onnx.py  one-off torch→ONNX export
  tests/                    pytest (SQLite via aiosqlite); benchmarks/ latency + 300-client load test
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
  (parallelism comes from the pool); detection on a `DETECT_MAX_SIDE`=320 copy with landmarks mapped back
  to full resolution; a session stops embedding after `EMBED_MAX_FRAMES`=6.
- **Templates** are AES-256-GCM encrypted with `TEMPLATE_KEY` (AAD = template id). Rotating the
  key means re-enrolling everyone — by design.
- **Portal insights** `GET /attendance/me/insights?days=30` averages check-in/out times in the
  org timezone; "black points" = late arrivals + missed logouts.

## Working on it

```bash
# backend (Python 3.12+; a .venv already exists on the dev machine)
cd backend && .venv/Scripts/python -m pytest -q          # must stay green (22 tests)
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
- The OpenCV Zoo **int8** SFace files are ~7x *slower* than fp32 on ONNX Runtime (ConvInteger) and the
  `int8bq` file doesn't load in ORT at all. The old opset-8 ArcFace R100 ONNX fails ORT's BatchNorm check
  (OpenVINO reads it) and costs ~360 ms/face — too slow.
- Vision/e2e tests skip without `tests/data/synth_face_*.jpg` (git-ignored). Real photos used there may
  score low on passive PAD (LFW photos: ~0.42) and fail the e2e enrolment liveness gate; run that test with `PAD_LIVE_THRESHOLD=0.3` when using such images.
- Uvicorn `--reload` watches `.venv` too — start it with `--reload-dir app`.
- Benchmark on an otherwise idle CPU; background load skews every stage.
- `zoneinfo` on Windows needs the `tzdata` package (already in requirements).
- SFace's ONNX graph has a fixed batch of 1 — flip test-time augmentation is two runs, not a batch.
- Async SQLAlchemy: never touch lazy relationships after the session's greenlet context; use bulk
  deletes (see `purge_biometrics`).
- Tailwind v4 `@theme` vars resolve at `:root`; surface/ink tokens live in `@theme inline` so
  `.theme-dark` subtrees (kiosk, login panel) can override them.
- Liveness scores for a real webcam sit around 0.6–0.85; use medians and patience, not a single
  high threshold.
- Don't run the vendored `tools/third_party/minifasnet/MiniFASNet.py`; the export script has its
  own architecture definition that loads the published state_dict.
