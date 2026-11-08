"""Single entry point that owns the model instances and the bounded inference executor."""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.core.config import settings
from app.vision.detector import Face, FaceDetector
from app.vision.embedder import FaceEmbedder
from app.vision.matcher import TemplateIndex
from app.vision.pad import PresentationAttackDetector
from app.vision.quality import Quality, assess


@dataclass(slots=True)
class FrameAnalysis:
    faces: list[Face]
    face: Face | None
    quality: Quality | None
    live_prob: float | None
    embedding: np.ndarray | None
    aligned: np.ndarray | None
    timings_ms: dict[str, float] = field(default_factory=dict)
    state: str = "no_face"  # no_face | multiple_faces | quality | ok


class VisionPipeline:
    def __init__(self) -> None:
        # Parallelism comes from the worker pool (one frame per core), not from threading inside each op:
        # OpenCV's own pool would oversubscribe the CPU when every worker runs a detection at once.
        cv2.setNumThreads(1)
        self.detector = FaceDetector()
        self.embedder = FaceEmbedder()
        self.pad = PresentationAttackDetector()
        self.index = TemplateIndex(self.embedder.dim)
        self.executor = ThreadPoolExecutor(max_workers=settings.inference_workers, thread_name_prefix="vision")
        self._sem = asyncio.Semaphore(settings.inference_workers * 2)

    # ---- sync core ---------------------------------------------------------------------------
    def analyse(self, bgr: np.ndarray, *, want_embedding: bool = True, want_pad: bool = True, max_yaw: float = 35.0) -> FrameAnalysis:
        t: dict[str, float] = {}
        t0 = time.perf_counter()
        faces = self.detector.detect(bgr)
        t["detect"] = (time.perf_counter() - t0) * 1000
        if not faces:
            return FrameAnalysis(faces, None, None, None, None, None, t, "no_face")
        big = [f for f in faces if f.size >= settings.min_face_size * 0.6]
        if len(big) > 1:
            return FrameAnalysis(faces, big[0], None, None, None, None, t, "multiple_faces")
        face = faces[0]
        q = assess(bgr, face, max_yaw=max_yaw)
        if not q.ok:
            return FrameAnalysis(faces, face, q, None, None, None, t, "quality")
        live = None
        if want_pad:
            t1 = time.perf_counter()
            live = self.pad.score(bgr, face.box).live_prob
            t["pad"] = (time.perf_counter() - t1) * 1000
        emb = aligned = None
        if want_embedding:
            t2 = time.perf_counter()
            aligned = self.embedder.align(bgr, face.landmarks)
            emb = self.embedder.embed(aligned)
            t["embed"] = (time.perf_counter() - t2) * 1000
        return FrameAnalysis(faces, face, q, live, emb, aligned, t, "ok")

    # ---- async wrappers ----------------------------------------------------------------------
    async def analyse_async(self, bgr: np.ndarray, **kw) -> FrameAnalysis:
        loop = asyncio.get_running_loop()
        async with self._sem:
            return await loop.run_in_executor(self.executor, lambda: self.analyse(bgr, **kw))

    async def decode_async(self, data: bytes) -> np.ndarray | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, decode_jpeg, data)

    @property
    def busy(self) -> bool:
        return self._sem.locked()


def decode_jpeg(data: bytes, max_side: int = 960) -> np.ndarray | None:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) > max_side:
        s = max_side / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def encode_jpeg(bgr: np.ndarray, quality: int = 80) -> bytes:
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b""


_pipeline: VisionPipeline | None = None


def get_pipeline() -> VisionPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = VisionPipeline()
    return _pipeline
