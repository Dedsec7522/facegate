"""Build the final reports from the recorded runs of the latest suite. Every number comes from the run files; nothing
is estimated. Missing data is printed as "not measured".

    python tools/make_reports.py

Writes to reports/:
  final_report.html              everything below in one page (also linked from the dashboard's History tab)
  performance_by_stage.csv       Report 1: concurrency and performance
  model_performance.csv          Report 2: recognition metrics against targets
  employee_verification.csv      Report 3: one row per employee and step of the largest attendance stage
  predictions_all.csv            every recognition of every stage
  confusion_pairs.csv            expected identity -> predicted identity, with counts (accuracy / confusion report)
  attendance_db_validation.csv   every database check of every stage
  hardware_utilisation.csv       CPU / RAM per stage
  checklist.csv                  PASS / FAIL checklist behind the feasibility verdict
"""
from __future__ import annotations

import csv
import html
import json
import platform
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_config import settings as S  # noqa: E402
from dashboard.routes import COLUMNS, flat, rows  # noqa: E402

RUNS = S.RESULTS / "runs"
OUT = S.REPORTS

# Suggested acceptance criteria (from the test brief). They are starting points, not industry standards; change them
# here once the business requirements are agreed.
T_CORRECT = 0.99            # correct identification rate on the accuracy pass
T_FAR = 0.001               # false acceptance rate on non-enrolled inputs
T_FRR = 0.01                # false rejection rate
T_P95_MS = 2000             # 95th-percentile recognition time (session request -> verdict)
T_NO_VERDICT = 0.01         # share of recognitions that reached no verdict (timeouts, errors)


def jload(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None


def pct(x, d=2):
    return "not measured" if x is None else f"{x * 100:.{d}f}%"


def num(x, d=0):
    return "not measured" if x is None else f"{x:,.{d}f}"


def write_csv(name: str, header: list[str], data: list[list]) -> None:
    with open(OUT / name, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(data)


def table(header: list[str], data: list[list], cls: str = "") -> str:
    def cell(v):
        s = html.escape(str(v))
        c = " class='pass'" if s == "PASS" else " class='fail'" if s in ("FAIL", "NOT READY") else " class='info'" if s in ("INFO", "CONDITIONALLY READY") else ""
        return f"<td{c}>{s}</td>"
    return f"<table class='{cls}'><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in header) + "</tr>" + "".join("<tr>" + "".join(cell(v) for v in r) + "</tr>" for r in data) + "</table>"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    suite = jload(S.RESULTS / "suite.json") or {"stages": []}
    stages = []
    for st in suite["stages"]:
        rid = st.get("run_id")
        s = jload(RUNS / rid / "summary.json") if rid else None
        if s:
            stages.append({"name": st["name"], "run_id": rid, "s": s, "db": jload(RUNS / rid / "db_validation.json") or {}, "info": jload(RUNS / rid / "stage_info.json") or {}})
    if not stages:
        raise SystemExit("no finished stages found in test_results/suite.json")
    # Responsiveness during load (tools/health_probe.py: one health request a second against the same event loop that
    # serves the recognitions). A blocked or deadlocked server shows up as failed or very slow probes.
    probes = []
    try:
        with open(S.RESULTS / "health_probe.jsonl", encoding="utf-8") as fh:
            probes = [json.loads(line) for line in fh if line.strip()]
    except FileNotFoundError:
        pass
    for x in stages:
        mine = [p for p in probes if x["s"]["started"] <= p["t"] <= x["s"]["ended"]]
        ms = sorted(p["ms"] for p in mine if p["ms"] is not None and p["status"] == 200)
        x["probe"] = {"n": len(mine), "failed": len(mine) - len(ms), "p50": ms[len(ms) // 2] if ms else None, "p95": ms[int(len(ms) * 0.95)] if ms else None,
                      "max": ms[-1] if ms else None} if mine else None
    # Attendance responses, recomputed from the raw records so that different things are not mixed up:
    #   wrong         the server answered with something it must not (a second stored event of the same kind)
    #   server_error  the server answered 5xx
    #   no_response   the request got no HTTP answer at all (connection refused or timed out): a capacity failure
    #   created / refused   as expected
    # In the sustained stage the first check-in the server *confirms* must be stored and later ones refused; the scan
    # that was sent first may have received no answer under overload.
    for x in stages:
        a = {"created": 0, "refused": 0, "no_response": 0, "wrong": 0, "server_error": 0}
        seen: set = set()
        allrows = sorted(rows(RUNS / x["run_id"]), key=lambda r: r["t"])
        for r in allrows:
            at = r.get("attendance")
            if not at:
                continue
            st, key = at["status"], (r.get("expected_code"), at["action"])
            if st == 0:
                a["no_response"] += 1
            elif st >= 500:
                a["server_error"] += 1
            elif st == 201:
                first = key not in seen
                seen.add(key)
                a["created" if (first and at.get("employee_code") == r.get("expected_code")) else "wrong"] += 1
            elif st == 409:
                # A refusal never creates data. Whether a refused first event left a gap is covered by the database
                # validation, which proves every confirmed event is stored once and nothing else is.
                a["refused"] += 1
            else:
                a["wrong"] += 1
        x["att"] = a
        # verification log: the server may have decided recognitions whose answer never reached the client
        va = (x["db"].get("counts") or {}).get("verification_attempts")
        if va is not None:
            v_i, v_r = sum(r.get("outcome") == "identified" for r in allrows), sum(r.get("outcome") == "rejected" for r in allrows)
            un = len(allrows) - v_i - v_r
            a_i, a_r = va.get("identified", 0), sum(n for k, n in va.items() if k != "identified")
            log_ok = a_i >= v_i and a_r >= v_r and (a_i - v_i) + (a_r - v_r) <= un
            for c in x["db"].get("checks", []):
                if c["check"].startswith("Verification log"):
                    c.update(check="Verification log has a row for every verdict the test received", ok=log_ok, failures=0 if log_ok else 1,
                             examples=[] if log_ok else c["examples"], note=f"log {a_i} / {a_r} (identified / rejected), test received {v_i} / {v_r}; {un} recognitions ended without an answer")
            x["db"]["ok"] = all(c["ok"] for c in x["db"].get("checks", []))
    by_scn = lambda sc: [x for x in stages if x["s"]["scenario"] == sc]  # noqa: E731
    att = by_scn("attendance")
    acc = (by_scn("accuracy") or [None])[0]
    burst = (by_scn("burst") or [None])[0]
    sust = (by_scn("sustained") or [None])[0]
    live = (by_scn("liveness") or [None])[0]

    # ---------------------------------------------------------------- Report 1: concurrency and performance
    def stage_row(x):
        s, m, v, sy = x["s"], x["s"]["metrics"], x["s"]["verdicts"], x["s"]["system"]
        tot = next((e for e in s["locust"] if e["name"] == "Aggregated"), {})
        wrong = v.get("incorrect", 0) + v.get("false_accept", 0)
        no_verdict = v.get("error", 0) / s["predictions"] if s["predictions"] else None
        timeouts = sum(n for k, n in s["reasons"].items() if "timeout" in k)
        p95 = (m.get("identify_ms") or {}).get("p95")   # time to a correct match; refused inputs are bounded by the client's frame limit instead
        ok_integrity = wrong == 0 and x["att"]["wrong"] == 0 and x["db"].get("ok") is True
        ok_complete = no_verdict is not None and no_verdict <= T_NO_VERDICT and timeouts == 0 and not x["info"].get("timed_out") and x["att"]["no_response"] == 0 and x["att"]["server_error"] == 0
        ok_speed = p95 is not None and p95 <= T_P95_MS
        x["checks"] = {"integrity": ok_integrity, "complete": ok_complete, "speed": ok_speed, "wrong": wrong, "timeouts": timeouts, "no_verdict": no_verdict}
        x["pass"] = ok_integrity and ok_complete and ok_speed
        why = [] if x["pass"] else [t for t, ok in (("integrity", ok_integrity), ("requests without an answer / timeouts / server errors", ok_complete), (f"p95 > {T_P95_MS} ms", ok_speed)) if not ok]
        return [x["name"], s["users"], s["inflight_peak"], tot.get("requests"), (tot.get("requests") or 0) - (tot.get("failures") or 0), tot.get("failures"),
                s["predictions"], v.get("correct", 0) + v.get("correct_reject", 0), wrong, v.get("rejected", 0), v.get("error", 0),
                x["att"]["created"], x["att"]["refused"], x["att"]["no_response"], x["att"]["server_error"], x["att"]["wrong"],
                (m.get("identify_ms") or {}).get("p50"), p95, (m.get("identify_ms") or {}).get("p99"), m["recognition_ms"]["p95"], tot.get("rps"), sy["cpu_avg"], sy["cpu_max"], sy["ram_avg"], s["duration_s"],
                "PASS" if x["pass"] else "FAIL", ", ".join(why)]

    perf_header = ["Stage", "Concurrent users", "Peak recognitions in flight", "Total requests", "Successful", "Failed", "Recognitions", "Correct", "Wrong identity",
                   "Rejected", "No verdict", "Attendance stored", "Duplicates refused", "Attendance: no answer", "Attendance: server error (5xx)", "Attendance: wrong answer", "Median ms to a correct match", "P95 ms to a correct match", "P99 ms to a correct match", "P95 ms all attempts", "Requests/s", "CPU % avg", "CPU % max", "RAM % avg", "Duration s", "Result", "Why"]
    perf = [stage_row(x) for x in stages if x["s"]["scenario"] in ("attendance", "burst", "sustained")]
    write_csv("performance_by_stage.csv", perf_header, perf)

    # ---------------------------------------------------------------- Report 2: model performance
    model: list[list] = []
    if acc:
        m, bc = acc["s"]["metrics"], acc["s"]["by_category"]
        g = bc.get("genuine", {})
        gd = g.get("correct", 0) + g.get("incorrect", 0) + g.get("rejected", 0)
        clean = {"correct": g.get("correct", 0) / gd if gd else None, "incorrect": g.get("incorrect", 0) / gd if gd else None, "frr": g.get("rejected", 0) / gd if gd else None}
        nf, tf = bc.get("no_face", {}), bc.get("two_faces", {})
        # Split the refusals of plain genuine probes: the quality gate declined the photograph, or the model had a usable face and did not match it.
        arows = [r for r in rows(RUNS / acc["run_id"]) if r["category"] == "genuine"]
        gate = Counter((r.get("reason") or "")[5:] for r in arows if r["verdict"] == "rejected" and (r.get("reason") or "").startswith("gate:"))
        modelrej = Counter(r.get("reason") or "?" for r in arows if r["verdict"] == "rejected" and not (r.get("reason") or "").startswith("gate:"))
        usable = gd - sum(gate.values())
        ok_scores = [r["match_score"] for r in arows if r["verdict"] == "correct" and r.get("match_score") is not None]
        fa = [r for r in rows(RUNS / acc["run_id"]) if r["verdict"] in ("false_accept", "incorrect")]

        def rej(d):
            n = d.get("correct_reject", 0) + d.get("false_accept", 0)
            return d.get("correct_reject", 0) / n if n else None

        model += [
            ["Correct recognition rate (unseen probe photos)", pct(clean["correct"]), f">= {pct(T_CORRECT, 0)}", "PASS" if clean["correct"] is not None and clean["correct"] >= T_CORRECT else "FAIL", f"{g.get('correct', 0)} of {gd} genuine attempts with a verdict"],
            ["Incorrect identification rate", pct(clean["incorrect"], 3), "0 (as low as possible)", "PASS" if clean["incorrect"] == 0 else "FAIL", f"{g.get('incorrect', 0)} matched to another employee"],
            ["False acceptance rate (not enrolled)", pct(m["far"], 3), f"<= {pct(T_FAR, 1)}", "PASS" if m["far"] is not None and m["far"] <= T_FAR else "FAIL", f"{m['negatives'].get('false_accept', 0)} of {m['negatives_decided']} non-enrolled inputs identified"],
            ["False rejection rate", pct(clean["frr"]), f"<= {pct(T_FRR, 0)}", "PASS" if clean["frr"] is not None and clean["frr"] <= T_FRR else "FAIL", f"{g.get('rejected', 0)} genuine attempts refused"],
            ["  of which refused by the quality gate (photo unusable)", pct(sum(gate.values()) / gd) if gd else "not measured", "INFO", "INFO", ", ".join(f"{k} {n}" for k, n in gate.most_common()) + ": a second face in the photograph, or a face turned away / too soft for the gate"],
            ["  of which not recognised by the model", pct(sum(modelrej.values()) / gd) if gd else "not measured", "INFO", "INFO", ", ".join(f"{k} {n}" for k, n in modelrej.most_common())],
            ["Correct recognition rate on photos the quality gate accepted", pct(g.get("correct", 0) / usable) if usable else "not measured", f">= {pct(T_CORRECT, 0)}", "PASS" if usable and g.get("correct", 0) / usable >= T_CORRECT else "FAIL", f"{g.get('correct', 0)} of {usable}"],
            ["Unknown-face rejection", pct(m["unknown_rejection_rate"]), "100% on test dataset", "PASS" if m["unknown_rejection_rate"] == 1 else "FAIL", str(bc.get("unknown", {}))],
            ["No-face rejection", pct(rej(nf)), "100% on test dataset", "PASS" if rej(nf) == 1 else "FAIL", str(nf)],
            ["Two-equal-faces rejection", pct(rej(tf)), "100% on test dataset", "PASS" if rej(tf) == 1 else "FAIL", str(tf)],
            ["Precision / recall / F1", f"{pct(m['precision'])} / {pct(m['recall'])} / {pct(m['f1'])}", "model-dependent", "INFO", "over identifications, all input types of the accuracy pass"],
            ["Average match score of correct matches", num(sum(ok_scores) / len(ok_scores), 3) if ok_scores else "not measured", "model-dependent", "INFO", f"cosine similarity, not a probability; lowest {min(ok_scores) if ok_scores else 'n/a'}, accept threshold {acc['info'].get('settings', {}).get('match_accept_threshold')}"],
            ["Wrong identifications in the accuracy pass", str(len(fa)), "0", "PASS" if not fa else "FAIL", "; ".join(f"{r.get('label')} -> {r.get('predicted_code')} (score {r.get('match_score')}, runner-up {r.get('second_score')})" for r in fa)],
            ["Highest score offered by a non-enrolled face", num(m["impostor_score_max"], 3), "below the accept threshold", "INFO", "best gallery match for people who are not enrolled"],
            ["P95 model time per frame (server-reported)", f"{num(m['server_frame_ms']['p95'])} ms", "INFO", "INFO", f"median {num(m['server_frame_ms']['p50'])} ms; a verdict needs a median of {num(m['frames_to_identify']['p50'])} frames"],
            ["P95 time to a correct match at low load", f"{num(m['identify_ms']['p95'])} ms", f"<= {T_P95_MS} ms", "PASS" if (m["identify_ms"]["p95"] or 1e9) <= T_P95_MS else "FAIL", f"session request to verdict, 8 concurrent users; median {num(m['identify_ms']['p50'])} ms"],
        ]
        for variant in ("dark", "bright", "blur"):
            d = bc.get(f"genuine_{variant}", {})
            n = d.get("correct", 0) + d.get("incorrect", 0) + d.get("rejected", 0)
            model.append([f"Correct recognition, {variant} frames", pct(d.get("correct", 0) / n) if n else "not measured", "INFO", "INFO", f"{d} of {n}"])
    dup = sum(c["failures"] for x in stages for c in x["db"].get("checks", []) if "duplicate" in c["check"].lower() or "window" in c["check"].lower())
    mapping = sum(c["failures"] for x in stages for c in x["db"].get("checks", []) if "expected employee" in c["check"].lower()) + sum(x["s"]["attendance"]["wrong_employee"] for x in stages)
    load_wrong = sum(x["s"]["verdicts"].get("incorrect", 0) + x["s"]["verdicts"].get("false_accept", 0) for x in stages if x is not acc)
    load_ident = sum(x["s"]["verdicts"].get("correct", 0) for x in stages if x is not acc)
    events_total = sum(x["db"].get("counts", {}).get("db_events", 0) for x in stages)
    model += [
        ["Wrong identity under load (all load stages)", str(load_wrong), "0", "PASS" if load_wrong == 0 else "FAIL", f"against {load_ident:,} correct identifications"],
        ["Duplicate attendance records", str(dup), "0", "PASS" if dup == 0 else "FAIL", f"database check over {events_total:,} stored events"],
        ["Incorrect attendance mapping", str(mapping), "0", "PASS" if mapping == 0 else "FAIL", "stored employee differs from the person who scanned"],
    ]
    write_csv("model_performance.csv", ["Metric", "Actual result", "Target", "Status", "Basis"], model)

    # ---------------------------------------------------------------- Report 3 + all predictions + confusion pairs
    conf: Counter = Counter()
    with open(OUT / "predictions_all.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for x in stages:
            for r in rows(RUNS / x["run_id"]):
                w.writerow(flat(r))
                if r.get("outcome") == "identified" or r["category"].startswith("genuine"):
                    exp = r.get("expected_code") or f"(not enrolled: {r['category']})"
                    pred = r.get("predicted_code") or ("(rejected)" if r.get("outcome") == "rejected" else "(no verdict)")
                    conf[(exp, pred)] += 1
    off = sorted(((e, p, n) for (e, p), n in conf.items() if e != p), key=lambda t: (-t[2], t[0]))
    diag = sum(n for (e, p), n in conf.items() if e == p)
    write_csv("confusion_pairs.csv", ["Expected identity", "Predicted identity", "Count"], [[e, p, n] for (e, p), n in sorted(conf.items()) if e != p] or [["(none)", "(none)", 0]])
    big = max(att, key=lambda x: x["s"]["users"]) if att else None
    emp_rows: list[list] = []
    if big:
        for r in sorted(rows(RUNS / big["run_id"]), key=lambda r: (r.get("expected_code") or "", r["t"])):
            f = flat(r)
            a_ok = f["attendance_ok"]
            res = "PASS" if f["verdict"] == "correct" and a_ok is not False else "FAIL"
            emp_rows.append([f["label"], f["step"], f["attempt"], f["expected_code"], f["predicted_code"] or ("none: " + (f["reason"] or f["error"] or f["outcome"] or "")),
                             "" if f["match_score"] is None else f["match_score"], f["total_ms"], "n/a" if a_ok is None else ("Yes" if a_ok else "No") + f" ({f['attendance_status']})", res])
    emp_header = ["Employee ID", "Step", "Attempt", "Expected identity", "Predicted identity", "Match score", "Response time ms", "Attendance verified", "Result"]
    write_csv("employee_verification.csv", emp_header, emp_rows)

    # ---------------------------------------------------------------- database validation, hardware
    dbv = [[x["name"], c["check"], "PASS" if c["ok"] else "FAIL", c["failures"], "; ".join(map(str, c["examples"])), c.get("note", "")] for x in stages for c in x["db"].get("checks", [])]
    write_csv("attendance_db_validation.csv", ["Stage", "Check", "Result", "Failures", "Examples", "Note"], dbv)
    hw_header = ["Stage", "Users", "CPU % avg (machine)", "CPU % max", "FaceGate API % avg", "FaceGate API % max", "Load generator % avg", "Other processes % avg",
                 "RAM % avg", "RAM % max", "API memory MB start", "API memory MB end", "API memory MB max", "Health check after load (median ms)", "Health check 15 s later (median ms)",
                 "Health probes during load", "Probes failed", "Probe median ms", "Probe p95 ms", "Probe max ms"]
    hw = [[x["name"], x["s"]["users"], *(x["s"]["system"].get(k) for k in ("cpu_avg", "cpu_max", "api_cpu_avg", "api_cpu_max", "generator_cpu_avg", "other_cpu_avg", "ram_avg", "ram_max",
                                                                           "api_rss_mb_start", "api_rss_mb_end", "api_rss_mb_max")),
           (x["info"].get("recovery_immediately") or {}).get("median_ms"), (x["info"].get("recovery_after_15s") or {}).get("median_ms"),
           *((x["probe"] or {}).get(k, "not measured") for k in ("n", "failed", "p50", "p95", "max"))] for x in stages]
    write_csv("hardware_utilisation.csv", hw_header, hw)

    # ---------------------------------------------------------------- feasibility
    passing = [x for x in att if x.get("pass")]
    max_ok = max((x["s"]["users"] for x in passing), default=0)
    # "reliably supported" needs every smaller stage to pass too
    reliable = 0
    for x in sorted(att, key=lambda x: x["s"]["users"]):
        if x.get("pass"):
            reliable = x["s"]["users"]
        else:
            break
    s500 = next((x for x in att if x["s"]["users"] >= 500), None)
    integrity_fail = [x["name"] for x in stages if x.get("checks") and not x["checks"]["integrity"]] + [x["name"] for x in stages if x["db"] and x["db"].get("ok") is False and x["name"] not in [y["name"] for y in stages if y.get("checks")]]
    integrity_fail = sorted(set(integrity_fail))
    model_fail = [r[0] for r in model if r[3] == "FAIL"]
    security_fail = [r[0] for r in model if r[3] == "FAIL" and any(k in r[0] for k in ("False acceptance", "Incorrect", "Wrong identity", "Unknown-face", "Duplicate", "mapping"))]
    required = bool(acc and s500 and burst and sust)
    if not required:
        verdict = "NOT DETERMINED"
    elif integrity_fail or security_fail:
        verdict = "NOT READY"
    elif s500.get("pass") and burst.get("pass") and sust.get("pass") and not model_fail:
        verdict = "READY"
    else:
        verdict = "CONDITIONALLY READY"

    def peak_rate(x):
        s = x["s"]
        done = s["verdicts"].get("correct", 0) + s["verdicts"].get("correct_reject", 0) + s["verdicts"].get("rejected", 0)
        return done / s["duration_s"] if s["duration_s"] else None

    checklist = [
        ["Accuracy pass completed", "PASS" if acc else "FAIL", ""],
        ["All ten load tests completed", "PASS" if len(att) >= 8 and burst and sust else "FAIL", f"{len(att)} staged tests, burst {'yes' if burst else 'no'}, sustained {'yes' if sust else 'no'}"],
        ["No wrong identity in any stage", "PASS" if load_wrong == 0 and (not acc or acc["s"]["verdicts"].get("incorrect", 0) == 0) else "FAIL", f"{load_wrong} under load"],
        ["No non-enrolled person accepted", "PASS" if all(x["s"]["verdicts"].get("false_accept", 0) == 0 for x in stages) else "FAIL", ""],
        ["No duplicate attendance records", "PASS" if dup == 0 else "FAIL", f"{events_total:,} stored events checked"],
        ["No attendance stored for the wrong employee", "PASS" if mapping == 0 else "FAIL", ""],
        ["Stored attendance consistent with API responses in every stage", "PASS" if all(x["db"].get("ok") for x in stages if x["db"]) else "FAIL", ", ".join(x["name"] for x in stages if x["db"] and not x["db"].get("ok"))],
        [f"Correct recognition >= {pct(T_CORRECT, 0)} (accuracy pass)", next((r[3] for r in model if r[0].startswith("Correct recognition rate")), "FAIL"), next((r[1] for r in model if r[0].startswith("Correct recognition rate")), "")],
        [f"500 users: every recognition reaches a verdict (<= {pct(T_NO_VERDICT, 0)} without)", "PASS" if s500 and s500["checks"]["complete"] else "FAIL", f"{s500['s']['verdicts'].get('error', 0)} without verdict, {s500['checks']['timeouts']} server timeouts" if s500 else "not run"],
        [f"500 users: p95 time to a correct match <= {T_P95_MS} ms", "PASS" if s500 and s500["checks"]["speed"] else "FAIL", f"{num(s500['s']['metrics']['identify_ms']['p95'])} ms" if s500 else "not run"],
        ["500-user synchronised burst passes", "PASS" if burst and burst.get("pass") else "FAIL", perf[[p[0] for p in perf].index(burst["name"])][-1] if burst else "not run"],
        ["500-user sustained load passes", "PASS" if sust and sust.get("pass") else "FAIL", perf[[p[0] for p in perf].index(sust["name"])][-1] if sust else "not run"],
        ["API healthy after every stage", "PASS" if all((x["info"].get("recovery_after_15s") or {}).get("ok") == (x["info"].get("recovery_after_15s") or {}).get("of") for x in stages) else "FAIL", ""],
    ]
    probed = [x for x in stages if x.get("probe")]
    pf, pn = sum(x["probe"]["failed"] for x in probed), sum(x["probe"]["n"] for x in probed)
    worst = max((x["probe"]["max"] or 0 for x in probed), default=None)
    checklist.append(["Server stayed responsive during load (no deadlock or frozen event loop)",
                      "NOT MEASURED" if not probed else "PASS" if pf == 0 else "FAIL",
                      f"{pn - pf:,} of {pn:,} once-a-second health probes answered while the stages ran; slowest {num(worst)} ms" if probed else "health_probe.py was not running"])
    write_csv("checklist.csv", ["Check", "Result", "Evidence"], checklist)

    # ---------------------------------------------------------------- environment
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=S.REPO, capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "backend"], cwd=S.REPO, capture_output=True, text=True).stdout.strip())
    except Exception:  # noqa: BLE001
        commit, dirty = "?", False
    cpu_name = platform.processor()
    try:
        cpu_name = subprocess.run(["powershell", "-NoProfile", "-c", "(Get-CimInstance Win32_Processor).Name"], capture_output=True, text=True, timeout=20).stdout.strip() or cpu_name
    except Exception:  # noqa: BLE001
        pass
    import locust
    settings0 = (att[0]["info"].get("settings") if att else None) or {}
    other = [x["s"]["system"].get("other_cpu_avg") for x in stages if x["s"]["system"].get("other_cpu_avg") is not None]
    envrows = [
        ["Application under test", f"FaceGate backend at commit {commit}{' (backend working tree has uncommitted changes)' if dirty else ' (backend unmodified)'}, started with uvicorn, one process"],
        ["Test target", f"{S.API_URL}, PostgreSQL 16 in Docker on port {S.PG_PORT} (separate from the application's database)"],
        ["Machine", f"{cpu_name}; {psutil.cpu_count(logical=False)} cores / {psutil.cpu_count()} threads; {psutil.virtual_memory().total / 2**30:.1f} GB RAM; {platform.system()} {platform.release()}"],
        ["GPU", "not used: the application runs inference on the CPU only (OpenVINO / ONNX Runtime)"],
        ["Load generator", f"Locust {locust.__version__}, 1 master + worker processes on the same machine, Python {platform.python_version()}"],
        ["Other processes on the machine", f"used {min(other):.0f}-{max(other):.0f}% of the CPU on average during the stages (not part of the test; it reduces what the server could use)" if other else "not measured"],
        ["Test identities", f"{acc['s']['enrolled_employees'] if acc else stages[0]['s']['enrolled_employees']} enrolled employees from LFW, 100 non-enrolled people; enrolment photo and probe photos are different photographs"],
        ["Application settings during load stages", ", ".join(f"{k}={settings0.get(k)}" for k in ("kiosk_liveness", "match_accept_threshold", "adaptive_templates", "duplicate_scan_seconds", "relogin_cooldown_hours", "pad_live_threshold"))],
        ["Suite run", f"{datetime.fromtimestamp(suite.get('started', 0)):%Y-%m-%d %H:%M} to {datetime.fromtimestamp(suite.get('ended', 0) or 0):%H:%M}" if suite.get("started") else "?"],
    ]

    # ---------------------------------------------------------------- HTML
    feas = [
        ["Maximum reliably supported concurrent users", f"{reliable}" if reliable else "below the smallest stage", "largest stage that passed, with every smaller stage passing too"],
        ["Largest stage that passed on its own", str(max_ok), ""],
        ["Sustained throughput", f"{peak_rate(sust):.2f} completed recognitions per second" if sust and peak_rate(sust) else "not measured", "verdicts reached ÷ duration of the sustained stage"],
        ["Peak recognitions in flight", str(max(x["s"]["inflight_peak"] for x in stages)), "open verification streams at the same moment"],
        ["Recognition accuracy (accuracy pass)", next((r[1] for r in model if r[0].startswith("Correct recognition rate")), "not measured"), ""],
        ["Attendance data integrity", "no duplicate, missing or mis-assigned record" if dup == 0 and mapping == 0 and all(x["db"].get("ok") for x in stages if x["db"]) else "problems found, see database validation", f"{events_total:,} stored events checked"],
        ["Verdict", verdict, ""],
    ]
    burst_html = ""
    if burst:
        b, bs = burst["s"].get("burst") or {}, burst["info"].get("burst_server_side") or {}
        burst_html = "<h2>Synchronised burst</h2>" + table(["Measure", "Value"], [
            ["Employees released at the same instant", b.get("users_released")],
            ["Client: first camera frame sent after the release (median / p95 / max)", " / ".join(f"{num(b.get('first_frame_after_release_ms', {}).get(k))} ms" for k in ("p50", "p95", "max"))],
            ["Server: session requests answered within 0.5 s / 1 s / 2 s / 5 s of the release", " / ".join(str(bs.get(k, "not measured")) for k in ("answered_within_0.5s", "answered_within_1s", "answered_within_2s", "answered_within_5s"))],
            ["Server: most session requests completed in any 100 ms", bs.get("busiest_100ms", "not measured")],
            ["Peak recognitions in flight", burst["s"]["inflight_peak"]],
        ]) + "<p class='note'>Server times come from the test API's access log, which stamps a request when its response is sent. Camera frames travel inside WebSockets and are not logged individually by the application, so their server arrival times are not available without changing it.</p>"
    live_html = ""
    if live:
        lv = live["s"]
        live_html = "<h2>Passive anti-spoofing policy against photographs</h2><p class='note'>The load stages use the application's default kiosk policy (advisory). This stage switches the test instance to the stricter <i>passive</i> policy and replays the same photographs. They are photographs, so being refused is the intended outcome; this is not a measurement of how live faces fare.</p>" + table(
            ["Outcome", "Count"], [[k, n] for k, n in sorted(lv["verdicts"].items())] + [[k, n] for k, n in sorted(lv["reasons"].items())])

    css = """body{font:14px/1.55 Inter,system-ui,'Segoe UI',sans-serif;color:#1e1b2e;background:#f8f6ff;margin:0;padding:28px}main{max-width:1180px;margin:auto}
h1{font-size:24px;margin:0 0 4px}h2{font-size:16px;margin:30px 0 8px;color:#4c1d95}p{margin:6px 0}.note{color:#6b6487;font-size:12.5px}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #e6e1f5;border-radius:10px;overflow:hidden;font-size:12.5px;margin:8px 0}
th{background:#f1edff;text-align:left;padding:7px 9px;white-space:nowrap}td{padding:6px 9px;border-top:1px solid #e6e1f5;vertical-align:top}
td.pass{color:#15803d;font-weight:700}td.fail{color:#b91c1c;font-weight:700}td.info{color:#6d28d9;font-weight:600}.wide{display:block;overflow-x:auto}
.verdict{display:inline-block;padding:6px 16px;border-radius:999px;font-weight:700;font-size:16px;margin:10px 0}
.READY{background:#dcfce7;color:#15803d}.CONDITIONALLY{background:#fef3c7;color:#b45309}.NOT{background:#fee2e2;color:#b91c1c}.card{background:#fff;border:1px solid #e6e1f5;border-radius:12px;padding:14px 16px}"""
    files = ["performance_by_stage.csv", "model_performance.csv", "employee_verification.csv", "predictions_all.csv", "confusion_pairs.csv", "attendance_db_validation.csv", "hardware_utilisation.csv", "checklist.csv"]
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>FaceGate load test: final report</title><style>{css}</style></head><body><main>
<h1>FaceGate attendance load test: final report</h1>
<p class="note">Generated {datetime.now():%Y-%m-%d %H:%M} from the recorded runs in <code>test_results/runs</code>. Every figure is measured; anything that could not be measured says so.</p>
<div class="card"><span class="verdict {verdict.split()[0]}">{verdict}</span>
{table(["Question", "Answer", "Basis"], feas)}</div>
<h2>PASS / FAIL checklist</h2>{table(["Check", "Result", "Evidence"], checklist)}
<p class="note">Acceptance criteria used: correct recognition &ge; {pct(T_CORRECT, 0)}, FAR &le; {pct(T_FAR, 1)}, FRR &le; {pct(T_FRR, 0)}, p95 recognition time &le; {T_P95_MS} ms, at most {pct(T_NO_VERDICT, 0)} of recognitions without a verdict, no wrong identity, no duplicate or mis-assigned attendance record. These are the suggested starting criteria from the test brief, not industry standards; confirm them against the business requirement before treating the verdict as final.</p>
<h2>Report 1: concurrency and performance</h2><div class="wide">{table(perf_header, perf)}</div>
<p class="note">"Concurrent users" is the number of virtual employees alive in the stage. "Peak recognitions in flight" is how many had a verification stream open at the same moment. "Requests" are Locust's counts: HTTP calls, one entry per recognition, and one per camera frame; frames answered "busy" are counted as requests, not failures. "Time to a correct match" runs from the session request to the server's verdict for recognitions that identified the right employee; "all attempts" also includes refused inputs, which run until the client's frame limit.</p>
{burst_html}
<h2>Report 2: face recognition model performance</h2>{table(["Metric", "Actual result", "Target", "Status", "Basis"], model)}
<p class="note">Rates use only attempts that reached a verdict as the denominator; attempts without one are counted in Report 1. Correct rate = correct &divide; (correct + wrong identity + rejected) over genuine probes. FRR = rejected &divide; the same. FAR = non-enrolled inputs identified &divide; non-enrolled inputs with a verdict. Precision = correct &divide; all identifications; recall = correct &divide; genuine attempts with a verdict; F1 = harmonic mean. The match score is a cosine similarity, not a calibrated probability.</p>
<h2>Accuracy and confusion</h2><p>{diag:,} recognitions landed on the expected identity; {sum(n for _, _, n in off):,} did not (rejections, attempts without a verdict, and any wrong identity). The 25 most frequent off-diagonal pairs:</p>
{table(["Expected identity", "Predicted identity", "Count"], [list(t) for t in off[:25]] or [["none", "none", 0]])}
{live_html}
<h2>Report 3: individual employee verification ({html.escape(big['name']) if big else 'not run'})</h2>
<p class="note">{len(emp_rows):,} rows; the first 60 are shown. The full table is in <a href="employee_verification.csv">employee_verification.csv</a>, and every recognition of every stage is in <a href="predictions_all.csv">predictions_all.csv</a> (searchable in the dashboard's Predictions tab).</p>
<div class="wide">{table(emp_header, emp_rows[:60])}</div>
<h2>Attendance database validation</h2>{table(["Stage", "Stored events", "Check-ins", "Check-outs", "Refused requests", "Employees", "Result"], [[x["name"], x["db"].get("counts", {}).get("db_events"), x["db"].get("counts", {}).get("check_ins"), x["db"].get("counts", {}).get("check_outs"), x["db"].get("counts", {}).get("refused_requests"), x["db"].get("counts", {}).get("employees_with_events"), "PASS" if x["db"].get("ok") else "FAIL"] for x in stages if x["db"]])}
<p class="note">Read directly from the test database after each stage: every API-confirmed event exists for the right employee and action; no extra rows; no two check-ins or check-outs in a row; no two events inside the duplicate window; check-out after check-in; one day summary per employee whose first-in, last-out and worked minutes agree with the events. Failed checks, if any:</p>
{table(["Stage", "Check", "Result", "Failures", "Examples", "Note"], [r for r in dbv if r[2] == "FAIL"] or [["all stages", "all checks", "PASS", 0, "", ""]])}
<h2>Hardware utilisation</h2><div class="wide">{table(hw_header, hw)}</div>
<p class="note">CPU figures are shares of the whole machine (100% = all {psutil.cpu_count()} threads busy), sampled once a second. The health probes are one request a second to <code>/api/health</code> for the whole stage, answered by the same event loop that serves recognitions and attendance; a deadlocked or blocked server would fail them. GPU: not applicable. Database CPU is inside "other processes" because PostgreSQL runs in Docker's virtual machine and cannot be separated from outside it.</p>
<h2>Environment and reproduction</h2>{table(["Item", "Value"], envrows)}
<p class="note">Reproduce with <code>./start.ps1</code> then <code>python tools/run_suite.py</code> and <code>python tools/make_reports.py</code> (see README.md). Stage definitions: <code>test_config/stages.json</code>. Raw evidence per stage: <code>test_results/runs/&lt;run&gt;/</code> (predictions, Locust HTML report and CSVs, system samples, database validation). Test API log: <code>test_results/api.log</code>.</p>
<h2>Files</h2><p>{' · '.join(f'<a href="{f}">{f}</a>' for f in files)}</p>
</main></body></html>"""
    (OUT / "final_report.html").write_text(doc, encoding="utf-8")
    print(f"verdict: {verdict}; reliably supported users: {reliable}; reports in {OUT}")
    for r in checklist:
        print(f"  {r[1]:4} {r[0]}  {r[2]}")


if __name__ == "__main__":
    main()
