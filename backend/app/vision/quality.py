"""Image/face quality gates and coarse head-pose estimation from 5 landmarks."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.core.config import settings
from app.vision.detector import Face


@dataclass(slots=True)
class Quality:
    ok: bool
    score: float
    brightness: float
    sharpness: float
    yaw: float  # degrees, + = subject turned to their left (nose moves to image right)
    pitch: float
    roll: float
    issues: list[str] = field(default_factory=list)


def head_pose(face: Face) -> tuple[float, float, float]:
    """Coarse yaw/pitch/roll in degrees from eye/nose/mouth geometry. Good enough for a
    turn-left/right challenge and pose gating; not a metric pose estimate."""
    re, le, nose, rm, lm = face.landmarks
    eye_mid = (re + le) / 2
    mouth_mid = (rm + lm) / 2
    eye_dist = float(np.linalg.norm(le - re)) + 1e-6
    # Horizontal nose offset relative to the eye midpoint, normalised by eye distance.
    yaw_ratio = float((nose[0] - eye_mid[0]) / eye_dist)
    yaw = float(np.clip(yaw_ratio * 90.0, -90, 90))
    # Vertical: nose position between eye line and mouth line.
    face_h = float(np.linalg.norm(mouth_mid - eye_mid)) + 1e-6
    pitch_ratio = float(((nose[1] - eye_mid[1]) / face_h) - 0.55)
    pitch = float(np.clip(pitch_ratio * 120.0, -90, 90))
    roll = float(np.degrees(np.arctan2(le[1] - re[1], le[0] - re[0])))
    return yaw, pitch, roll


def assess(bgr: np.ndarray, face: Face, *, min_size: int | None = None, max_yaw: float = 35.0) -> Quality:
    min_size = min_size or settings.min_face_size
    x, y, w, h = face.box
    H, W = bgr.shape[:2]
    issues: list[str] = []

    crop = bgr[max(0, y) : min(H, y + h), max(0, x) : min(W, x + w)]
    if crop.size == 0:
        return Quality(False, 0.0, 0, 0, 0, 0, 0, ["face_out_of_frame"])
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    yaw, pitch, roll = head_pose(face)

    if face.size < min_size:
        issues.append("too_small")
    if x < 0 or y < 0 or x + w > W or y + h > H:
        issues.append("partially_out_of_frame")
    if brightness < 55:
        issues.append("too_dark")
    elif brightness > 225:
        issues.append("too_bright")
    if sharpness < 25:
        issues.append("blurry")
    if abs(yaw) > max_yaw:
        issues.append("turned")
    if abs(roll) > 25:
        issues.append("tilted")
    if face.score < settings.detector_score_threshold:
        issues.append("low_confidence")

    size_term = min(1.0, face.size / (min_size * 1.6))
    light_term = 1.0 - min(1.0, abs(brightness - 130) / 110)
    sharp_term = min(1.0, sharpness / 250)
    pose_term = 1.0 - min(1.0, abs(yaw) / 60)
    score = float(np.clip(0.3 * size_term + 0.2 * light_term + 0.25 * sharp_term + 0.25 * pose_term, 0, 1))
    return Quality(not issues, score, brightness, sharpness, yaw, pitch, roll, issues)


GUIDANCE = {
    "no_face": "Position your face inside the frame",
    "multiple_faces": "Only one person should be in view",
    "too_small": "Move closer to the camera",
    "partially_out_of_frame": "Centre your face in the frame",
    "too_dark": "Find better lighting — your face is too dark",
    "too_bright": "Too much light — move away from the glare",
    "blurry": "Hold still for a moment",
    "turned": "Look straight at the camera",
    "tilted": "Keep your head level",
    "low_confidence": "Face not clear — adjust your position",
}
