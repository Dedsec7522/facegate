"""Deadlock / responsiveness watchdog for the test API: one GET /api/health per second, forever.

    python tools/health_probe.py          appends to test_results/health_probe.jsonl until stopped

The health endpoint is answered by the same event loop that serves every WebSocket and attendance request, so if that
loop were ever blocked or deadlocked this probe would time out. Each line is {"t": epoch, "ms": latency or null,
"status": code or error}. tools/make_reports.py joins the lines to each stage by time. One request a second is far too
little to influence the measurement.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_config import settings as S  # noqa: E402

OUT = S.RESULTS / "health_probe.jsonl"
TIMEOUT_S = 10


def main() -> None:
    s = requests.Session()
    with open(OUT, "a", encoding="utf-8") as fh:
        while True:
            t = time.time()
            t0 = time.perf_counter()
            try:
                r = s.get(f"{S.API_URL}/api/health", timeout=TIMEOUT_S)
                row = {"t": round(t, 2), "ms": round((time.perf_counter() - t0) * 1000, 1), "status": r.status_code}
            except Exception as e:  # noqa: BLE001 - a refused or timed-out probe is the data we are after
                row = {"t": round(t, 2), "ms": None, "status": type(e).__name__}
                s = requests.Session()
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            time.sleep(max(0.0, 1.0 - (time.time() - t)))


if __name__ == "__main__":
    main()
