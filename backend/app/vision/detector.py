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

    def detect(self, bgr: np.ndarray) -> list[Face]:
        """Detect on a copy downscaled to `detect_max_side` (detection cost scales with pixels; faces worth
        verifying are ≥ 80 px in the streamed frame, i.e. ≥ 40 px here, well inside YuNet's range), then map boxes
        and landmarks back to full-resolution coordinates so alignment keeps every pixel of detail."""
        h, w = bgr.shape[:2]
        s = min(1.0, settings.detect_max_side / max(h, w)) if settings.detect_max_side > 0 else 1.0
        img = cv2.resize(bgr, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA) if s < 1.0 else bgr
        _, out = self._det(img.shape[1], img.shape[0]).detect(img)
        if out is None:
            return []
        faces: list[Face] = []
        for row in out:
            row = row.copy()
            row[:14] /= s
            x, y, bw, bh = row[:4]
            lm = row[4:14].reshape(5, 2).astype(np.float32)
            faces.append(Face((int(x), int(y), int(bw), int(bh)), lm, float(row[14])))
        faces.sort(key=lambda f: f.box[2] * f.box[3], reverse=True)
        return faces
