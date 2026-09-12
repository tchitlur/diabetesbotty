"""Backend route audit: hit every route, log 4xx/5xx and any field that is
null, NaN, an empty list/dict, or an obvious placeholder. Writes audit/api-log.json."""
from __future__ import annotations

import json
import math
import sys
import urllib.request
import urllib.error
from pathlib import Path

B = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent / "api-log.json"
PLACEHOLDERS = {"", "todo", "tbd", "lorem", "placeholder", "n/a", "…", "..."}
# empty by design: no escalations yet, no alerts when the forecast is in range, and a card the safety
# gate refused (request_data) carries no simulation output
ALLOW_EMPTY = {"escalation_history", "escalations", "raw_items", "data_missing", "gate.checks", "modified_events", "notes", "checked",
               "week_summary.events_removed", "week_summary.events_added", "plan_events", "long_term_delta", "factors", "variants"}
ALLOW_EMPTY_ROOT = {"GET /alerts", "GET /escalations"}


def call(method: str, path: str, body=None):
    req = urllib.request.Request(B + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:300]}


def walk(x, path, found, depth=0):
    if isinstance(x, dict):
        if not x and path.split(".")[-1] not in ALLOW_EMPTY:
            found.append(f"{path}: empty object")
        for k, v in x.items():
            walk(v, f"{path}.{k}" if path else k, found, depth + 1)
    elif isinstance(x, list):
        if not x and not any(path.endswith(a) for a in ALLOW_EMPTY) and path != "":
            found.append(f"{path}: empty array")
        for i, v in enumerate(x[:3] if len(x) > 50 else x):
            walk(v, f"{path}[{i}]", found, depth + 1)
        if len(x) > 50:
            nulls = sum(1 for v in x if v is None)
            nans = sum(1 for v in x if isinstance(v, float) and math.isnan(v))
            if nans:
                found.append(f"{path}: {nans} NaN values")
            if nulls and not path.endswith(("actual", "glucose")):   # CGM gaps are real data, drawn as gaps
                found.append(f"{path}: {nulls} null values")
    elif x is None:
        leaf = path.split(".")[-1].split("[")[0]
        if leaf not in ("insulin_kind", "exercise_kind", "cause_event", "since", "proposed", "best_variant", "mini_curve", "snack_time", "drink_cutoff", "workout_start", "sleep_hours", "mean_glucose", "overnight_min", "suggested", "portion", "last_error", "stale", "overnight_min_actual", "glucose", "actual"):
            found.append(f"{path}: null")
    elif isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        found.append(f"{path}: {x}")
    elif isinstance(x, str) and x.strip().lower() in PLACEHOLDERS and not path.endswith(("condition", "variant_name", "label", "notes", "last_error", "explanation", "instruction", "reason", "what", "rule")):
        found.append(f"{path}: placeholder string {x!r}")


def main() -> None:
    call("POST", "/demo/reset", {})
    beers = {"type": "alcohol", "start_time": "2025-08-29T19:00", "duration_min": 90, "alcohol_g": 28, "carbs_g": 26, "uncertainty": 0.25, "source": "local", "label": "2 beers"}
    routes = [
        ("GET", "/health", None), ("GET", "/state", None), ("GET", "/state?stale=30", None), ("GET", "/forecast", None), ("GET", "/history?hours=6", None),
        ("POST", "/parse", {"text": "can I have two more beers tonight?"}), ("POST", "/parse", {"text": "fasted run tomorrow at 7 for 30 min"}),
        ("POST", "/parse", {"text": "large coffee now"}), ("POST", "/parse", {"text": "asdf qwerty"}), ("GET", "/parser/status", None),
        ("POST", "/permission", {"event": beers}), ("POST", "/permission?stale=30", {"event": beers}),
        ("POST", "/permission", {"event": {**beers, "start_time": "now", "type": "exercise", "exercise_kind": "aerobic", "duration_min": 30, "alcohol_g": 0, "carbs_g": 0, "label": "run"}}),
        ("POST", "/events/accept", {"events": [beers]}), ("GET", "/events/planned", None), ("GET", "/events/recent", None),
        ("GET", "/plan?date=tomorrow", None), ("GET", "/plan?date=tomorrow&drinks=3", None), ("POST", "/plan", {"date": "tomorrow", "drinks": 0}),
        ("POST", "/change", {"name": "morning_workouts"}), ("POST", "/change", {"name": "cut_caffeine"}), ("POST", "/change", {"name": "drink_fridays_only"}),
        ("POST", "/change", {"name": "fasting_16_8"}), ("POST", "/change", {"name": "no_change"}), ("POST", "/change", {"name": "bogus"}), ("GET", "/change/options", None),
        ("GET", "/budget", None), ("GET", "/alerts", None), ("GET", "/replay/days", None), ("GET", "/replay/suggest", None),
        ("POST", "/replay", {"date": "2025-08-09"}), ("POST", "/replay", {"date": "2025-08-09", "alcohol_scale": 0.0}), ("POST", "/replay", {"date": "2025-08-29"}),
        ("GET", "/drift", None), ("GET", "/clinician", None), ("GET", "/cards", None), ("GET", "/why", None), ("GET", "/escalations", None), ("GET", "/trends", None),
    ]
    log = []
    for method, path, body in routes:
        status, data = call(method, path, body)
        found: list = []
        expect_error = (path == "/change" and body and body.get("name") == "bogus") or (path == "/replay" and body and body.get("date") == "2025-08-29")
        if status >= 400 and not expect_error:
            found.append(f"HTTP {status}: {str(data)[:200]}")
        elif status < 400 and expect_error:
            found.append(f"expected an error but got {status}")
        elif status < 400:
            walk(data, "", found)
        log.append({"route": f"{method} {path}", "body": body, "status": status, "findings": found})
        print(f"{status} {method} {path}" + (f"  -> {len(found)} finding(s)" if found else ""))
        for f in found:
            print("     ", f)
    OUT.write_text(json.dumps(log, indent=1), encoding="utf-8")
    n = sum(len(r["findings"]) for r in log)
    print(f"\n{n} finding(s) across {len(log)} calls -> {OUT}")


if __name__ == "__main__":
    main()
