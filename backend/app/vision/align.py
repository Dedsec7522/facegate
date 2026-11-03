"""5-point similarity alignment to the 112x112 recognition template."""
from __future__ import annotations

import cv2
import numpy as np

# Canonical landmark positions for a 112x112 crop (standard ArcFace/InsightFace reference template).
REFERENCE_112 = np.array(
    [
        [38.2946, 51.6963],  # right eye (subject's left in image)
        [73.5318, 51.5014],  # left eye
        [56.0252, 71.7366],  # nose tip
        [41.5493, 92.3655],  # right mouth corner
        [70.7299, 92.2041],  # left mouth corner
    ],
    dtype=np.float32,
)


def align_face(bgr: np.ndarray, landmarks: np.ndarray, size: int = 112) -> np.ndarray:
    ref = REFERENCE_112 * (size / 112.0)
    m, _ = cv2.estimateAffinePartial2D(landmarks.astype(np.float32), ref, method=cv2.LMEDS)
    if m is None:  # degenerate landmarks; fall back to a plain crop
        return cv2.resize(bgr, (size, size))
    return cv2.warpAffine(bgr, m, (size, size), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def crop_scaled(bgr: np.ndarray, box: tuple[int, int, int, int], scale: float, out: int) -> np.ndarray:
    """Crop the face box enlarged by `scale` in both axes and resize to out×out (the PAD models were
    trained on this box-proportional crop). The scale is reduced if the enlarged box would not fit
    the frame, and the box is shifted to stay inside the frame rather than padded."""
    h, w = bgr.shape[:2]
    x, y, bw, bh = box
    bw, bh = max(1, bw), max(1, bh)
    scale = min((h - 1) / bh, (w - 1) / bw, scale)
    nw, nh = bw * scale, bh * scale
    cx, cy = x + bw / 2.0, y + bh / 2.0
    x1, y1 = cx - nw / 2.0, cy - nh / 2.0
    x2, y2 = x1 + nw, y1 + nh
    if x1 < 0:
        x2, x1 = x2 - x1, 0
    if y1 < 0:
        y2, y1 = y2 - y1, 0
    if x2 > w - 1:
        x1, x2 = x1 - (x2 - (w - 1)), w - 1
    if y2 > h - 1:
        y1, y2 = y1 - (y2 - (h - 1)), h - 1
    crop = bgr[int(y1) : int(y2) + 1, int(x1) : int(x2) + 1]
    return cv2.resize(crop, (out, out), interpolation=cv2.INTER_AREA)
