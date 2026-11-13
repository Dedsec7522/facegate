"""Extra pages on Locust's own web server (same port as the native Locust UI):

  /facegate                    live dashboard (recognition verdicts, attendance checks, system load, event log)
  /facegate/data               everything the dashboard shows, as JSON (polled once a second)
  /facegate/history            every finished run with its headline numbers and report files
  /facegate/predictions        per-prediction rows of one run (search / filter), ?format=csv to export
  /facegate/files/<path>       report files under reports/ and test_results/runs/

These endpoints only read the harness's own result files; they never talk to the application.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

from flask import Response, abort, jsonify, request, send_file, send_from_directory

HERE = Path(__file__).resolve().parent
COLUMNS = ["time", "stage", "step", "attempt", "category", "label", "expected_code", "predicted_code", "verdict", "outcome", "reason", "match_score", "second_score",
           "liveness_score", "frames_analysed", "busy", "total_ms", "server_frame_ms", "attendance_action", "attendance_status", "attendance_ok",
           "attendance_ms", "event_id", "session_id", "probe", "error"]


def rows(run_dir: Path):
    for f in sorted(run_dir.glob("predictions_w*.jsonl")):
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                if '"type":"prediction"' not in line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:  # noqa: BLE001
                    continue


def flat(r: dict) -> dict:
    a = r.get("attendance") or {}
    return {"time": datetime.fromtimestamp(r["t"]).strftime("%H:%M:%S.%f")[:-3], "stage": r.get("stage"), "step": r.get("step"), "attempt": r.get("attempt"),
            "category": r.get("category"), "label": r.get("label"), "expected_code": r.get("expected_code"), "predicted_code": r.get("predicted_code"),
            "verdict": r.get("verdict"), "outcome": r.get("outcome"), "reason": r.get("reason"), "match_score": r.get("match_score"), "second_score": r.get("second_score"),
            "liveness_score": r.get("liveness_score"), "frames_analysed": r.get("frames_analysed"), "busy": r.get("busy"),
            "total_ms": r.get("total_ms"), "server_frame_ms": r.get("server_frame_ms"), "attendance_action": a.get("action"), "attendance_status": a.get("status"),
            "attendance_ok": a.get("ok"), "attendance_ms": a.get("ms"), "event_id": a.get("event_id"), "session_id": r.get("session_id"), "probe": r.get("probe"),
            "error": r.get("error")}


def mount(environment, agg, S, runs: Path) -> None:
    app = environment.web_ui.app

    @app.after_request
    def _cors(resp):
        if request.path.startswith("/facegate"):
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/facegate")
    def _page():
        return send_file(HERE / "index.html")

    @app.route("/facegate/data")
    def _data():
        return jsonify(agg.snapshot(environment))

    @app.route("/facegate/history")
    def _history():
        out = []
        for d in sorted(runs.glob("*/summary.json"), reverse=True):
            try:
                s = json.loads(d.read_text())
            except Exception:  # noqa: BLE001
                continue
            m = s.get("metrics", {})
            db = None
            try:
                db = json.loads((d.parent / "db_validation.json").read_text())
            except Exception:  # noqa: BLE001
                pass
            files = [f.name for f in sorted(d.parent.iterdir()) if f.suffix in (".html", ".csv", ".md") or f.name in ("summary.json", "db_validation.json")]
            out.append({"run_id": s["run_id"], "stage": s.get("stage"), "scenario": s.get("scenario"), "users": s.get("users"), "started": s.get("started"),
                        "duration_s": s.get("duration_s"), "predictions": s.get("predictions"), "verdicts": s.get("verdicts"), "attendance": s.get("attendance"),
                        "correct_rate": m.get("correct_rate"), "far": m.get("far"), "frr": m.get("frr"), "p95_ms": (m.get("recognition_ms") or {}).get("p95"),
                        "inflight_peak": s.get("inflight_peak"), "cpu_avg": (s.get("system") or {}).get("cpu_avg"),
                        "db_ok": (db or {}).get("ok"), "db_problems": (db or {}).get("problems"), "files": files})
        reports = [f.name for f in sorted(S.REPORTS.glob("*")) if f.is_file()] if S.REPORTS.exists() else []
        return jsonify({"runs": out, "reports": reports})

    @app.route("/facegate/predictions")
    def _predictions():
        run = request.args.get("run") or agg.meta.get("run_id") or ""
        d = (runs / run).resolve()
        if not run or runs.resolve() not in d.parents or not d.is_dir():
            return jsonify({"run": run, "rows": [], "total": 0})
        q = (request.args.get("q") or "").lower()
        verdict = request.args.get("verdict") or ""
        out = []
        for r in rows(d):
            if verdict and r.get("verdict") != verdict:
                continue
            f = flat(r)
            if q and q not in " ".join(str(x) for x in (f["label"], f["predicted_code"], f["step"], f["reason"], f["category"])).lower():
                continue
            out.append(f)
        if request.args.get("format") == "csv":
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(out)
            return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="predictions_{run}.csv"'})
        limit = min(2000, int(request.args.get("limit") or 500))
        return jsonify({"run": run, "total": len(out), "rows": out[-limit:]})

    @app.route("/facegate/files/<path:p>")
    def _files(p: str):
        target = (S.ROOT / p).resolve()
        allowed = [S.REPORTS.resolve(), runs.resolve()]
        if not target.is_file() or not any(a in target.parents for a in allowed):
            abort(404)
        return send_from_directory(target.parent, target.name)
