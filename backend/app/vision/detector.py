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
        h, w = bgr.shape[:2]
        _, out = self._det(w, h).detect(bgr)
        if out is None:
            return []
        faces: list[Face] = []
        for row in out:
            x, y, bw, bh = row[:4]
            lm = row[4:14].reshape(5, 2).astype(np.float32)
            faces.append(Face((int(x), int(y), int(bw), int(bh)), lm, float(row[14])))
        faces.sort(key=lambda f: f.box[2] * f.box[3], reverse=True)
        return faces
