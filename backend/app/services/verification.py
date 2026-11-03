"""Streaming verification sessions (attendance kiosk) and enrolment capture sessions.

A session lives in memory for a short TTL. The browser streams JPEG frames; every frame is analysed
by the vision pipeline and the session accumulates evidence:
  * passive PAD live-probabilities (must average >= threshold over >= pad_min_frames frames)
  * an active head-turn challenge chosen by the server and verified from landmark geometry
  * face embeddings (must be mutually consistent and >= embed_min_frames of them)
Only when all three are satisfied is the aggregated embedding matched. The result is bound to a
single-use verification token that the attendance endpoint consumes."""
from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from dataclasses import dataclass, field

import numpy as np

from app.core.config import settings
from app.vision.embedder import normalize
from app.vision.pipeline import FrameAnalysis, get_pipeline
from app.vision.quality import GUIDANCE

CHALLENGES = ("turn_left", "turn_right")
CHALLENGE_TEXT = {"turn_left": "Slowly turn your head to the left", "turn_right": "Slowly turn your head to the right"}
YAW_TRIGGER = 18.0  # degrees of estimated yaw that counts as "turned"
YAW_CENTRE = 9.0
ENROL_POSES = ("front", "left", "right", "up", "down")
POSE_TEXT = {
    "front": "Look straight at the camera",
    "left": "Turn your head slightly to the left",
    "right": "Turn your head slightly to the right",
    "up": "Tilt your head slightly up",
    "down": "Tilt your head slightly down",
}


@dataclass(slots=True)
class Session:
    id: str
    purpose: str  # attendance | enrolment
    nonce: str
    created: float
    ip: str | None
    user_agent: str | None
    challenge: str | None
    employee_id: str | None = None  # enrolment target
    require_challenge: bool = True
    pad_threshold: float = settings.pad_live_threshold
    accept_threshold: float = settings.match_accept_threshold
    frames: int = 0
    last_frame_at: float = 0.0
    live_probs: list[float] = field(default_factory=list)
    embeddings: list[np.ndarray] = field(default_factory=list)
    yaw_history: list[float] = field(default_factory=list)
    challenge_state: str = "pending"  # pending | turned | passed | failed
    done: bool = False
    result: dict | None = None
    token_used: bool = False
    # enrolment
    poses: dict[str, tuple[np.ndarray, float, np.ndarray]] = field(default_factory=dict)  # pose -> (emb, quality, aligned)
    pose_hold: dict[str, int] = field(default_factory=dict)
    consent_version: str | None = None

    @property
    def age(self) -> float:
        return time.monotonic() - self.created

    @property
    def expired(self) -> bool:
        return self.age > settings.verify_session_ttl_seconds


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create(self, purpose: str, *, ip: str | None, user_agent: str | None, require_challenge: bool = True,
                     pad_threshold: float | None = None, accept_threshold: float | None = None,
                     employee_id: str | None = None, consent_version: str | None = None) -> Session:
        async with self._lock:
            self._gc()
            s = Session(
                id=str(uuid.uuid4()),
                purpose=purpose,
                nonce=secrets.token_urlsafe(16),
                created=time.monotonic(),
                ip=ip,
                user_agent=user_agent,
                challenge=secrets.choice(CHALLENGES) if (purpose == "attendance" and require_challenge) else None,
                employee_id=employee_id,
                require_challenge=require_challenge,
                pad_threshold=pad_threshold or settings.pad_live_threshold,
                accept_threshold=accept_threshold or settings.match_accept_threshold,
                consent_version=consent_version,
            )
            if s.challenge is None:
                s.challenge_state = "passed"
            self._sessions[s.id] = s
            return s

    def get(self, sid: str) -> Session | None:
        s = self._sessions.get(sid)
        if s and s.expired:
            self._sessions.pop(sid, None)
            return None
        return s

    def drop(self, sid: str) -> None:
        self._sessions.pop(sid, None)

    def _gc(self) -> None:
        for sid, s in list(self._sessions.items()):
            if s.expired:
                self._sessions.pop(sid, None)

    @property
    def active(self) -> int:
        return len(self._sessions)

    # ---------------------------------------------------------------------------------------
    def public(self, s: Session) -> dict:
        return {
            "session_id": s.id,
            "nonce": s.nonce,
            "purpose": s.purpose,
            "challenge": s.challenge,
            "challenge_text": CHALLENGE_TEXT.get(s.challenge or "", None),
            "ttl_seconds": settings.verify_session_ttl_seconds,
            "poses": list(ENROL_POSES) if s.purpose == "enrolment" else None,
        }

    def rate_ok(self, s: Session) -> bool:
        now = time.monotonic()
        if s.last_frame_at and (now - s.last_frame_at) < 1.0 / settings.max_stream_fps:
            return False
        s.last_frame_at = now
        return True

    # ---- attendance --------------------------------------------------------------------------
    async def process_attendance_frame(self, s: Session, bgr: np.ndarray) -> dict:
        pipe = get_pipeline()
        a: FrameAnalysis = await pipe.analyse_async(bgr, want_embedding=True, want_pad=True, max_yaw=60.0)
        s.frames += 1
        resp = self._frame_feedback(a, s)
        if a.state != "ok":
            return resp

        q = a.quality
        yaw = q.yaw if q else 0.0
        s.yaw_history.append(yaw)
        self._advance_challenge(s, yaw)

        # Evidence is only collected while the face is roughly frontal (clean embeddings / PAD crops).
        if abs(yaw) <= 25:
            if a.live_prob is not None:
                s.live_probs.append(a.live_prob)
            if a.embedding is not None:
                s.embeddings.append(a.embedding)

        live_avg = float(np.median(s.live_probs)) if s.live_probs else 0.0  # median: robust to a few bad frames
        resp.update(
            {
                "liveness": {"frames": len(s.live_probs), "needed": settings.pad_min_frames, "score": round(live_avg, 3),
                             "passed": len(s.live_probs) >= settings.pad_min_frames and live_avg >= s.pad_threshold},
                "challenge": {"name": s.challenge, "state": s.challenge_state, "text": CHALLENGE_TEXT.get(s.challenge or "")},
                "yaw": round(yaw, 1),
                "embeddings": len(s.embeddings),
            }
        )

        enough_pad = len(s.live_probs) >= settings.pad_min_frames
        enough_emb = len(s.embeddings) >= settings.embed_min_frames
        if enough_pad and live_avg < s.pad_threshold and len(s.live_probs) >= settings.pad_reject_min_frames:
            return self._finish(s, {"state": "rejected", "reason": "spoof", "message": "Liveness check failed. Please use the live camera, not a photo or screen.",
                                    "liveness_score": live_avg})
        if s.challenge_state == "failed":
            return self._finish(s, {"state": "rejected", "reason": "challenge_failed", "message": "Head-turn check was not completed.", "liveness_score": live_avg})
        if enough_pad and live_avg >= s.pad_threshold and s.challenge_state == "passed" and enough_emb:
            return self._identify(s, live_avg)
        if s.age > settings.verify_session_ttl_seconds - 5:
            return self._finish(s, {"state": "rejected", "reason": "timeout", "message": "Verification timed out. Please try again.", "liveness_score": live_avg})
        resp["state"] = "collecting"
        return resp

    def _advance_challenge(self, s: Session, yaw: float) -> None:
        if s.challenge is None or s.challenge_state in ("passed", "failed"):
            return
        # Sign convention from quality.head_pose: nose moving to image-right (+yaw) = subject turned to THEIR left
        # as seen in a mirrored selfie preview, which is what the user perceives as "left".
        want_positive = s.challenge == "turn_left"
        turned = (yaw > YAW_TRIGGER) if want_positive else (yaw < -YAW_TRIGGER)
        wrong = (yaw < -YAW_TRIGGER * 1.6) if want_positive else (yaw > YAW_TRIGGER * 1.6)
        if s.challenge_state == "pending":
            if turned:
                s.challenge_state = "turned"
            elif wrong and len(s.yaw_history) > 6:
                # turning decisively the wrong way is tolerated once; sustained wrong direction fails
                if sum(1 for y in s.yaw_history[-6:] if ((y < -YAW_TRIGGER) if want_positive else (y > YAW_TRIGGER))) >= 5:
                    s.challenge_state = "failed"
        elif s.challenge_state == "turned" and abs(yaw) < YAW_CENTRE:
            s.challenge_state = "passed"

    def _identify(self, s: Session, live_avg: float) -> dict:
        pipe = get_pipeline()
        embs = np.stack(s.embeddings)
        mean = normalize(embs.mean(axis=0))
        # Internal consistency: all frames should agree with the mean (guards against face swaps mid-session).
        consistency = float((embs @ mean).min())
        if consistency < 0.45:
            return self._finish(s, {"state": "rejected", "reason": "inconsistent", "message": "The face changed during verification. Please try again.",
                                    "liveness_score": live_avg, "match_score": None})
        m = pipe.index.match(mean, accept=s.accept_threshold)
        base = {"liveness_score": round(live_avg, 3), "match_score": round(m.score, 3), "second_score": round(m.second_score, 3),
                "second_employee_id": m.second_employee_id, "frames": s.frames}
        if m.decision == "identified":
            return self._finish(s, {"state": "identified", "employee_id": m.employee_id, **base})
        if m.decision == "ambiguous":
            return self._finish(s, {"state": "rejected", "reason": "ambiguous", "message": "We could not tell you apart from another enrolled person. Please try again or ask an administrator.", **base})
        return self._finish(s, {"state": "rejected", "reason": "unknown", "message": "Face not recognised. You may not be enrolled yet.", **base})

    def _finish(self, s: Session, result: dict) -> dict:
        s.done = True
        s.result = result
        return {**result, "session_id": s.id}

    # ---- enrolment ---------------------------------------------------------------------------
    async def process_enrolment_frame(self, s: Session, bgr: np.ndarray) -> dict:
        pipe = get_pipeline()
        a = await pipe.analyse_async(bgr, want_embedding=True, want_pad=True, max_yaw=40.0)
        s.frames += 1
        resp = self._frame_feedback(a, s)
        remaining = [p for p in ENROL_POSES if p not in s.poses]
        target = remaining[0] if remaining else None
        resp["poses"] = {"captured": list(s.poses), "target": target, "text": POSE_TEXT.get(target or "", "All poses captured")}
        if a.state != "ok" or target is None:
            resp["state"] = "collecting" if target else "complete"
            return resp
        q = a.quality
        if a.live_prob is not None:
            s.live_probs.append(a.live_prob)
        yaw, pitch = q.yaw, q.pitch
        ok_pose = {
            "front": abs(yaw) < 10 and abs(pitch) < 12,
            "left": yaw > 12 and yaw < 40,
            "right": yaw < -12 and yaw > -40,
            "up": pitch < -8 and abs(yaw) < 15,
            "down": pitch > 10 and abs(yaw) < 15,
        }[target]
        resp["pose_ok"] = ok_pose
        resp["yaw"], resp["pitch"] = round(yaw, 1), round(pitch, 1)
        if ok_pose and q.score >= 0.45:
            s.pose_hold[target] = s.pose_hold.get(target, 0) + 1
            if s.pose_hold[target] >= 2:  # need two consecutive good frames in the pose
                s.poses[target] = (a.embedding, q.score, a.aligned)
                remaining = [p for p in ENROL_POSES if p not in s.poses]
                resp["poses"] = {"captured": list(s.poses), "target": remaining[0] if remaining else None,
                                 "text": POSE_TEXT.get(remaining[0], "All poses captured") if remaining else "All poses captured",
                                 "just_captured": target}
        else:
            s.pose_hold[target] = 0
        live_avg = float(np.median(s.live_probs)) if s.live_probs else 0.0
        resp["liveness"] = {"frames": len(s.live_probs), "score": round(live_avg, 3), "passed": len(s.live_probs) >= settings.pad_min_frames and live_avg >= s.pad_threshold}
        resp["state"] = "complete" if len(s.poses) == len(ENROL_POSES) else "collecting"
        return resp

    # ---- shared -----------------------------------------------------------------------------
    @staticmethod
    def _frame_feedback(a: FrameAnalysis, s: Session) -> dict:
        face = a.face
        box = list(face.box) if face else None
        lm = face.landmarks.round(1).tolist() if face else None
        if a.state == "no_face":
            guidance, issues = GUIDANCE["no_face"], ["no_face"]
        elif a.state == "multiple_faces":
            guidance, issues = GUIDANCE["multiple_faces"], ["multiple_faces"]
        elif a.state == "quality":
            issues = a.quality.issues if a.quality else []
            guidance = GUIDANCE.get(issues[0], "Adjust your position") if issues else "Hold still"
        else:
            guidance, issues = "Hold still", []
        return {
            "state": a.state,
            "frame": s.frames,
            "face": {"box": box, "landmarks": lm, "score": round(face.score, 3)} if face else None,
            "faces": len(a.faces),
            "issues": issues,
            "guidance": guidance,
            "quality": round(a.quality.score, 2) if a.quality else None,
            "timings_ms": {k: round(v, 1) for k, v in a.timings_ms.items()},
        }


manager = SessionManager()
