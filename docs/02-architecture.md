# FaceGate — architecture

Self-hosted corporate face-attendance platform. No cloud biometric APIs. All inference runs on the server CPU (GPU optional).

## 1. System overview

```
Browser (React/TS)                       API (FastAPI, async)                       Postgres 16
──────────────────                       ────────────────────                       ───────────
Kiosk / Enrolment  ──WebSocket frames──▶ VerificationSession (in-memory, TTL) ──▶ verification_attempts
   getUserMedia                           ├─ YuNet detect + quality gate            attendance_events
   JPEG @ ~6 fps                          ├─ MiniFASNet PAD (2 scales, fused)       attendance_days
                                          ├─ head-turn challenge (nonce)            employees / users
Admin & Employee   ──REST (cookies)──▶    ├─ SFace embed → TemplateIndex (RAM)      face_templates (AES-GCM)
   portals                                └─ single-use verification token           audit_log, corrections …
                                         AttendanceEngine (rules, tz, shifts)
```

Inference is CPU-bound and runs in a bounded `ThreadPoolExecutor` (size = `INFERENCE_WORKERS`), so the event loop never blocks and load is shed with a clear `busy` message instead of unbounded queueing.

## 2. Biometric pipeline (independent implementation)

| Stage | Model / method | Licence | Notes |
|---|---|---|---|
| Detect + 5 landmarks | YuNet 2023mar via `cv2.FaceDetectorYN` | MIT | OpenCV's standard face API; weights vendored with SHA-256 in `backend/models/` |
| Quality gate | own code | — | min face size, Laplacian blur, brightness range, max yaw/roll from landmarks, single-face rule |
| Align | own code | — | 5-point similarity transform → 112×112 (ArcFace-style reference template) |
| Embed | SFace 2021dec (ONNX Runtime) | Apache-2.0 | 128-d, L2-normalised, horizontal-flip test-time augmentation (two passes averaged); 3 required frontal samples + optional left/right per enrolment; **adaptive templates**: a confident, live-verified identification (score ≥ 0.65, margin ≥ 0.15) adds the session embedding as an extra template (max 10 per employee, oldest adaptive dropped first) so recognition follows beards, glasses and haircuts |
| Match | own code | — | cosine similarity against in-memory index; accept ≥ `MATCH_ACCEPT` (default 0.40, SFace-calibrated) **and** top-1 − top-2 (different identity) ≥ `MATCH_MARGIN` (0.08); otherwise `unknown` / `ambiguous` |
| Passive PAD | MiniFASNet V1SE (scale 4.0) + V2 (scale 2.7), ONNX, 80×80 | Apache-2.0 | softmax over [spoof, live, spoof]; scores averaged across models and across frames |
| Active challenge | own code | — | server picks `turn_left` / `turn_right`; yaw estimated from nose-vs-eye geometry over consecutive frames; must complete within session |
| Replay guard | own code | — | session nonce, server-side frame counter & timestamps, max frame rate, TTL 90 s, token single-use |

Stated limitation: RGB-only PAD resists prints and phone/monitor replays reasonably (model vendor reports 97.8 % TPR @ 1e-5 FPR on their data) but is **not** a certified ISO 30107-3 PAD and cannot stop a compromised camera device. For hostile environments, IR/depth hardware is recommended (see `docs/06-security-and-privacy.md`).

### Two verification modes

| Mode | Where | Decision |
|---|---|---|
| 1:N identification | Kiosk (`POST /verify/sessions`, anonymous) | best employee over the whole index with accept threshold + margin |
| **1:1 verification bound to the account** | Employee portal (`POST /verify/sessions/me`, authenticated) | only the signed-in employee's templates are compared; anyone else's face → `mismatch`; the WebSocket hello must carry that account's token and the issued attendance token can only name that employee — nobody can log in or out from another person's portal |

## 3. Verification flow (no success before the DB commit)

1. `POST /api/v1/verify/sessions` → `{session_id, nonce, challenge}` (rate-limited per IP).
2. `WS /api/v1/verify/stream/{session_id}` — client sends binary JPEG frames; server replies JSON per frame: `{faces, guidance, quality, liveness_progress, challenge_state}`.
3. When PAD ≥ threshold over ≥ N frames, the challenge passed, and ≥ M good embeddings were collected, the server matches and sends `{state: "identified", employee, token}` or `{state: "rejected", reason}`.
4. `POST /api/v1/attendance/events {token, action}` → engine validates rules → inserts `attendance_events` row → returns the stored record. The UI only shows success after this response.

## 4. Attendance engine rules (server-side, configurable in `app_settings`)

- Timezone per organisation; attendance day boundary at `day_start` (default 04:00) so overnight shifts stay on one day.
- `check_in` allowed when no open session for the day; `check_out` requires an open session.
- Duplicate-scan window (default 120 s) rejects repeated events.
- Late = check-in after `work_start + grace`; early-leave = check-out before `work_end`.
- Missing check-out: daily job (and on-demand) flags open sessions after `auto_close_after` hours.
- Corrections: admin creates a correction row (old/new, reason) → engine recomputes the day summary; original event rows are never mutated.

## 5. Data model (PostgreSQL, Alembic)

`departments`, `employees`, `user_accounts` (admin/employee login, Argon2id, TOTP secret encrypted), `biometric_enrolments` (consent, status, quality, created_by), `face_templates` (AES-GCM blob of 128-float, per-pose, enrolment FK), `verification_attempts` (outcome, scores, reason, ip, session), `attendance_events` (immutable), `attendance_days` (derived summary), `attendance_corrections`, `audit_log` (actor, action, target, before/after JSON, ip), `app_settings`, `refresh_sessions`.

Vector search: 300 employees × 5 templates = 1 500 × 128 floats = 768 KB; brute-force NumPy cosine is ~0.1 ms. pgvector is therefore not used (templates stay encrypted at rest; the index is rebuilt from DB on startup and on enrolment changes via a version counter).

## 6. Security model

- Auth: Argon2id; access JWT (15 min) + rotating refresh token (HttpOnly, Secure, SameSite=Strict cookies); TOTP MFA for admins; login rate-limit + lockout.
- RBAC enforced by FastAPI dependencies (`require_role`), never by the client.
- Biometric templates encrypted with AES-256-GCM (`TEMPLATE_KEY`), never logged, never returned by API; raw enrolment images are discarded after embedding (only a small aligned thumbnail kept if `KEEP_ENROL_THUMBNAIL=true`).
- Every admin action and every verification attempt is written to `audit_log` / `verification_attempts`.
- No hidden bypasses: the only non-biometric path is the explicit, audited **manual attendance by an admin** (`attendance_corrections` with reason) and an employee **PIN fallback** that must be enabled per employee by an admin and is logged as `method=pin`.

## 7. Repository layout

```
backend/   FastAPI app, Alembic, vision pipeline, tests, benchmarks
frontend/  React 19 + TS + Tailwind v4 + Motion, Vite
deploy/    docker-compose.yml, nginx, env templates, TLS
docs/      analysis, architecture, design system, testing, licences
```

## 8. Phased plan

1. Backend core: config, DB, models, migrations, auth, RBAC, audit.
2. Vision: detector, quality, align, embed, PAD, matcher, benchmarks.
3. Enrolment + verification stream + attendance engine + reports.
4. Design system + frontend shell + all pages + motion.
5. Browser integration testing (Chrome DevTools), load test, security review.
6. Docker Compose, Nginx TLS, README, licence report, comparison report.
