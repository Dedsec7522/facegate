"""Face embeddings on the CPU.

Default: Intel `face-reidentification-retail-0095` (Apache-2.0, Open Model Zoo) on the OpenVINO runtime —
256-d, 0.59 GFLOPs, ~11 ms per face on one core. On LFW through FaceGate's own detector and alignment it
scored 99.50 % (TAR 98.87 % at FAR 0.1 %) against SFace's 99.08 % / 97.97 % while being ~5x cheaper
(see docs/05-test-and-benchmark-results.md §7).

Fallback: OpenCV Zoo SFace 2021dec (Apache-2.0) on ONNX Runtime, 128-d, with flip test-time augmentation,
selected with FACE_MODEL=sface-2021dec. Templates are tied to the model that produced them (the enrolment's
`model_version`); switching models means re-enrolling.
"""
from __future__ import annotations

import threading

import numpy as np

from app.core.config import settings
from app.vision.align import REFERENCE_112, REFERENCE_INTEL_UNIT, align_to

INTEL_FILE = "face-reidentification-retail-0095.xml"
SFACE_FILE = "face_recognition_sface_2021dec.onnx"

MODELS = {
    # version id       (input size, embedding dim)
    "intel-fr-0095": (128, 256),
    "sface-2021dec": (112, 128),
}


class FaceEmbedder:
    def __init__(self, model: str | None = None) -> None:
        self.version = model or settings.face_model
        if self.version not in MODELS:
            raise ValueError(f"FACE_MODEL must be one of {sorted(MODELS)}, got {self.version!r}")
        self.input_size, self.dim = MODELS[self.version]
        self._local = threading.local()
        if self.version == "intel-fr-0095":
            import openvino as ov

            core = ov.Core()
            model_ = core.read_model(str(settings.models_dir / INTEL_FILE))
            # One compiled model, one stream per inference worker: each worker thread runs its own infer request
            # on its own core instead of all requests fighting over every core.
            self._compiled = core.compile_model(
                model_, "CPU",
                {"PERFORMANCE_HINT": "THROUGHPUT", "NUM_STREAMS": str(settings.inference_workers), "INFERENCE_PRECISION_HINT": "f32"},
            )
            self._out = self._compiled.output(0)
            self._ref = REFERENCE_INTEL_UNIT * self.input_size
            self._flip = False  # flip TTA measured as no gain for this model (99.47 % vs 99.50 % on LFW) at 2x the cost
        else:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            opts.log_severity_level = 3  # the SFace graph lists initializers as inputs; ORT warns loudly but runs fine
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(str(settings.models_dir / SFACE_FILE), opts, providers=["CPUExecutionProvider"])
            self._input_name = self._session.get_inputs()[0].name
            self._ref = REFERENCE_112 * (self.input_size / 112.0)
            self._flip = True

    def align(self, bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        """Crop aligned to this model's own landmark template and input size."""
        return align_to(bgr, landmarks, self._ref, self.input_size)

    def _run(self, aligned_bgr: np.ndarray) -> np.ndarray:
        # Both models take a BGR image, NCHW float32, raw 0-255 pixel values (no normalisation).
        x = aligned_bgr.astype(np.float32).transpose(2, 0, 1)[None]
        if self.version == "intel-fr-0095":
            req = getattr(self._local, "req", None)
            if req is None:  # infer requests are not thread-safe: one per worker thread
                req = self._local.req = self._compiled.create_infer_request()
            return req.infer({0: x})[self._out].reshape(-1)
        # The SFace graph has a fixed batch of 1.
        return self._session.run(None, {self._input_name: x})[0][0]

    def embed(self, aligned_bgr: np.ndarray) -> np.ndarray:
        e = normalize(self._run(aligned_bgr))
        if self._flip:
            e = normalize(e + normalize(self._run(np.ascontiguousarray(aligned_bgr[:, ::-1]))))
        return e

    def embed_batch(self, aligned: list[np.ndarray]) -> np.ndarray:
        if not aligned:
            return np.zeros((0, self.dim), np.float32)
        return np.stack([self.embed(a) for a in aligned])


def normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, np.float32)
    n = float(np.linalg.norm(v)) + 1e-9
    return (v / n).astype(np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(normalize(a), normalize(b)))
