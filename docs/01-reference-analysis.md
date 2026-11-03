# Reference analysis — `opencv_zoo/models/face_detection_yunet`

Studied strictly for learning and benchmarking. No application code from it is used in FaceGate.

## What the reference actually is

The reference is **not an attendance system**. It is a single-model demo folder in OpenCV Zoo:

| File | Role |
|---|---|
| `face_detection_yunet_2023mar.onnx` / `2026may.onnx` | YuNet detector weights (MIT) |
| `yunet.py` | ~50-line wrapper around `cv.FaceDetectorYN` |
| `demo.py` / `demo.cpp` | Webcam / image demo that draws boxes and 5 landmarks |

### Pipeline (how it works)
1. `cv.FaceDetectorYN.create(model, "", input_size, score_thr, nms_thr, top_k)`
2. `setInputSize([w, h])` must match the frame size.
3. `detect(image)` → `(N, 15)` rows: `x, y, w, h, 5×(lx, ly), score`.
4. Demo draws the results; nothing else.

### Strongest ideas worth keeping
- YuNet is a genuinely good lightweight detector: ~230 KB, CPU real-time, WIDER Face hard-AP 0.75, 5 landmarks suitable for alignment.
- The 15-float output contract is simple and stable.
- OpenCV ships the inference engine, so there is no ML framework dependency.

### Limitations (what it does not do)
| Capability | Reference | Consequence for an attendance product |
|---|---|---|
| Recognition / identity | **None** — detection only | Cannot tell who is in frame |
| Embeddings & matching | None | No one-to-many identification, no thresholds |
| Enrolment | None | No concept of a registered person |
| Liveness / PAD | None | A printed photo is detected exactly like a live face |
| Multi-face policy | Draws all; no decision logic | Would mark the wrong person |
| Quality gating | None | Blurry / dark / tiny faces still produce boxes |
| Persistence, API, auth, audit | None | Nothing to build an app on |
| Replay / injection protection | None | Frames are trusted blindly |
| Concurrency | Single process, blocking loop | Not a service |
| Default conf threshold 0.9 (demo) vs 0.6 (wrapper) | Inconsistent | Misses small/angled faces or accepts junk |
| `2026may` model needs OpenCV 5 ONNX engine | Version coupling | Stock `pip install opencv-python` 4.x fails on the default model |

## How FaceGate improves on it (to be measured, not assumed)

| Area | Reference | FaceGate design | How it is verified |
|---|---|---|---|
| Detection | YuNet demo | YuNet (MIT) via OpenCV's standard `FaceDetectorYN` API, plus quality gates (size, blur, brightness, pose) before anything downstream | Unit tests on synthetic/real frames; latency benchmark |
| Recognition | none | SFace (Apache-2.0) 128-d embeddings with own 5-point similarity alignment, multi-template enrolment, cosine matching with calibrated accept / ambiguity margins | Identification tests: known / unknown / ambiguous / multi-face / no-face |
| Liveness | none | Passive PAD (MiniFASNet V1SE + V2, Apache-2.0, 80×80 crops at scale 2.7 & 4.0, ONNX) fused over several frames **and** a server-issued head-turn challenge verified from landmark geometry, nonce-bound | Print / phone-screen / video replay trials with documented pass/fail counts |
| Replay / injection | none | Per-session nonce, server timestamps, frame-order and rate checks, single-use verification token bound to session + identity, short TTL | Automated replay test (resubmit captured frames and tokens) |
| Enrolment | none | Admin-gated guided capture: lighting/quality coach, 5 poses, liveness during enrolment, duplicate-identity check, encrypted templates, consent record, audit trail | API + browser tests |
| Attendance engine | none | Server-side check-in/out state machine, timezone + overnight shift rules, duplicate-scan window, missing check-out detection, corrections with audit history | Pytest state-machine tests |
| Security | none | Argon2id passwords, TOTP MFA, RBAC enforced in dependencies, HttpOnly secure cookies, CSRF-safe design, rate limiting, audit log, AES-GCM template encryption, retention/deletion | Security review + tests |
| Performance | blocking loop | Async FastAPI, bounded inference thread-pool, in-memory template index (300 × k templates ≈ µs search), WebSocket frame streaming, benchmarked | 300-concurrent load test with measured p50/p95 |
| Deployment | run a script | Docker Compose (Postgres, API, Nginx TLS), migrations, env templates, README | Fresh-machine bring-up documented |

See `docs/02-architecture.md` for the independent design.
