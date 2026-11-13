"""Passive presentation-attack detection. Two independent detectors, both run on every frame at no extra waiting time:

1. MiniFASNet V1SE (scale 4.0) + V2 (scale 2.7), Apache-2.0. Each takes an 80x80 BGR crop around the detected face
   enlarged by its scale and outputs 3 logits; index 1 is the 'live' class. The two are averaged (`live_prob`).
2. Intel Open Model Zoo `anti-spoof-mn3` (MobileNetV3, MIT), trained on CelebA-Spoof, which contains phone, tablet and
   monitor replays as well as printed photos. It takes the tight face box at 128x128 RGB and outputs
   [real, spoof] probabilities (`real_prob`). It was added because MiniFASNet scored a photo shown on a phone in a
   dark room 0.80 "live": on 400 genuine LFW photos MiniFASNet puts 8.5 % below 0.45, this model 0.8 %.

Neither is proof of a live person: a good enough replay can fool any single-camera RGB check. The caller takes the
median over a session's frames before deciding."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import onnxruntime as ort

from app.core.config import settings
from app.vision.align import crop_scaled

PAD_MODELS = (
    ("minifasnet_v1se_4.0_80x80.onnx", 4.0),
    ("minifasnet_v2_2.7_80x80.onnx", 2.7),
)


REPLAY_MODEL = "anti-spoof-mn3.onnx"
_REPLAY_MEAN = np.array([151.2405, 119.5950, 107.8395], np.float32)  # RGB, from the model's Open Model Zoo definition
_REPLAY_SCALE = np.array([63.0105, 56.4570, 55.0035], np.float32)
# The replay model reads an under-exposed face as a spoof (LFW darkened to half: 78 % below 0.45). Lifting a dark crop
# to a normal exposure first brings that back to 4 % (0.2 % with sensor noise at 0.28 exposure). Only ever brighten:
# dimming a bright crop makes genuine faces look like replays (76 % below 0.45), so bright crops are left alone.
_REPLAY_DARK_BELOW = 90.0
_REPLAY_TARGET_MEAN = 115.0


@dataclass(slots=True)
class PadResult:
    live_prob: float
    per_model: list[float]
    real_prob: float | None = None  # replay detector; None when it is switched off


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
        self.replay: ort.InferenceSession | None = None
        if settings.replay_check:
            path = settings.models_dir / REPLAY_MODEL
            if not path.exists():
                raise FileNotFoundError(f"Replay-detection model missing: {path} (Open Model Zoo public/anti-spoof-mn3), or set REPLAY_CHECK=false")
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            self.replay = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
            self._replay_input = self.replay.get_inputs()[0].name

    def replay_real_prob(self, bgr: np.ndarray, box: tuple[int, int, int, int]) -> float | None:
        """Probability that the face in `box` is a real face in front of the camera rather than a photo or a screen."""
        if self.replay is None:
            return None
        x, y, w, h = box
        H, W = bgr.shape[:2]
        crop = bgr[max(0, y) : min(H, y + h), max(0, x) : min(W, x + w)]
        if crop.shape[0] < 8 or crop.shape[1] < 8:
            return None
        crop = cv2.resize(crop, (128, 128), interpolation=cv2.INTER_CUBIC)
        mean = float(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).mean())
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32)
        if 1.0 <= mean < _REPLAY_DARK_BELOW:
            rgb = np.clip(rgb * (_REPLAY_TARGET_MEAN / mean), 0, 255)
        x_in = ((rgb - _REPLAY_MEAN) / _REPLAY_SCALE).transpose(2, 0, 1)[None]
        return float(self.replay.run(None, {self._replay_input: x_in})[0][0][0])

    def score(self, bgr: np.ndarray, box: tuple[int, int, int, int]) -> PadResult:
        probs: list[float] = []
        for sess, scale, inp in self.sessions:
            crop = crop_scaled(bgr, box, scale, 80)
            x = crop.astype(np.float32).transpose(2, 0, 1)[None]  # raw 0-255 BGR, as trained
            logits = sess.run(None, {inp: x})[0][0]
            probs.append(float(_softmax(logits)[1]))
        return PadResult(float(np.mean(probs)), probs, self.replay_real_prob(bgr, box))
