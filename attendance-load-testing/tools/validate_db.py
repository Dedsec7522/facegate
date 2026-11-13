"""Check the attendance rows actually stored in the test database against what the test run expected.

An HTTP 201 only says the API claimed to store an event. This script reads the tables directly and verifies:
  1. every event the API confirmed exists, for the right employee, with the right action
  2. the database holds no attendance events the test did not create
  3. no employee has two consecutive check-ins or check-outs (duplicates), nor two events inside the duplicate window
  4. every check-out is later than its check-in, and stored times match the times the API returned
  5. each employee has exactly one day summary; first-in / last-out / worked minutes agree with the events
  6. refused (409) requests left no row behind
  7. the verification-attempt log has one row per recognition verdict

    python tools/validate_db.py <run_id>        (run before the database is reset for the next stage)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_config import settings as S  # noqa: E402
from dashboard.routes import rows  # noqa: E402


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def validate(run_id: str) -> dict:
    run_dir = S.RESULTS / "runs" / run_id
    preds = list(rows(run_dir))
    confirmed = {}      # event_id -> prediction
    refused = 0
    for p in preds:
        a = p.get("attendance")
        if not a:
            continue
        if a["status"] == 201 and a.get("event_id"):
            confirmed[a["event_id"]] = p
        elif a["status"] == 409:
            refused += 1

    with psycopg.connect(f"{S.PG_DSN}/{S.PG_DB}") as c:
        ev = c.execute("""select e.id, emp.employee_code, e.action::text, e.occurred_at, e.voided, e.method::text, e.verification_attempt_id, e.match_score
                          from attendance_events e join employees emp on emp.id = e.employee_id order by emp.employee_code, e.occurred_at""").fetchall()
        days = c.execute("""select emp.employee_code, d.attendance_date, d.first_in, d.last_out, d.worked_minutes, d.is_open, d.status
                            from attendance_days d join employees emp on emp.id = d.employee_id""").fetchall()
        attempts = dict(c.execute("select outcome::text, count(*) from verification_attempts where purpose = 'attendance' group by 1").fetchall())
        dup_days = c.execute("select count(*) from (select employee_id, attendance_date from attendance_days group by 1,2 having count(*) > 1) x").fetchone()[0]

    checks, problems = [], []

    def check(name: str, bad: list, note: str = "") -> None:
        checks.append({"check": name, "ok": not bad, "failures": len(bad), "examples": bad[:5], "note": note})
        problems.extend(bad)

    db = {r[0]: r for r in ev}
    check("Every API-confirmed event is stored", [f"{p['expected_code']} {eid} missing" for eid, p in confirmed.items() if eid not in db],
          f"{len(confirmed)} confirmed by the API, {len(db)} rows in attendance_events")
    check("Stored event belongs to the expected employee and action",
          [f"{eid}: stored {db[eid][1]}/{db[eid][2]}, expected {p['expected_code']}/{p['attendance']['action']}" for eid, p in confirmed.items()
           if eid in db and (db[eid][1] != p["expected_code"] or db[eid][2] != p["attendance"]["action"])])
    check("No attendance rows the test did not create", [f"{r[1]} {r[0]} {r[2]}" for r in ev if r[0] not in confirmed])
    check("Stored time equals the time the API returned",
          [f"{eid}: {db[eid][3].isoformat()} vs {p['attendance']['occurred_at']}" for eid, p in confirmed.items()
           if eid in db and p["attendance"].get("occurred_at") and abs((db[eid][3] - _ts(p["attendance"]["occurred_at"])).total_seconds()) > 0.001])
    # The server stamps the event while it handles the request, so the stored time must lie between the moment the
    # test sent the attendance request and the moment it got the answer (2 s of slack for clock rounding). A fixed
    # tolerance would report a slow answer under load as a wrong timestamp.
    def _late(eid: str, p: dict) -> float:
        sent = p["t"] + p.get("total_ms", 0) / 1000
        got = sent + p["attendance"].get("ms", 0) / 1000
        ts = db[eid][3].timestamp()
        return max(sent - 2 - ts, ts - got - 2, 0.0)

    check("Stored time lies between the test's attendance request and its response",
          [f"{eid}: outside by {_late(eid, p):.1f}s" for eid, p in confirmed.items() if eid in db and _late(eid, p) > 0])

    per = defaultdict(list)
    for r in ev:
        if not r[4]:
            per[r[1]].append(r)
    seq_bad, win_bad, order_bad = [], [], []
    for code, es in per.items():
        for a, b in zip(es, es[1:]):
            if a[2] == b[2]:
                seq_bad.append(f"{code}: two {a[2]} in a row ({a[0]}, {b[0]})")
            if (b[3] - a[3]).total_seconds() < S.DUPLICATE_WINDOW_S:
                win_bad.append(f"{code}: events {(b[3] - a[3]).total_seconds():.1f}s apart")
            if a[2] == "check_in" and b[2] == "check_out" and b[3] <= a[3]:
                order_bad.append(f"{code}: check-out not after check-in")
        if es and es[0][2] != "check_in":
            seq_bad.append(f"{code}: first event is {es[0][2]}")
    check("No duplicate check-in or check-out per employee", seq_bad, f"{len(per)} employees with events")
    check(f"No two events inside the {S.DUPLICATE_WINDOW_S}s duplicate window", win_bad)
    check("Check-out is later than check-in", order_bad)
    check("One day-summary row per employee and day", [f"{dup_days} employee/day pairs duplicated"] if dup_days else [])

    day = {d[0]: d for d in days}
    day_bad = []
    for code, es in per.items():
        d = day.get(code)
        if not d:
            day_bad.append(f"{code}: no day summary")
            continue
        ins = [e[3] for e in es if e[2] == "check_in"]
        outs = [e[3] for e in es if e[2] == "check_out"]
        if ins and d[2] != min(ins):
            day_bad.append(f"{code}: first_in {d[2]} != {min(ins)}")
        if outs and d[3] != max(outs):
            day_bad.append(f"{code}: last_out {d[3]} != {max(outs)}")
        if bool(d[5]) != (es[-1][2] == "check_in"):
            day_bad.append(f"{code}: is_open={d[5]} but last event is {es[-1][2]}")
        if ins and outs:
            want = int((max(outs) - min(ins)).total_seconds() // 60)
            if abs(d[4] - want) > 1:
                day_bad.append(f"{code}: worked {d[4]} min, events say {want}")
    check("Day summary agrees with the events (first in, last out, worked minutes, open flag)", day_bad, f"{len(days)} day rows")
    check("Day summaries exist only for employees with events", [f"{c}: summary without events" for c in day if c not in per])

    # Every recognition that reached a server verdict writes one verification_attempts row.
    v_ident = sum(1 for p in preds if p.get("outcome") == "identified")
    v_rej = sum(1 for p in preds if p.get("outcome") == "rejected")
    a_ident = attempts.get("identified", 0)
    a_rej = sum(n for k, n in attempts.items() if k != "identified")
    # The server may have reached a verdict the client never received (the client hit its own deadline, or the
    # connection broke), so the log may hold up to `unanswered` more rows than the test saw. It must never hold fewer.
    unanswered = sum(1 for p in preds if p.get("outcome") not in ("identified", "rejected"))
    surplus = (a_ident - v_ident) + (a_rej - v_rej)
    log_ok = a_ident >= v_ident and a_rej >= v_rej and surplus <= unanswered
    check("Verification log has a row for every verdict the test received", ([] if log_ok else [f"log: {a_ident} identified / {a_rej} rejected; test saw {v_ident} / {v_rej}; {unanswered} recognitions ended without an answer"]),
          f"log {a_ident} / {a_rej}, test received {v_ident} / {v_rej}; {unanswered} recognitions ended without an answer and may still have been decided by the server")

    out = {"run_id": run_id, "checked_at": datetime.now().isoformat(timespec="seconds"), "ok": not problems, "problems": len(problems), "checks": checks,
           "counts": {"api_confirmed_events": len(confirmed), "db_events": len(ev), "refused_requests": refused, "employees_with_events": len(per),
                      "day_rows": len(days), "check_ins": sum(1 for r in ev if r[2] == "check_in"), "check_outs": sum(1 for r in ev if r[2] == "check_out"),
                      "verification_attempts": attempts}}
    (run_dir / "db_validation.json").write_text(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    r = validate(sys.argv[1])
    print(json.dumps({k: r[k] for k in ("ok", "problems", "counts")}, indent=1))
    for c in r["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"], c["examples"] if not c["ok"] else "")
