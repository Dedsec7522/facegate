"""Mark which probe photographs the application's quality gate can process, using the accuracy pass.

    python tools/screen_probes.py [run_id]      (default: the accuracy run of the latest suite)

A probe is *usable* when the server reached a verdict on it at low load, whatever the verdict was (correct, wrong or
"unknown"). It is *not usable* when the server analysed every frame and never accepted one: a second face in the
photograph, or a face turned too far to collect evidence. Selecting on "reached a verdict" and not on "matched
correctly" keeps the model's mistakes in the load stages.

Writes `load_probes` into test_datasets/enrolled.json. Load stages use those; the accuracy pass always uses all probes.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_config import settings as S  # noqa: E402
from dashboard.routes import rows  # noqa: E402

ENROLLED = S.DATASET / "enrolled.json"


def main() -> None:
    run = sys.argv[1] if len(sys.argv) > 1 else None
    if not run:
        suite = json.loads((S.RESULTS / "suite.json").read_text())
        run = next(s["run_id"] for s in suite["stages"] if "accuracy" in s["name"].lower() and s.get("run_id"))
    verdict: dict[str, str] = {}
    for r in rows(S.RESULTS / "runs" / run):
        if r["category"] != "genuine":
            continue
        gated = (r.get("reason") or "").startswith("gate:")
        verdict[r["probe"]] = "gated" if gated else "no_verdict" if r["verdict"] == "error" else "usable"
    data = json.loads(ENROLLED.read_text())
    stats = Counter(verdict.values())
    none = 0
    for e in data["enrolled"]:
        e["load_probes"] = [p for p in e["probes"] if verdict.get(p) == "usable"]
        none += not e["load_probes"]
    data["screened_with"] = run
    ENROLLED.write_text(json.dumps(data, indent=1))
    print(f"probes: {dict(stats)}; employees with at least one usable probe: {len(data['enrolled']) - none} of {len(data['enrolled'])}")


if __name__ == "__main__":
    main()
