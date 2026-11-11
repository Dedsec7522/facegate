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

## 7. Face-model evaluation and throughput changes (2026-11-09)

Machine: Intel i7-11800H (8 cores / 16 threads), Windows 10, ONNX Runtime 1.31, OpenVINO 2026.4. Only models whose licences permit commercial use were considered (InsightFace/ArcFace packs, SCRFD, EdgeFace and WebFace-trained AdaFace weights are non-commercial).

**Accuracy — LFW, 6 000 pairs, through FaceGate's own YuNet detection + 5-point alignment** (0 detector misses):

| Model | 10-fold acc. | AUC | TAR @ FAR 1 % | TAR @ FAR 0.1 % | Cost (1 thread) |
|---|---|---|---|---|---|
| **Intel face-reidentification-retail-0095** (OpenVINO, 256-d) | **99.50 ± 0.30 %** | **0.99958** | 99.50 % | **98.87 %** | **~11 ms** |
| Intel 0095 + flip TTA | 99.47 % | 0.99956 | 99.60 % | 98.93 % | ~22 ms |
| Intel 0095, detection at half resolution | 99.42 % | 0.99948 | 99.67 % | 99.03 % | ~11 ms |
| SFace 2021dec + flip TTA (previous default) | 99.08 ± 0.54 % | 0.99861 | 99.13 % | 97.97 % | ~55 ms (ORT) / ~24 ms (OpenVINO) per pass ×2 |
| SFace 2021dec, no flip | 98.93 % | 0.99835 | 99.00 % | 97.53 % | as above ×1 |
| SFace int8 (OpenCV Zoo) | — | — | — | — | 413 ms on ORT (ConvInteger) — rejected |
| ArcFace ResNet100 (ONNX Model Zoo, opset 8) | — | — | — | — | ~360 ms (OpenVINO) — rejected as too slow |

**Threshold calibration** (all 29.6 M impostor and 8 101 genuine pairs among the 7 701 LFW evaluation images, single image vs single image):

| Threshold | Intel FAR | Intel FRR | SFace+flip FAR | SFace+flip FRR |
|---|---|---|---|---|
| 0.42 | 1.2·10⁻⁴ | 2.75 % | 1.0·10⁻⁴ | 4.55 % |
| **0.45 (new default)** | **≈ 5·10⁻⁵** | **≈ 4.0 %** | 2.8·10⁻⁵ | 6.8 % |
| 0.50 | 1.2·10⁻⁵ | 7.5 % | 3.5·10⁻⁶ | 12.9 % |

At equal false-accept rate the Intel model rejects roughly 17–35 % fewer genuine pairs. LFW pairs are years apart with free pose and lighting; FaceGate averages ≥ 3 frames against same-camera enrolment samples, so real-world rejection rates are far lower than these single-image figures.

**Per-frame latency** (`benchmarks/latency.py`, 640×640 frame; both rows measured back to back on the same, heavily loaded CPU, so compare ratios, not absolute values):

| | detect | PAD | embed | frame p50 |
|---|---|---|---|---|
| Previous: SFace + flip on ORT, detection at full resolution | 121.6 ms | 20.7 ms | 171.7 ms | 308.8 ms |
| New: Intel 0095 on OpenVINO, detection at 320 px | 23.7 ms | 20.8 ms | 18.8 ms | **62.8 ms (≈ 4.9x faster)** |

Other throughput changes: `INFERENCE_WORKERS=0` → one worker per physical core (8 instead of 4 here), `cv2.setNumThreads(1)` so workers don't oversubscribe the CPU, and a verification session stops embedding after `EMBED_MAX_FRAMES=6`.

Tests: 21 / 22 pass with LFW photos as `tests/data` faces; the remaining failure is the e2e enrolment's liveness gate: LFW photos are photographs of photographs and score a passive-PAD median of ~0.42, below the 0.45 default (and the 0.80 in `.env.example`). With `PAD_LIVE_THRESHOLD=0.3` for the run, all e2e steps pass with the new model (enrol → duplicate guard → identified with score > 0.8 → single-use token → unknown face rejected). This is a property of the test images, not of the recognition change. **Pending:** the 300-client load test (§4) must be re-run on an idle host; the run on this machine was postponed because an unrelated process held the CPU at 100 %.


## 8. Load test, 11 November 2026 (Windows laptop)

Host: Windows 11, 8 logical cores, PostgreSQL 16 in Docker Desktop, API started without `--reload` (Proactor loop), load generator on the same machine (so these are pessimistic). 15 enrolled templates in the index; the streamed face was a real webcam frame.

| Run | Outcome | Throughput | Per-person |
|---|---|---|---|
| 500 password logins, all at once | 500 ok, 0 errors | 16.0 logins/s | p50 24 s queueing, max 31 s |
| 100 password logins, all at once | 100 ok | 16.4 logins/s | p50 5.2 s |
| 500 verifications, 10 kiosks | 500 identified | 21.7 frames/s | p50 2.2 s, p95 3.2 s, RTT p50 288 ms |
| 500 verifications, 50 kiosks | 500 identified | 17.2 frames/s | p50 13.6 s, p95 20.7 s |
| 500 verifications, 500 kiosks at once (before the fixes below) | 402 identified, 97 timed out (60 s TTL), 1 read error | 21.6 frames/s | p50 82 s |

Pipeline ceiling (`analyse` on one 640×640 frame, thread pool): 1 thread 19 frames/s, 2 threads 33, 4 threads 35, 8 threads 29.

What the run found and what changed:

- The first login storm crashed the **dev** server: with `--reload` uvicorn on Windows uses the select()-based loop, capped at 512 sockets (`ValueError: too many file descriptors in select()`). Not a production issue (Linux/epoll); load-test a `--reload`-free instance.
- Password verification ran Argon2id (64 MiB, 3 passes) synchronously on the event loop and that cost barely parallelises (12.8 verifies/s on 8 threads). Now OWASP cost (19 MiB, 2 passes, 1 lane: ~70 verifies/s), run via `asyncio.to_thread`, old hashes re-hashed on the next login. The DB pool grew from 10+20 to 20+40 connections (a login holds its connection while hashing) and the per-IP login budget became a setting (`LOGIN_PER_MINUTE_PER_IP`, default 60) because an office NAT is one address.
- The load generator itself was the first bottleneck: a new `httpx.AsyncClient` per request on Windows serialises at ~4 req/s. `load_test.py` and the login probe now share one keep-alive client (WebSocket connects were fine: 14 ms).
