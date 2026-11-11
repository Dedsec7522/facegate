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


def _region(bgr: np.ndarray, cx: float, cy: float, w: float, h: float) -> np.ndarray | None:
    H, W = bgr.shape[:2]
    x0, y0 = max(0, int(round(cx - w / 2))), max(0, int(round(cy - h / 2)))
    x1, y1 = min(W, int(round(cx + w / 2))), min(H, int(round(cy + h / 2)))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    return bgr[y0:y1, x0:x1]


def _skin_ratio(region: np.ndarray | None) -> float:
    """Share of pixels inside the classic YCrCb skin-chroma box. Works across skin tones; fabric, plastic and
    hair fall outside it, which is what the occlusion check relies on."""
    if region is None:
        return -1.0
    ycrcb = cv2.cvtColor(region, cv2.COLOR_BGR2YCrCb)
    cr, cb = ycrcb[..., 1], ycrcb[..., 2]
    return float(((cr >= 133) & (cr <= 178) & (cb >= 80) & (cb <= 132)).mean())


def _brightness(region: np.ndarray | None) -> float:
    return -1.0 if region is None else float(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).mean())


def occlusion(bgr: np.ndarray, face: Face) -> list[str]:
    """Heuristic partial-cover check from the 5 landmarks, relative to a reference patch of uncovered skin (the most
    skin-like of cheeks, forehead, nose bridge and temples). `covered`: the nose tip and lip areas are not skin-toned
    (mask, scarf), or the brow band just above the eyes is dark and not skin-toned (a cap, hood or hair pulled down
    over the brows). `eyes_covered`: both eye patches are far darker than the reference (dark sunglasses, or a brim
    shadowing the eyes). It is a colour heuristic, not a trained occlusion model: skin-coloured covers and a hand are
    not caught (a hand usually breaks detection instead), and when no reference patch is skin-toned (odd lighting,
    heavy make-up) the check stays silent rather than guessing. Landmark geometry that cannot belong to an uncovered
    frontal face (collapsed by heavy occlusion) is reported as `covered` too."""
    re, le, nose, rm, lm = face.landmarks
    d = float(np.linalg.norm(le - re))
    if d < 12:
        return []
    eye_mid, mouth_mid = (re + le) / 2, (rm + lm) / 2
    face_h = float(np.linalg.norm(mouth_mid - eye_mid))
    if not (0.55 * d <= face_h <= 1.7 * d) or nose[1] <= eye_mid[1] or mouth_mid[1] <= nose[1] + 0.05 * d:
        return ["covered"]
    refs = [
        _region(bgr, re[0] - 0.15 * d, re[1] + 0.5 * d, 0.35 * d, 0.3 * d),  # upper cheeks: bare unless masked
        _region(bgr, le[0] + 0.15 * d, le[1] + 0.5 * d, 0.35 * d, 0.3 * d),
        _region(bgr, eye_mid[0], eye_mid[1] - 0.55 * d, 1.0 * d, 0.3 * d),  # forehead: bare unless hat / fringe
        _region(bgr, eye_mid[0], eye_mid[1] + 0.3 * d, 0.4 * d, 0.25 * d),  # nose bridge
        _region(bgr, re[0] - 0.55 * d, re[1], 0.25 * d, 0.3 * d),  # temples
        _region(bgr, le[0] + 0.55 * d, le[1], 0.25 * d, 0.3 * d),
    ]
    ref_ratios = [_skin_ratio(r) for r in refs]
    ref_ratio = max(ref_ratios)
    if ref_ratio < 0.5:
        return []  # nothing we can trust as "uncovered skin" in this light: make no claim
    ref = refs[int(np.argmax(ref_ratios))]
    issues: list[str] = []
    nose_ratio = _skin_ratio(_region(bgr, nose[0], nose[1] + 0.05 * d, 0.45 * d, 0.35 * d))
    lip_ratio = _skin_ratio(_region(bgr, mouth_mid[0], mouth_mid[1], 0.8 * d, 0.22 * d))
    if 0 <= nose_ratio < 0.3 and 0 <= lip_ratio < 0.3:
        issues.append("covered")
    ref_b = _brightness(ref)
    # Brow band (just above the eyebrows): a cap, hood or hair pulled down over the brows makes it dark and
    # non-skin while the cheeks stay lit. Measured: 95 / 0.80 with a cap worn normally vs 36 / 0.49 pulled low.
    brow = _region(bgr, eye_mid[0], eye_mid[1] - 0.4 * d, 1.2 * d, 0.2 * d)
    if ref_b > 70 and brow is not None and _brightness(brow) < 0.4 * ref_b and _skin_ratio(brow) < 0.6 and "covered" not in issues:
        issues.append("covered")
    eyes_b = [_brightness(_region(bgr, e[0], e[1], 0.45 * d, 0.28 * d)) for e in (re, le)]
    if ref_b > 70 and all(0 <= b < 80 and b < 0.45 * ref_b for b in eyes_b):
        issues.append("eyes_covered")
    return issues


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
    if brightness < 40:
        issues.append("too_dark")
    elif brightness > 225:
        issues.append("too_bright")
    if sharpness < 18:
        issues.append("blurry")
    if abs(yaw) > max_yaw:
        issues.append("turned")
    if abs(roll) > 25:
        issues.append("tilted")
    if face.score < settings.detector_score_threshold:
        issues.append("low_confidence")
    # Only judge covering on a face that is big and lit enough for the colour heuristic to mean something.
    if face.size >= min_size * 0.8 and 40 <= brightness <= 225:
        issues = occlusion(bgr, face) + issues  # covering first: it is the guidance the person needs most

    size_term = min(1.0, face.size / (min_size * 1.6))
    light_term = 1.0 - min(1.0, abs(brightness - 130) / 110)
    sharp_term = min(1.0, sharpness / 250)
    pose_term = 1.0 - min(1.0, abs(yaw) / 60)
    score = float(np.clip(0.3 * size_term + 0.2 * light_term + 0.25 * sharp_term + 0.25 * pose_term, 0, 1))
    return Quality(not issues, score, brightness, sharpness, yaw, pitch, roll, issues)


GUIDANCE = {
    "no_face": "No face is visible: look at the camera and make sure nothing covers your face",
    "multiple_faces": "More than one person is equally close: the person checking in should step closer to the camera",
    "covered": "Your face looks partially covered: remove any hat, mask, scarf or hand in front of it",
    "eyes_covered": "Your eyes are not clearly visible: remove sunglasses, or lift a cap or hood that shadows them",
    "too_small": "Move closer to the camera",
    "partially_out_of_frame": "Centre your face in the frame",
    "too_dark": "Find better lighting — your face is too dark",
    "too_bright": "Too much light — move away from the glare",
    "blurry": "Hold still for a moment",
    "turned": "Look straight at the camera",
    "tilted": "Keep your head level",
    "low_confidence": "Face not clear — adjust your position",
}
