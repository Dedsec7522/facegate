"""A verification session must bind its liveness evidence to the identified face for the whole session.

Attack: show an enrolled employee's photo for the first frames (identity, low PAD), then a different live face
(high PAD, natural motion). The PAD median turns "live" once live frames outnumber the photo frames; the session
must then reject as inconsistent rather than identify the employee from the photo frames.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from app.services.verification import Session, SessionManager
from app.vision.detector import Face
from app.vision.matcher import TemplateIndex
from app.vision.pipeline import FrameAnalysis, get_pipeline
from app.vision.quality import Quality

pytestmark = pytest.mark.asyncio


def _unit(seed: int, dim: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _frame(emb: np.ndarray, live: float, rng: np.random.Generator) -> FrameAnalysis:
    base = np.array([[280, 220], [360, 220], [320, 270], [290, 320], [350, 320]], np.float32)
    face = Face((240, 160, 160, 200), base + rng.normal(0, 1.5, base.shape).astype(np.float32), 0.95)
    q = Quality(True, 0.9, 130.0, 200.0, 0.0, 0.0, 0.0, [])
    return FrameAnalysis([face], face, q, live, emb, None, {}, "ok")


async def test_photo_identity_then_other_live_face_is_rejected(monkeypatch):
    pipe = get_pipeline()
    dim = pipe.embedder.dim
    alice, bob = _unit(1, dim), _unit(2, dim)
    idx = TemplateIndex(dim)
    idx.load([("alice", alice)])
    monkeypatch.setattr(pipe, "index", idx)

    rng = np.random.default_rng(0)
    script = [(alice, 0.05)] * 6 + [(bob, 0.95)] * 30  # photo of Alice, then Bob's live face
    frames = iter(script)

    async def fake_analyse(bgr, **kw):
        emb, live = next(frames)
        return _frame(emb, live, rng)

    monkeypatch.setattr(pipe, "analyse_async", fake_analyse)
    m = SessionManager()
    s = Session(id="bind", purpose="attendance", nonce="n", created=time.monotonic(), ip=None, user_agent=None,
                challenge=None, liveness_policy="passive")
    s.challenge_state = "passed"
    blank = np.zeros((480, 640, 3), np.uint8)
    result = None
    for _ in range(len(script)):
        r = await m.process_attendance_frame(s, blank)
        if s.done:
            result = r
            break
    assert result is not None, "session never reached a decision"
    assert result["state"] == "rejected", result
    assert result.get("employee_id") != "alice"
    assert result["reason"] == "inconsistent", result
