"""Single-frame latency breakdown of the vision pipeline on this machine (detect / PAD / embed / match).

    .venv/Scripts/python benchmarks/latency.py
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.vision.matcher import TemplateIndex  # noqa: E402
from app.vision.pipeline import VisionPipeline  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"


def main() -> None:
    pipe = VisionPipeline()
    img = cv2.resize(cv2.imread(str(sorted(DATA.glob("synth_face_*.jpg"))[0])), (640, 480))
    for _ in range(3):
        pipe.analyse(img)  # warm-up
    runs = [pipe.analyse(img) for _ in range(40)]
    for k in ("detect", "pad", "embed"):
        xs = [r.timings_ms[k] for r in runs]
        print(f"{k:7s} p50={statistics.median(xs):6.1f} ms  p95={sorted(xs)[int(0.95 * len(xs))]:6.1f} ms")
    tot = [sum(r.timings_ms.values()) for r in runs]
    print(f"frame   p50={statistics.median(tot):6.1f} ms  p95={sorted(tot)[int(0.95 * len(tot))]:6.1f} ms")

    rng = np.random.default_rng(0)
    for n_emp in (50, 300, 1000):
        idx = TemplateIndex()
        vecs = rng.normal(size=(n_emp * 5, pipe.embedder.dim)).astype(np.float32)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        idx.load([(f"e{i // 5}", v) for i, v in enumerate(vecs)])
        probe = runs[0].embedding
        t = time.perf_counter()
        for _ in range(200):
            idx.match(probe)
        print(f"match   {n_emp:4d} employees ({n_emp * 5} templates): {(time.perf_counter() - t) / 200 * 1000:.3f} ms")


if __name__ == "__main__":
    main()
