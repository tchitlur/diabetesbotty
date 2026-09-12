"""Replay: take a past day, apply slider modifications to its events, and
return the actual CGM curve alongside the twin's simulation of the original
and the modified day.

The day is simulated in two segments anchored on UKF-filtered hidden states
(06:00 and 18:00) so the twin starts each segment where the patient really
was; the counterfactual (sliders) then diverges from that anchor. Runs from
06:00 through 08:00 the next morning so overnight lows are visible."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from backend.schema.events import Event
from backend.schema.state import State
from backend.schema.api import ReplayResponse, EventModel
from backend.engine import fast
from backend.engine.simulate import simulate, state_params
from backend.inference.estimator import run_ukf
from backend.inference.windows import twin_daily_states

DT = 5
ANCHORS = (6, 18)     # hours; each segment starts from the UKF state at the anchor
END_HOUR_NEXT_DAY = 8


def list_days(twin) -> List[Dict[str, object]]:
    """Past days available for replay, flagged with what happened."""
    start = twin.pt.cgm.times[0].to_pydatetime().date() + timedelta(days=1)
    end = (twin.now - timedelta(days=1)).date()
    by_day: Dict[str, Dict[str, object]] = {}
    for e in twin.pt.events:
        d = e.start.date().isoformat()
        row = by_day.setdefault(d, {"date": d, "alcohol_g": 0.0, "exercise_min": 0.0, "carbs_g": 0.0})
        row["alcohol_g"] += e.alcohol_g
        row["carbs_g"] += e.carbs_g
        if e.type == "exercise":
            row["exercise_min"] += max(e.duration_min, 30)
    # actual overnight minimum (22:00 -> 08:00 next day) from the CGM, so the UI can flag nights with a low
    t = twin.pt.cgm.times
    g = np.where(twin.pt.cgm.valid, twin.pt.cgm.glucose, np.nan)
    out = []
    d = start
    while d <= end:
        k = d.isoformat()
        row = by_day.get(k, {"date": k, "alcohol_g": 0.0, "exercise_min": 0.0, "carbs_g": 0.0})
        row["weekday"] = d.strftime("%a")
        row["drinks"] = round(row["alcohol_g"] / 14.0)
        a = t.searchsorted(pd.Timestamp(datetime(d.year, d.month, d.day, 22)))
        b = t.searchsorted(pd.Timestamp(datetime(d.year, d.month, d.day) + timedelta(days=1, hours=8)))
        seg = g[a:b]
        row["overnight_min"] = round(float(np.nanmin(seg)), 0) if len(seg) and not np.all(np.isnan(seg)) else None
        row["overnight_low"] = bool(row["overnight_min"] is not None and row["overnight_min"] < 70)
        out.append(row)
        d += timedelta(days=1)
    return out


def modify_events(events: List[Event], carbs_scale: float = 1.0, alcohol_scale: float = 1.0, exercise_scale: float = 1.0,
                  insulin_scale: float = 1.0) -> List[Event]:
    out = []
    for e in events:
        if e.type == "meal":
            e = e.copy(carbs_g=e.carbs_g * carbs_scale)
        elif e.type == "alcohol":
            if alcohol_scale <= 0:
                continue
            e = e.copy(alcohol_g=e.alcohol_g * alcohol_scale, carbs_g=e.carbs_g * alcohol_scale)
        elif e.type == "exercise":
            if exercise_scale <= 0:
                continue
            e = e.copy(duration_min=max(e.duration_min, 30) * exercise_scale)
        elif e.type == "insulin" and e.insulin_kind == "bolus":
            e = e.copy(insulin_units=e.insulin_units * insulin_scale)
        out.append(e)
    return out


def _segment(twin, t0: datetime, t1: datetime, hidden: np.ndarray, base_state: State, events: List[Event]) -> np.ndarray:
    horizon = int((t1 - t0).total_seconds() // 60)
    s0 = base_state.copy()
    s0.glucose = float(fast.glucose_mgdl(hidden[None, :], twin.params)[0])
    s0.plasma_insulin = float(hidden[fast.IDX["I"]])
    tr = simulate(s0, events, twin.params, horizon, t0=t0, hidden=hidden)
    return tr.series["glucose"]


def replay_day(twin, date: str, carbs_scale: float = 1.0, alcohol_scale: float = 1.0, exercise_scale: float = 1.0,
               insulin_scale: float = 1.0) -> ReplayResponse:
    day = datetime.fromisoformat(date).replace(hour=0, minute=0)
    if day >= twin.now.replace(hour=0, minute=0):
        raise ValueError("replay needs a past day")
    end = day + timedelta(days=1, hours=END_HOUR_NEXT_DAY)
    events = [e for e in twin.pt.events if day - timedelta(hours=14) <= e.start < end]
    day_events = [e for e in events if day <= e.start < day + timedelta(days=1)]
    modified = modify_events(events, carbs_scale, alcohol_scale, exercise_scale, insulin_scale)
    ms = twin_daily_states(twin.pt).get((day - timedelta(days=1)).date().isoformat()) or State()
    # anchors: UKF states at 06:00 and 18:00 (each filtered over the preceding 6 h of the real day)
    anchors = [day.replace(hour=h) for h in ANCHORS]
    bounds = anchors + [end]
    g_orig, g_mod, times = [], [], []
    for i, t0 in enumerate(anchors):
        u = run_ukf(twin.pt, twin.params, hours=6.0, end=t0)
        x = u.mean
        t1 = bounds[i + 1]
        seg_o = _segment(twin, t0, t1, x, ms, [e for e in events if e.start < t1])
        seg_m = _segment(twin, t0, t1, x, ms, [e for e in modified if e.start < t1])
        n = len(seg_o) if i == len(anchors) - 1 else len(seg_o) - 1
        g_orig.extend(seg_o[:n])
        g_mod.extend(seg_m[:n])
        times.extend((t0 + timedelta(minutes=DT * k)).isoformat(timespec="minutes") for k in range(n))
    g0 = np.array(g_orig)
    g1 = np.array(g_mod)
    grid = pd.DatetimeIndex([pd.Timestamp(x) for x in times])
    idx = twin.pt.cgm.times.searchsorted(grid)
    actual = np.full(len(grid), np.nan)
    for i, j in enumerate(idx):
        if j < len(twin.pt.cgm.times) and abs((twin.pt.cgm.times[j] - grid[i]).total_seconds()) < 150 and twin.pt.cgm.valid[j]:
            actual[i] = twin.pt.cgm.glucose[j]
    return ReplayResponse(
        date=date, times=times, actual=[None if np.isnan(x) else round(float(x), 1) for x in actual],
        simulated=[round(float(x), 1) for x in g1], simulated_original=[round(float(x), 1) for x in g0],
        events=[EventModel(**e.to_dict()) for e in day_events if e.type != "water"],
        modified_events=[EventModel(**e.to_dict()) for e in modified if day <= e.start < day + timedelta(days=1) and e.type != "water"],
        min_glucose_original=round(float(g0.min()), 1), min_glucose_modified=round(float(g1.min()), 1),
        hypo_minutes_original=round(float(np.sum(g0 < 70) * DT), 0), hypo_minutes_modified=round(float(np.sum(g1 < 70) * DT), 0))


def suggest_day(twin, max_checks: int = 8) -> Dict[str, object]:
    """Most recent drink night where the twin's alcohol-free counterfactual
    lifts the overnight low (min < 72 as logged, > +15 mg/dL without alcohol).
    Cached on the twin; a handful of 2-segment replays (~1 s each)."""
    cached = getattr(twin, "_replay_suggest", None)
    if cached is not None:
        return cached
    days = [d for d in list_days(twin) if d["drinks"] > 0][::-1]
    best = None
    checked = []
    for d in days[:max_checks]:
        r1 = replay_day(twin, d["date"])
        r0 = replay_day(twin, d["date"], alcohol_scale=0.0)
        night = [i for i, t in enumerate(r1.times) if t >= d["date"] + "T22:00"]
        o = min(r1.simulated_original[i] for i in night)
        m = min(r0.simulated[i] for i in night)
        checked.append({"date": d["date"], "overnight_min_as_logged": round(o, 1), "overnight_min_no_alcohol": round(m, 1)})
        if o < 72 and m > o + 15:
            best = {"date": d["date"], "weekday": d["weekday"], "drinks": d["drinks"], "overnight_min_as_logged": round(o, 1), "overnight_min_no_alcohol": round(m, 1)}
            break
    out = {"suggested": best, "checked": checked}
    twin._replay_suggest = out  # type: ignore[attr-defined]
    return out
