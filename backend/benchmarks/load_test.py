"""Concurrency benchmark: N near-simultaneous verification sessions streaming real frames over WebSocket.

Each virtual kiosk creates a session, streams `frames` JPEGs of a synthetic face at up to 6 fps and
waits for the terminal message (identified / rejected). Reports latency percentiles for
per-frame round-trips and end-to-end session time, plus server throughput.

    .venv/Scripts/python benchmarks/load_test.py --clients 300 --ramp 5 --frames 10 --base http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import cv2
import httpx
import websockets

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"


def load_frames(n: int) -> list[bytes]:
    files = sorted(DATA.glob("synth_face_*.jpg"))
    if not files:
        raise SystemExit("no synthetic faces in tests/data")
    img = cv2.resize(cv2.imread(str(files[0])), (640, 640))
    out = []
    for i in range(n):
        v = cv2.convertScaleAbs(img, alpha=1.0, beta=(i % 5) - 2)  # jitter so frames are not byte-identical
        ok, buf = cv2.imencode(".jpg", v, [cv2.IMWRITE_JPEG_QUALITY, 80])
        out.append(buf.tobytes())
    return out


async def one_client(idx: int, base: str, frames: list[bytes], results: dict, delay: float, gate: asyncio.Semaphore) -> None:
    await asyncio.sleep(delay)
    async with gate:
        await _run_client(idx, base, frames, results)


async def _run_client(idx: int, base: str, frames: list[bytes], results: dict) -> None:
    t0 = time.perf_counter()
    frame_rtts: list[float] = []
    busy = 0
    outcome = "error"
    msg: dict = {}
    try:
        # Each virtual client presents a distinct source address so per-IP limits behave as in production.
        xff = {"X-Forwarded-For": f"10.{(idx // 65025) % 256}.{(idx // 255) % 255}.{idx % 255 + 1}"}
        async with httpx.AsyncClient(base_url=base, timeout=30, headers=xff) as c:
            r = await c.post("/api/v1/verify/sessions")
            r.raise_for_status()
            s = r.json()
        ws_base = base.replace("http", "ws", 1)
        async with websockets.connect(f"{ws_base}/api/v1/verify/stream/{s['session_id']}", max_size=4 * 1024 * 1024) as ws:
            await ws.send(json.dumps({"nonce": s["nonce"]}))
            sent = 0
            while sent < len(frames):
                ts = time.perf_counter()
                await ws.send(frames[sent])
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                if msg.get("state") == "busy":  # server shed load: back off, do not count as processed
                    busy += 1
                    await asyncio.sleep(0.3)
                    continue
                frame_rtts.append((time.perf_counter() - ts) * 1000)
                sent += 1
                if msg.get("state") in ("identified", "rejected"):
                    outcome = msg["state"] + ":" + str(msg.get("reason", ""))
                    break
                await asyncio.sleep(1 / 6)
            else:
                outcome = "incomplete:" + str(msg.get("state"))
    except Exception as e:  # noqa: BLE001
        outcome = f"error:{type(e).__name__}"
    results[idx] = {"outcome": outcome, "total_ms": (time.perf_counter() - t0) * 1000, "frame_rtts": frame_rtts, "busy": busy}


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[max(0, min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1)))))]


async def main(a: argparse.Namespace) -> None:
    frames = load_frames(a.frames)
    results: dict[int, dict] = {}
    t0 = time.perf_counter()
    gate = asyncio.Semaphore(a.concurrency)
    await asyncio.gather(*(one_client(i, a.base, frames, results, (i / a.clients) * a.ramp, gate) for i in range(a.clients)))
    wall = time.perf_counter() - t0
    totals = [r["total_ms"] for r in results.values()]
    rtts = [x for r in results.values() for x in r["frame_rtts"]]
    outcomes: dict[str, int] = {}
    for r in results.values():
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    print(f"\nclients={a.clients} ramp={a.ramp}s frames/client={a.frames} wall={wall:.1f}s")
    print(f"outcomes: {outcomes}")
    print(f"frames processed: {len(rtts)}  throughput: {len(rtts) / wall:.1f} frames/s")
    print(f"per-frame RTT ms  p50={pct(rtts, 50):.0f} p90={pct(rtts, 90):.0f} p95={pct(rtts, 95):.0f} p99={pct(rtts, 99):.0f} max={max(rtts) if rtts else 0:.0f}")
    print(f"session total ms  p50={pct(totals, 50):.0f} p90={pct(totals, 90):.0f} p95={pct(totals, 95):.0f} mean={statistics.mean(totals):.0f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--clients", type=int, default=50)
    p.add_argument("--ramp", type=float, default=5.0, help="seconds over which clients start")
    p.add_argument("--frames", type=int, default=10)
    p.add_argument("--concurrency", type=int, default=10, help="max simultaneous sessions (number of kiosks)")
    p.add_argument("--base", default="http://127.0.0.1:8000")
    asyncio.run(main(p.parse_args()))
