# Test and benchmark results

Machine: Windows 11, Intel i5-1135G7 (4 cores / 8 threads, 2.4 GHz), 16 GB RAM, **no GPU**, Python 3.13, ONNX Runtime 1.31 CPU, OpenCV 4.14, Postgres 16 in Docker. Date: 2026-11-03.

## 1. Automated tests (`backend/tests`, 21 passed)

| File | What is verified |
|---|---|
| `test_attendance_engine.py` (4) | overnight day boundary incl. BST; check-out without check-in rejected; late minutes after grace; duplicate scan inside window rejected; double check-in rejected; worked minutes across two sessions; early-leave minutes; inactive employee rejected; corrections require a reason, void + adjust + add recompute the day and preserve before/after JSON |
| `test_vision.py` (6) | no-face and multiple-face detection; dark / too-small frames fail quality gates; same identity stable under brightness, resolution and mirroring (cosine > 0.6); identification rules (self-match > 0.95, unknown rejected, near-duplicate → `ambiguous`, empty index → no decision); alignment shape; per-frame latency budget |
| `test_api.py` (7) | wrong password 401; unauthenticated 401; employee role gets 403 on admin routes but 200 on own status; employee CRUD + conflict + audit entries; verification token single-use (replay 409) and garbage token 401; PIN fallback refused until an admin sets a PIN, then recorded as `method=pin`; settings patch + dashboard + CSV export; public session creation returns nonce + challenge |
| `test_bound_verification.py` (2) | portal 1:1 mode: another person's face in your portal → `mismatch` (never identified as them); own face → identified as you only; account without enrolment → `not_enrolled`; kiosk (unbound) still identifies 1:N; `POST /verify/sessions/me` → 401 anonymous, 404 for accounts without an employee, 200 + bound session for an employee |
| `test_e2e_stream.py` (2) | **full loop**: enrol a synthetic face through `commit_enrolment` → duplicate-identity guard raises for a second employee → kiosk WebSocket with real JPEG frames identifies the enrolled face (score > 0.8), issues a token, `POST /attendance/events` stores the event, token replay → 409; wrong nonce refused; a different face → `rejected:unknown`; blank frame → `no_face` guidance only. Challenge state machine: turn-and-return passes, no turn stays pending, sustained wrong direction fails |

Frontend: `tsc -b` clean, `vite build` clean (largest chunk: charts 442 kB / 124 kB gzip, lazy-loaded).

## 2. Browser verification (Chrome DevTools MCP, 1440×900 and 375×812)

| Page | Result |
|---|---|
| Landing, Login (incl. MFA step markup), Dashboard, Employees, Employee detail, Attendance (5 tabs), Reports, Settings (5 tabs), Portal, Kiosk | render with **zero console errors/warnings** (only the expected 401 from the anonymous session probe) |
| Login → dashboard → employees → profile → PIN set → kiosk PIN check-in → attendance board shows *Late · On site 19:35* | real browser → API → Postgres → UI loop confirmed |
| Employee account (isolated context) → portal | own status/next action shown; admin routes blocked |
| Mobile 375 px | dashboard stacks to single column, drawer navigation, no horizontal scroll |
| Lighthouse (desktop, `/admin`) | Accessibility **94**, Best practices **100**, SEO 91. Two findings fixed afterwards: dark-mode link contrast (`text-brand-600` → adaptive) and card heading order (`h3` → `h2`). |
| Camera flows (enrolment, face verification) | **Not executable in the in-app browser** (device capture is blocked there) nor in headless DevTools Chrome; the camera-denied error state renders correctly. Live webcam trials must be run by a person in a normal browser — see §5. |

## 3. Latency (`benchmarks/latency.py`, 640×480 frame, warm)

| Stage | p50 | p95 |
|---|---|---|
| YuNet detect | 17.4 ms | 22.0 ms |
| MiniFASNet PAD (2 models) | 6.1 ms | 8.5 ms |
| SFace embed (with flip test-time augmentation, two passes) | 35.3 ms | 50.8 ms |
| **Frame total** | **61.0 ms** | **88.3 ms** |

(Before flip-TTA was added the embed stage was 13.9 ms and a frame 37.5 ms; the extra pass buys a more stable embedding per frame.)
| Match, 50 employees (250 templates) | 0.07 ms | |
| Match, 300 employees (1 500 templates) | 0.44 ms | |
| Match, 1 000 employees (5 000 templates) | 2.6 ms | |

A full verification needs ≥ 4 PAD frames, ≥ 3 embeddings and the head turn: with a 6 fps client that is **≈ 2–4 s** of streaming on an idle server.

## 4. Concurrency (`benchmarks/load_test.py`, real JPEG frames over WebSocket, server on the same laptop)

**Scenario A — 300 verification sessions through 10 concurrent kiosks** (8 frames each, 6 fps client pacing):

| Metric | Value |
|---|---|
| Sessions completed | 300 / 300, 0 errors, 2 400 frames processed |
| Wall time | 187.5 s → **~96 sessions/min** sustained |
| Per-frame round trip | p50 146 ms · p90 475 ms · p95 727 ms · p99 1 118 ms |
| Session (8 frames) | p50 5.1 s · p90 8.7 s · p95 9.7 s |

Interpretation: 300 employees arriving over a 30-minute window is ~10 sessions/min — a tenth of what this 4-core laptop sustained — so the morning peak is well within budget. Ten kiosks verifying at the same instant raise per-frame latency from 40 ms to ~150 ms (p50), which a user perceives as slightly slower frame feedback, not as failure.

**Scenario B — 300 sessions started within 5 s (worst case, every employee on their own phone at once), same laptop:**

| Metric | Value |
|---|---|
| Sessions that streamed to completion | 256 / 300 (all 8 frames processed, no crashes, server health endpoint stayed responsive) |
| Session creations that timed out (30 s client timeout) | **44** — the single event loop was saturated by 300 concurrent WebSocket streams |
| Per-frame round trip | p50 766 ms · p90 1 312 ms · p95 1 543 ms · p99 1 974 ms |
| Session (8 frames) | p50 130 s (clients back off on `busy` replies) |

Interpretation: a 4-core laptop degrades gracefully (no data loss, no wrong decisions, explicit `busy` back-pressure) but it is **not** adequate for 300 truly simultaneous streams. Sizing guidance derived from both runs: budget ~25 frames/s per CPU core; a verification needs ~8–20 frames; so plan ~1 core per 1.5 concurrent kiosks and keep dedicated kiosks (Scenario A) rather than letting 300 phones stream at once. For phone-based check-in, deploy ≥ 2 API nodes behind a sticky-session load balancer or add a GPU (ONNX Runtime CUDA/DirectML provider is a one-line change in `embedder.py`/`pad.py`).

Before the fix recorded in this document (per-IP session limiter at 30/min and JPEG decode on the event loop) the same scenario produced 244 HTTP 429s and 26 connect timeouts; both were corrected (limiter now 120/min per client IP and configurable, decode moved to the inference pool).

## 5. First live webcam trial (2026-11-03, developer's laptop camera)

Six genuine attempts were made at the kiosk before any enrolment existed. Outcome: 1 × `unknown` (correct — nobody enrolled; liveness 0.84, head-turn passed, 38 frames / 6.4 s) and **5 × `spoof` with liveness 0.57–0.80**. The passive PAD models score a real face on this webcam between ~0.55 and ~0.85, so the original 0.80 *mean* threshold was mis-calibrated and the session rejected after only 8 frames. Fix applied: decision uses the **median** per-frame score, default threshold **0.55** (the vendor's own decision is argmax ≈ 0.5), and a session needs ≥ 14 frames of evidence before it is rejected. This is a calibration, not a weakening of the challenge: the head-turn gate is unchanged, and the threshold remains admin-tunable per site.

## 6. Pending manual trials (require a physical camera and a person)

These were **not** executed by the automated run and are not claimed:

| Trial | Expected | How to record |
|---|---|---|
| Enrol 3–5 real employees | all five poses captured in < 60 s each | Settings → Audit log shows `enrolment.create` |
| Genuine check-in / check-out | identified in 2–4 s, correct name, event stored | Attendance → Today |
| Printed photo of an enrolled employee | `rejected:spoof` (PAD) or `challenge_failed` | Attendance → Failed verifications |
| Photo on a phone screen / laptop monitor | `rejected:spoof` | same |
| Pre-recorded video replay on a screen (with head turn) | `rejected:spoof` by PAD moiré/texture cues — this is the hardest case; record the outcome honestly | same |
| Two people in frame | `multiple_faces` guidance, no event | kiosk |
| Non-enrolled person | `rejected:unknown` | Failed verifications |
| Beard/hairstyle change | still identified (threshold margin) | Today board |
| Poor lighting | guidance "Find better lighting", no false accept | kiosk |

Run `backend/benchmarks/load_test.py` again on the production server after deployment and replace §4 with those numbers.
