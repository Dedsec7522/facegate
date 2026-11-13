"""Turns one still photograph into the short JPEG frame sequence a webcam would send.

A real camera never delivers two identical frames: the head drifts by a pixel or two and exposure flickers. The
application relies on that (a stream with no micro-motion at all is rejected as frozen/injected), so each simulated
session gets a small random walk in position plus slight brightness changes. This reproduces camera behaviour; it does
not alter, disable or bypass any check in the application.

Also builds the special inputs for the accuracy tests: no face, two equally close faces, dark and blurred frames.
"""
from __future__ import annotations

import random
from functools import lru_cache

import cv2
import numpy as np

from test_config import settings as S

# One OpenCV thread in the load generator: its default pool (one thread per core) keeps spinning after every small
# warp/encode call, which cost a full core per Locust worker and would take that CPU away from the server under test.
cv2.setNumThreads(1)


def on_canvas(img: np.ndarray) -> np.ndarray:
    """Place a photograph, at its native resolution, in the middle of a webcam-sized frame.

    Enlarging a 250 px press photo to fill the frame makes it fail the application's sharpness gate (measured: 65 of 80
    refused as blurry at 640 px, 0 of 80 at native size), which would test the resampling, not the application. On a
    640x480 canvas the face keeps its real detail (about 110 px wide, as for someone standing a metre from a kiosk)
    and the server still pays the decode and detection cost of a real camera frame. The surround is the same photo,
    heavily blurred, so there is no artificial hard edge."""
    w, h = S.FRAME_SIZE
    ih, iw = img.shape[:2]
    if iw > w or ih > h:
        k = min(w / iw, h / ih)
        img = cv2.resize(img, (int(iw * k), int(ih * k)), interpolation=cv2.INTER_AREA)
        ih, iw = img.shape[:2]
    bg = _backdrop(img, w, h)
    x, y = (w - iw) // 2, (h - ih) // 2
    bg[y:y + ih, x:x + iw] = img
    return bg


def _backdrop(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """The photo stretched over the frame and heavily blurred. Blurring a 1/8-size copy and enlarging it gives the
    same soft surround as a sigma-25 blur at full size for about 1 ms instead of 130 ms, which matters because the
    load generator builds one of these per scan and must not spend the server's CPU (same machine) doing it."""
    small = cv2.resize(img, (w // 8, h // 8), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 25 / 8)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


@lru_cache(maxsize=256)
def load(path: str) -> np.ndarray:
    img = cv2.imread(str(S.DATASET / path))
    if img is None:
        raise FileNotFoundError(path)
    return on_canvas(img)


@lru_cache(maxsize=512)
def load_raw(path: str) -> np.ndarray:
    img = cv2.imread(str(S.DATASET / path))
    if img is None:
        raise FileNotFoundError(path)
    return img


def _encode(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, S.JPEG_QUALITY])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return buf.tobytes()


def degrade(img: np.ndarray, variant: str | None) -> np.ndarray:
    if variant == "dark":      # under-exposed office corner
        return cv2.convertScaleAbs(img, alpha=0.5, beta=-10)
    if variant == "bright":    # window behind the camera
        return cv2.convertScaleAbs(img, alpha=1.25, beta=30)
    if variant == "blur":      # out-of-focus webcam
        return cv2.GaussianBlur(img, (0, 0), 2.2)
    return img


def session_frames(img: np.ndarray, rng: random.Random, n: int = 8, variant: str | None = None) -> list[bytes]:
    """`n` distinct frames of the same photograph with webcam-like micro-motion; the caller cycles through them."""
    img = degrade(img, variant)
    h, w = img.shape[:2]
    x = y = 0.0
    path = []
    for _ in range(n):
        x = max(-4.0, min(4.0, x + rng.gauss(0, 1.1)))
        y = max(-4.0, min(4.0, y + rng.gauss(0, 1.1)))
        path.append((x, y))
    # A random walk can, by chance, barely move. No camera pointed at a person is that still, so stretch a too-quiet
    # path to at least ~1 px of spread (the application treats < 0.35 px of landmark motion as a frozen stream).
    spread = float(np.std([p[0] for p in path]) + np.std([p[1] for p in path])) / 2
    k = max(1.0, 1.0 / max(spread, 0.05))
    out = []
    for x, y in path:
        x, y = max(-5.0, min(5.0, x * k)), max(-5.0, min(5.0, y * k))
        m = np.float32([[1, 0, x], [0, 1, y]])
        f = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        out.append(_encode(cv2.convertScaleAbs(f, alpha=1.0, beta=rng.uniform(-2.5, 2.5))))
    return out


def no_face_image(rng: random.Random) -> np.ndarray:
    """An empty desk/wall: smooth gradient with sensor noise, no face anywhere."""
    w, h = S.FRAME_SIZE
    gx = np.linspace(rng.randint(40, 110), rng.randint(130, 210), w, dtype=np.float32)
    base = np.repeat(gx[None, :], h, axis=0)
    img = np.stack([base * rng.uniform(0.8, 1.0), base * rng.uniform(0.8, 1.0), base], axis=2)
    noise = np.random.default_rng(rng.randint(0, 1 << 30)).normal(0, 6, img.shape)
    return np.clip(img + noise, 0, 255).astype(np.uint8)


def two_faces_image(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Two people equally close to the camera, side by side (the application must refuse to pick one).
    `a` and `b` are raw photographs (`load_raw`), kept at native size like every other test frame."""
    w, h = S.FRAME_SIZE
    pair = np.concatenate([a, cv2.resize(b, (a.shape[1], a.shape[0]))], axis=1)
    bg = _backdrop(pair, w, h)
    ph, pw = pair.shape[:2]
    x, y = (w - pw) // 2, (h - ph) // 2
    bg[y:y + ph, x:x + pw] = pair
    return bg
