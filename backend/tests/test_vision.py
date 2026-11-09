"""Vision pipeline behaviour on synthetic (non-real) faces: detection, quality gates, identification rules."""
from __future__ import annotations

import glob

import cv2
import numpy as np
import pytest

from app.core.config import settings
from app.vision.align import align_face
from app.vision.matcher import TemplateIndex
from app.vision.pipeline import VisionPipeline
from tests.conftest import DATA

FILES = sorted(glob.glob(str(DATA / "synth_face_*.jpg")))
pytestmark = pytest.mark.skipif(len(FILES) < 3, reason="synthetic face images not present in tests/data")


@pytest.fixture(scope="module")
def pipe():
    return VisionPipeline()


@pytest.fixture(scope="module")
def faces(pipe):
    out = {}
    for f in FILES:
        img = cv2.resize(cv2.imread(f), (640, 640))
        a = pipe.analyse(img)
        assert a.state == "ok", (f, a.state, a.quality.issues if a.quality else None)
        out[f] = (img, a)
    return out


def test_no_face_and_multiple_faces(pipe, faces):
    assert pipe.analyse(np.full((480, 640, 3), 120, np.uint8)).state == "no_face"
    imgs = [cv2.resize(v[0], (400, 400)) for v in list(faces.values())[:2]]
    assert pipe.analyse(np.concatenate(imgs, axis=1)).state == "multiple_faces"


def test_quality_gates(pipe, faces):
    img, _ = next(iter(faces.values()))
    dark = cv2.convertScaleAbs(img, alpha=0.25, beta=0)
    a = pipe.analyse(dark)
    assert a.state in ("quality", "no_face") and (a.quality is None or "too_dark" in a.quality.issues)
    small = cv2.resize(img, (90, 90))  # face ~60 px: below the 80 px minimum
    canvas = np.full((480, 640, 3), 128, np.uint8)
    canvas[195:285, 275:365] = small
    a = pipe.analyse(canvas)
    assert a.state in ("quality", "no_face")


def test_same_identity_is_stable_under_perturbation(pipe, faces):
    img, a = next(iter(faces.values()))
    variants = [
        cv2.convertScaleAbs(img, alpha=1.10, beta=8),           # brighter
        cv2.convertScaleAbs(img, alpha=0.85, beta=-10),         # darker
        cv2.resize(cv2.resize(img, (480, 480)), (640, 640)),    # lower resolution
        cv2.flip(img, 1),                                       # mirrored
    ]
    for v in variants:
        b = pipe.analyse(v)
        assert b.state == "ok", (b.state, b.quality.issues if b.quality else None)
        assert float(a.embedding @ b.embedding) > 0.6


def test_identification_rules(pipe, faces):
    items = list(faces.values())
    idx = TemplateIndex()
    idx.load([(f"emp{i}", a.embedding) for i, (_, a) in enumerate(items)])
    # every enrolled image identifies itself with a strong score
    for i, (_, a) in enumerate(items):
        m = idx.match(a.embedding, accept=settings.match_accept_threshold, margin=0.08)
        assert m.decision == "identified" and m.employee_id == f"emp{i}" and m.score > 0.95
    # an un-enrolled identity is rejected
    idx2 = TemplateIndex()
    idx2.load([(f"emp{i}", a.embedding) for i, (_, a) in enumerate(items[1:])])
    m = idx2.match(items[0][1].embedding, accept=settings.match_accept_threshold, margin=0.08)
    assert m.decision == "unknown", m
    # ambiguity: two "employees" with near-identical templates → ambiguous, never a guess
    idx3 = TemplateIndex()
    e = items[0][1].embedding
    idx3.load([("a", e), ("b", e + np.random.default_rng(0).normal(0, 0.01, e.shape).astype(np.float32))])
    assert idx3.match(e, accept=settings.match_accept_threshold, margin=0.08).decision == "ambiguous"
    assert TemplateIndex().match(e).decision == "empty"


def test_alignment_output_shape(faces):
    img, a = next(iter(faces.values()))
    assert align_face(img, a.face.landmarks).shape == (112, 112, 3)


def test_latency_budget(pipe, faces):
    import time

    img, _ = next(iter(faces.values()))
    pipe.analyse(img)
    t = time.perf_counter()
    for _ in range(10):
        pipe.analyse(img)
    per_frame = (time.perf_counter() - t) / 10 * 1000
    assert per_frame < 400, f"{per_frame:.0f} ms/frame is too slow for a kiosk"
