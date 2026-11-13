"""Single entry point that owns the model instances and the bounded inference executor."""
from __future__ import annotations

import asyncio
import heapq
import itertools
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
    # Every other face in the frame (largest first): box, detector score and, when asked for, who it is.
    others: list[dict] = field(default_factory=list)
    # Replay detector: probability that this is a real face rather than a photo or a screen (None = not measured).
    real_prob: float | None = None


class Permit:
    """One slot in the inference pool. Releasing twice is harmless, so every exit path can release."""
    __slots__ = ("_adm", "_held")

    def __init__(self, adm: "Admission") -> None:
        self._adm, self._held = adm, True

    def release(self) -> None:
        if self._held:
            self._held = False
            self._adm._release()


class Admission:
    """Bounded entry to the inference pool: at most `slots` frames are queued or running at once.

    A frame that finds the pool full waits here for a slot instead of being answered "busy" at once. That matters
    because a kiosk sends its next frame the moment the previous one is answered: an instant "busy" made every
    waiting kiosk re-send ten frames a second, which the server had to receive and throw away. Holding the reply
    is the back-pressure the protocol already allows for.

    Waiters are served highest priority first, then first come first served. The stream handler passes the number
    of evidence frames a session has already collected, so sessions that are nearly decided finish before new ones
    start: under a rush people are answered one after another instead of everybody waiting until the end.
    """

    def __init__(self, slots: int) -> None:
        self._free = slots
        self._heap: list[tuple[int, int, asyncio.Future]] = []
        self._seq = itertools.count()
        self._stale = 0

    @property
    def full(self) -> bool:
        return self._free <= 0

    async def acquire(self, priority: int = 0, timeout: float | None = None) -> Permit | None:
        """A permit, or None if no slot came free within `timeout` seconds (None = wait as long as it takes)."""
        if self._free > 0:
            self._free -= 1
            return Permit(self)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        heapq.heappush(self._heap, (-priority, next(self._seq), fut))
        try:
            await asyncio.wait([fut], timeout=timeout)
        except BaseException:
            # Cancelled while waiting (the client went away). If the slot was handed over in the same instant, give it back.
            if fut.done() and not fut.cancelled():
                self._release()
            else:
                self._abandon(fut)
            raise
        if fut.done() and not fut.cancelled():
            return Permit(self)
        self._abandon(fut)
        return None

    def _abandon(self, fut: asyncio.Future) -> None:
        fut.cancel()
        self._stale += 1
        if self._stale > 256 and self._stale > len(self._heap) // 2:   # drop given-up waiters so the heap cannot grow without bound
            self._heap = [w for w in self._heap if not w[2].done()]
            heapq.heapify(self._heap)
            self._stale = 0

    def _release(self) -> None:
        while self._heap:
            fut = heapq.heappop(self._heap)[2]
            if not fut.done():
                fut.set_result(True)   # the slot passes straight to the next waiter
                return
            self._stale = max(0, self._stale - 1)
        self._free += 1


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
        self.admission = Admission(settings.inference_workers * 2)

    # ---- sync core ---------------------------------------------------------------------------
    def analyse(self, bgr: np.ndarray, *, want_embedding: bool = True, want_pad: bool = True, max_yaw: float = 35.0,
                want_others: bool = False) -> FrameAnalysis:
        """Analyse one frame. The subject is the largest face (the person closest to the camera); everyone else in
        the frame is listed in `others` and, with `want_others`, identified against the template index so the UI
        can say who they are. Two faces of about the same size mean we cannot tell who is checking in, which is
        the only case that still stops the frame (`multiple_faces`)."""
        t: dict[str, float] = {}
        t0 = time.perf_counter()
        faces = self.detector.detect(bgr)  # largest first
        t["detect"] = (time.perf_counter() - t0) * 1000
        if not faces:
            return FrameAnalysis(faces, None, None, None, None, None, t, "no_face")
        face = faces[0]
        others = self._describe_others(bgr, faces[1:], want_others, t)
        big = [f for f in faces if f.size >= settings.min_face_size * 0.6]
        if len(big) > 1 and big[1].size >= big[0].size * settings.primary_face_margin:
            return FrameAnalysis(faces, face, None, None, None, None, t, "multiple_faces", others)
        q = assess(bgr, face, max_yaw=max_yaw)
        if not q.ok:
            return FrameAnalysis(faces, face, q, None, None, None, t, "quality", others)
        live = real = None
        if want_pad:
            t1 = time.perf_counter()
            pad = self.pad.score(bgr, face.box)
            live, real = pad.live_prob, pad.real_prob
            t["pad"] = (time.perf_counter() - t1) * 1000
        emb = aligned = None
        if want_embedding:
            t2 = time.perf_counter()
            aligned = self.embedder.align(bgr, face.landmarks)
            emb = self.embedder.embed(aligned)
            t["embed"] = (time.perf_counter() - t2) * 1000
        return FrameAnalysis(faces, face, q, live, emb, aligned, t, "ok", others, real)

    def _describe_others(self, bgr: np.ndarray, faces: list[Face], identify: bool, t: dict[str, float]) -> list[dict]:
        """Boxes of the non-subject faces; with `identify`, the closest few are embedded and matched (no PAD or
        quality gates: this only labels bystanders, it never records attendance for them)."""
        out: list[dict] = []
        if not faces:
            return out
        t0 = time.perf_counter()
        for f in faces[: settings.max_other_faces]:
            item: dict = {"box": list(f.box), "score": round(f.score, 3), "employee_id": None, "match_score": None}
            if identify and f.size >= settings.min_face_size * 0.6 and self.index.size:
                m = self.index.match(self.embedder.embed(self.embedder.align(bgr, f.landmarks)))
                item["employee_id"] = m.employee_id if m.decision == "identified" else None
                item["match_score"] = round(m.score, 3)
            out.append(item)
        t["others"] = (time.perf_counter() - t0) * 1000
        return out

    # ---- async wrappers ----------------------------------------------------------------------
    async def analyse_async(self, bgr: np.ndarray, *, permit: Permit | None = None, **kw) -> FrameAnalysis:
        """Analyse a frame on the worker pool. Pass the `permit` from `admit()` if the caller already holds a slot;
        otherwise this waits for one. The slot is released when the analysis ends, either way."""
        loop = asyncio.get_running_loop()
        permit = permit or await self.admission.acquire()
        try:
            return await loop.run_in_executor(self.executor, lambda: self.analyse(bgr, **kw))
        finally:
            permit.release()

    async def admit(self, priority: int = 0, timeout: float | None = None) -> Permit | None:
        """Reserve a slot in the inference pool, waiting up to `timeout` seconds. None means the pool stayed full."""
        return await self.admission.acquire(priority, timeout)

    async def decode_async(self, data: bytes) -> np.ndarray | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, decode_jpeg, data)

    @property
    def busy(self) -> bool:
        return self.admission.full


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
