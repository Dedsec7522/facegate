"""Face detection with 5 landmarks (YuNet via OpenCV's standard FaceDetectorYN API)."""
from __future__ import annotations

import threading
from dataclasses import dataclass

import cv2
import numpy as np

from app.core.config import settings

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
cv2.ocl.setUseOpenCL(False)  # CPU only: never dispatch to OpenCL/GPU


@dataclass(slots=True)
class Face:
    box: tuple[int, int, int, int]  # x, y, w, h
    landmarks: np.ndarray  # (5, 2) float32: right eye, left eye, nose, right mouth, left mouth
    score: float

    @property
    def size(self) -> int:
        return max(self.box[2], self.box[3])

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.box
        return x + w / 2, y + h / 2


class FaceDetector:
    """Thread-safe wrapper; OpenCV detector objects are not re-entrant so we keep one per thread."""

    def __init__(self, score_threshold: float | None = None) -> None:
        self.path = str(settings.models_dir / YUNET_FILE)
        self.score_threshold = score_threshold or settings.detector_score_threshold
        self._local = threading.local()

    def _det(self, w: int, h: int):
        det = getattr(self._local, "det", None)
        if det is None:
            det = cv2.FaceDetectorYN.create(self.path, "", (w, h), self.score_threshold, 0.3, 50)
            self._local.det = det
            self._local.size = (w, h)
        elif self._local.size != (w, h):
            det.setInputSize((w, h))
            self._local.size = (w, h)
        return det

    def _run(self, img: np.ndarray) -> list[Face]:
        _, out = self._det(img.shape[1], img.shape[0]).detect(img)
        if out is None:
            return []
        return [Face((int(r[0]), int(r[1]), int(r[2]), int(r[3])), r[4:14].reshape(5, 2).astype(np.float32).copy(), float(r[14])) for r in out]

    def detect(self, bgr: np.ndarray) -> list[Face]:
        """Two-stage detection. Stage 1 finds faces on a copy downscaled to `detect_max_side` (cost scales with
        pixels; faces worth verifying are ≥ 80 px in the stream, ≥ 40 px here, well inside YuNet's range).
        Stage 2 re-runs the detector on a full-resolution crop around each face: landmarks straight from the
        small image are coarse (measured 4–11° of head-yaw bias on 640 px frames), which would skew the pose gates
        and the alignment the embedding depends on. The crop is a fraction of the frame, so this stays far cheaper
        than detecting at full resolution while keeping full-resolution landmarks."""
        h, w = bgr.shape[:2]
        s = min(1.0, settings.detect_max_side / max(h, w)) if settings.detect_max_side > 0 else 1.0
        if s >= 1.0:
            faces = self._run(bgr)
        else:
            small = cv2.resize(bgr, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
            faces = []
            for f in self._run(small):
                x, y, bw, bh = (v / s for v in f.box)
                coarse = Face((int(x), int(y), int(bw), int(bh)), f.landmarks / s, f.score)
                faces.append(self._refine(bgr, coarse) or coarse)
        faces.sort(key=lambda f: f.box[2] * f.box[3], reverse=True)
        return faces

    def _refine(self, bgr: np.ndarray, f: Face) -> Face | None:
        """Detect again inside a full-resolution crop (the coarse box padded by half its size on each side) and
        return the detection nearest the coarse centre, in frame coordinates. None if nothing is found there."""
        h, w = bgr.shape[:2]
        x, y, bw, bh = f.box
        px, py = bw // 2, bh // 2
        x0, y0 = max(0, x - px), max(0, y - py)
        x1, y1 = min(w, x + bw + px), min(h, y + bh + py)
        if x1 - x0 < 32 or y1 - y0 < 32:
            return None
        cx, cy = f.center
        best, best_d = None, float("inf")
        for g in self._run(np.ascontiguousarray(bgr[y0:y1, x0:x1])):
            gx, gy = g.center
            d = (gx + x0 - cx) ** 2 + (gy + y0 - cy) ** 2
            if d < best_d:
                best, best_d = g, d
        if best is None or best_d > (max(bw, bh) * 0.5) ** 2:
            return None
        bx, by, bbw, bbh = best.box
        return Face((bx + x0, by + y0, bbw, bbh), best.landmarks + np.array([x0, y0], np.float32), best.score)
