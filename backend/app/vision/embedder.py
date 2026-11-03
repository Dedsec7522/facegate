"""SFace (Apache-2.0) 128-d face embeddings via ONNX Runtime."""
from __future__ import annotations

import numpy as np
import onnxruntime as ort

from app.core.config import settings

SFACE_FILE = "face_recognition_sface_2021dec.onnx"
MODEL_VERSION = "sface-2021dec"
EMBED_DIM = 128


class FaceEmbedder:
    def __init__(self) -> None:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.log_severity_level = 3  # the SFace graph lists initializers as inputs; ORT warns loudly but runs fine
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(settings.models_dir / SFACE_FILE), opts, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    @staticmethod
    def _prep(aligned_bgr: np.ndarray) -> np.ndarray:
        # SFace expects a 112x112 BGR image, NCHW float32, raw 0-255 pixel values (no normalisation).
        x = aligned_bgr.astype(np.float32).transpose(2, 0, 1)
        return x[None]

    def embed(self, aligned_bgr: np.ndarray) -> np.ndarray:
        """Flip test-time augmentation: the crop and its mirror are embedded in one batch and averaged,
        which measurably stabilises the vector against small alignment/pose errors."""
        # The SFace graph has a fixed batch of 1, so the two passes run back to back (~+12 ms on CPU).
        a = self.session.run(None, {self.input_name: self._prep(aligned_bgr)})[0][0]
        b = self.session.run(None, {self.input_name: self._prep(np.ascontiguousarray(aligned_bgr[:, ::-1]))})[0][0]
        return normalize(normalize(a.astype(np.float32)) + normalize(b.astype(np.float32)))

    def embed_batch(self, aligned: list[np.ndarray]) -> np.ndarray:
        if not aligned:
            return np.zeros((0, EMBED_DIM), np.float32)
        return np.stack([self.embed(a) for a in aligned])


def normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v)) + 1e-9
    return (v / n).astype(np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(normalize(a), normalize(b)))
