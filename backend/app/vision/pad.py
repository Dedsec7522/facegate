"""Passive presentation-attack detection: MiniFASNet V1SE (scale 4.0) + V2 (scale 2.7), Apache-2.0.

Each model takes an 80x80 BGR crop around the detected face enlarged by its scale and outputs 3 logits.
Index 1 is the 'live' class. The two models are averaged (score fusion) and the caller further
averages over several frames before deciding."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import onnxruntime as ort

from app.core.config import settings
from app.vision.align import crop_scaled

PAD_MODELS = (
    ("minifasnet_v1se_4.0_80x80.onnx", 4.0),
    ("minifasnet_v2_2.7_80x80.onnx", 2.7),
)


@dataclass(slots=True)
class PadResult:
    live_prob: float
    per_model: list[float]


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


class PresentationAttackDetector:
    def __init__(self) -> None:
        self.sessions: list[tuple[ort.InferenceSession, float, str]] = []
        for fname, scale in PAD_MODELS:
            path = settings.models_dir / fname
            if not path.exists():
                raise FileNotFoundError(f"PAD model missing: {path}. Run backend/tools/export_pad_onnx.py")
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            sess = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
            self.sessions.append((sess, scale, sess.get_inputs()[0].name))

    def score(self, bgr: np.ndarray, box: tuple[int, int, int, int]) -> PadResult:
        probs: list[float] = []
        for sess, scale, inp in self.sessions:
            crop = crop_scaled(bgr, box, scale, 80)
            x = crop.astype(np.float32).transpose(2, 0, 1)[None]  # raw 0-255 BGR, as trained
            logits = sess.run(None, {inp: x})[0][0]
            probs.append(float(_softmax(logits)[1]))
        return PadResult(float(np.mean(probs)), probs)
