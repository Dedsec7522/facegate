# Security and privacy

## Controls implemented

| Area | Control | Where |
|---|---|---|
| Passwords | Argon2id (64 MiB, t=3), constant-time compare, dummy verify for unknown emails | `app/core/security.py`, `api/v1/auth.py` |
| Lockout | 5 failed logins → 15-minute lock; per-IP login limiter 10/min (and Nginx 5/min) | `auth.py`, `core/rate_limit.py`, `deploy/nginx` |
| MFA | TOTP (RFC 6238) with QR provisioning; secret stored AES-GCM encrypted; required at login once enabled | `auth.py` |
| Sessions | 15-min access JWT + 7-day rotating refresh token (only SHA-256 hash stored, revocable); HttpOnly, Secure, SameSite=Strict cookies | `auth.py`, `refresh_sessions` table |
| RBAC | `admin` / `hr` / `employee` enforced by FastAPI dependencies on every route; employees can only read their own records | `core/deps.py` |
| Biometric templates | 128-float vectors encrypted with AES-256-GCM (`TEMPLATE_KEY`, AAD = template id); decrypted only into process memory; never returned by any API | `core/crypto.py`, `services/index.py` |
| Image minimisation | Frames are processed in memory and discarded; only one 112×112 aligned thumbnail per active enrolment is retained (toggle `KEEP_ENROL_THUMBNAIL`) | `services/enrolment.py` |
| Replay / injection | Server nonce per session, frame-rate cap, session TTL 120 s, embedding consistency check across frames, single-use verification token (JTI) bound to session + employee, 90 s TTL | `services/verification.py`, `api/v1/attendance.py` |
| Liveness | Passive PAD (two MiniFASNet models) averaged over ≥4 frames + server-chosen head-turn challenge; both must pass before matching | `services/verification.py` |
| Identification | Accept threshold + margin to the second-best identity → `ambiguous` rather than a guess; inactive employees are removed from the index immediately | `vision/matcher.py`, `employees.py` |
| Audit | Append-only `audit_log` for every admin action (before/after JSON, actor, IP); every verification attempt (success or failure) in `verification_attempts` | `services/audit.py` |
| Corrections | Original events are never mutated; corrections void + add with mandatory reason and actor | `services/attendance.py` |
| Non-biometric path | Only an admin-enabled per-employee PIN (Argon2id hashed) or an audited manual correction; both are labelled `method=pin|manual` in every report | `attendance.py` |
| Transport | TLS 1.2/1.3 via Nginx, HSTS, CSP, X-Frame-Options DENY, Permissions-Policy camera=(self) | `deploy/nginx/nginx.conf`, `app/main.py` |
| Backups | Nightly `pg_dump` with 14-day retention (compose `backup` service) | `deploy/docker-compose.yml` |
| Retention / erasure | Admin can revoke (keeps history) or purge (hard-delete templates + thumbnails) per employee; both audited | `DELETE /employees/{id}/biometrics` |

**There are no hidden bypasses.** Every path that writes an attendance event is listed above and each one is visible in the audit trail and reports.

## Known limitations (read before production)

1. **RGB-only liveness.** MiniFASNet resists printed photos and phone/monitor replays well in the vendor's evaluation (97.8 % TPR @ 1e-5 FPR) and our local trials, but it is not ISO/IEC 30107-3 certified and will not stop a high-quality 3D mask or a compromised camera driver injecting frames. For hostile environments pair the kiosk with an IR/depth camera and extend `PresentationAttackDetector` with a depth channel.
2. **Camera-level injection.** Browser-based capture cannot attest that frames come from a physical sensor. Deploy kiosks as managed devices (kiosk-mode browser, no USB) if this threat matters.
3. **Single-node rate limiting and token replay cache** live in process memory; when running more than one API replica, move both to Redis (the interfaces are isolated in `core/rate_limit.py` and `attendance._consume`).
4. **Thresholds are calibrated on synthetic faces and a small live trial**; collect ~50 real enrolments and run `benchmarks/` plus a manual FAR/FRR sweep before fixing `MATCH_ACCEPT_THRESHOLD` for your population.
5. **Legal.** Facial templates are special-category biometric data (UK GDPR Art. 9 / EU GDPR). Complete a DPIA, document the lawful basis (typically explicit consent, which the enrolment flow records with version and timestamp), publish the privacy notice shown at enrolment, and define a retention schedule. Some jurisdictions (e.g. Illinois BIPA) require written consent before collection.

## Operational checklist

- Generate unique `SECRET_KEY` and `TEMPLATE_KEY`; store `TEMPLATE_KEY` in a secrets manager — losing it makes all templates unrecoverable (by design); rotating it requires re-enrolment.
- Enable MFA for every admin on first login (Settings → My security).
- Restrict `/api/docs` (disabled automatically when `ENVIRONMENT=production`).
- Keep `deploy/backups/` on encrypted storage; test a restore quarterly.
