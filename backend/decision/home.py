"""Home and Plan views in plain language.

* tiles(): the "right now" pictographic tiles (value, fill level, status word,
  3-hour forecast of that one quantity), ordered so that whatever is furthest
  from normal or changing fastest comes first.
* coming_up(): next meal, next workout, next risk, best window.
* scan_starts(): batched "what if I did X at each of these times" pass through
  the deterministic engine; gives the safe / caution / avoid bands.
* timeline(): the Plan tab: now until bedtime (extended through tomorrow when
  fewer than 6 h remain), 30-minute bands, predicted meals, planned workouts.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.schema.events import Event
from backend.engine import fast
from backend.engine.fast import IDX
from backend.engine.simulate import events_to_inputs, state_params
from backend.decision.planner import typical_day_events
from backend.decision.alerts import compute_alerts
from backend.decision.plain import likelihood

DT = 5
TILE_ORDER = ["carbs", "liver", "ketones", "energy", "recovery", "insulin", "alcohol", "caffeine"]


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="minutes")


def _hhmm(d: datetime) -> str:
    return d.strftime("%H:%M")


def _day_word(d: datetime, now: datetime) -> str:
    n = (d.date() - now.date()).days
    return "today" if n == 0 else "tomorrow" if n == 1 else d.strftime("%A")


# ------------------------------------------------------------------ glucose hero

def trend(twin) -> Dict[str, Any]:
    """Direction from the last 20 minutes of valid CGM: rising / steady / falling (Dexcom-style 1 mg/dL/min)."""
    t = twin.pt.cgm.times
    m = (t > pd.Timestamp(twin.now - timedelta(minutes=21))) & (t <= pd.Timestamp(twin.now)) & twin.pt.cgm.valid
    g = twin.pt.cgm.glucose[m]
    if len(g) < 2:
        return {"word": "steady", "arrow": "→", "slope_mgdl_per_min": 0.0}
    x = np.arange(len(g)) * 5.0
    slope = float(np.polyfit(x, g, 1)[0])
    word = "rising" if slope >= 1.0 else "falling" if slope <= -1.0 else "steady"
    arrow = {"rising": "↑", "falling": "↓", "steady": "→"}[word]
    return {"word": word, "arrow": arrow, "slope_mgdl_per_min": round(slope, 2)}


def history(twin, hours: float = 3.0, max_gap_min: int = 20) -> Dict[str, Any]:
    """The display series for the chart: one array on the 5-minute grid from now-hours to now.
    `raw` keeps the sensor's dropouts and flagged points as nulls; `display` fills gaps up to
    `max_gap_min` by linear interpolation (display only). Longer gaps stay null and are listed."""
    t = twin.pt.cgm.times
    m = (t > pd.Timestamp(twin.now - timedelta(hours=hours))) & (t <= pd.Timestamp(twin.now))
    g, v = twin.pt.cgm.glucose[m], twin.pt.cgm.valid[m]
    raw = np.where(v & ~np.isnan(g), g, np.nan).astype(float)
    disp = raw.copy()
    n = len(raw)
    i = 0
    gaps = []
    while i < n:
        if np.isnan(disp[i]):
            j = i
            while j < n and np.isnan(disp[j]):
                j += 1
            length = (j - i) * 5
            if i > 0 and j < n and length <= max_gap_min:
                disp[i:j] = np.linspace(disp[i - 1], disp[j], j - i + 2)[1:-1]
            elif i > 0 and j == n and length <= max_gap_min:
                disp[i:j] = disp[i - 1]           # trailing short gap: hold the last reading up to now
            else:
                gaps.append({"start": t[m][i].isoformat(timespec="minutes"), "end": (t[m][j - 1] if j - 1 < n else t[m][-1]).isoformat(timespec="minutes"), "minutes": length})
            i = j
        else:
            i += 1
    return {"times": [x.isoformat(timespec="minutes") for x in t[m]],
            "raw": [None if np.isnan(x) else round(float(x), 1) for x in raw],
            "display": [None if np.isnan(x) else round(float(x), 1) for x in disp],
            "gaps": gaps}


# ------------------------------------------------------------------ tiles

def _status(v: float, cuts: List[Tuple[float, str, str]], last: Tuple[str, str]) -> Tuple[str, str]:
    for lim, word, tone in cuts:
        if v < lim:
            return word, tone
    return last


def recovery_score(load: float, debt: float) -> float:
    """0-100: 100 when rested with a normal training load; sleep debt and a heavy load pull it down."""
    return float(np.clip(100.0 - 10.0 * debt - 1.5 * max(load - 12.0, 0.0), 0.0, 100.0))


def tiles(twin) -> List[Dict[str, Any]]:
    """The "right now" tiles. Every tile has the same four rows: label, value + unit, fill level,
    status word. Hydration and body composition are computed elsewhere but not shown here."""
    s, _ = twin.state_now()
    tr = twin.deterministic(horizon_min=180)
    times = tr.times()
    ser = {k: np.asarray(v, dtype=float) for k, v in tr.series.items()}
    p = twin.params
    recent = twin.events_recent(12.0)
    alcohol_recent = any(e.type == "alcohol" for e in recent) or s.blood_alcohol > 0.005
    caffeine_recent = any(e.type == "caffeine" and e.start >= twin.now - timedelta(hours=8) for e in recent) or s.caffeine > 10

    def fc(arr: np.ndarray, digits: int = 1):
        return {"times": times, "values": [round(float(x), digits) for x in arr]}

    def rate(arr: np.ndarray, scale: float) -> float:
        k = min(12, len(arr) - 1)
        return abs(float(arr[k] - arr[0])) / max(scale, 1e-9)

    def tile(key, icon, label, value, unit, level, status, tone, forecast, note, score):
        return {"key": key, "icon": icon, "label": label, "value": value, "unit": unit, "value_text": f"{value} {unit}".strip(),
                "level": round(float(np.clip(level, 0, 1)), 3), "status": status, "tone": tone, "forecast": forecast, "note": note, "score": round(float(score), 3)}

    out: List[Dict[str, Any]] = []
    carbs = ser["gut_carbs_1"] + ser["gut_carbs_2"]
    v = float(carbs[0])
    word, tone = _status(v, [(3, "none left", "good"), (15, "a little", "good"), (40, "some", "good")], ("a lot", "warn"))
    out.append(tile("carbs", "🍞", "Carbs digesting", round(v), "g", v / 60.0, word, tone, fc(carbs, 0),
                    "Carbs from recent food still being absorbed. They push glucose up over the next hour or two.",
                    max(min(v / 60.0, 1.0) * 0.8, rate(carbs, 60.0) * 2)))
    lmax = float(p.get("liver_L_max", 120.0))
    v = float(ser["liver_glycogen"][0])
    lvl = v / lmax
    word, tone = _status(lvl, [(0.3, "running low", "bad"), (0.6, "half full", "warn")], ("well stocked", "good"))
    out.append(tile("liver", "🫀", "Liver stores", round(v), "g", lvl, word, tone, fc(ser["liver_glycogen"], 0),
                    f"Sugar your liver keeps in reserve (up to about {lmax:.0f} g). It releases it between meals and overnight; alcohol and long gaps run it down.",
                    max(max(0.0, 0.6 - lvl) * 2, rate(ser["liver_glycogen"], lmax) * 2)))
    v = float(ser["ketones"][0])
    word, tone = _status(v, [(0.6, "normal", "good"), (1.5, "raised", "warn")], ("high", "bad"))
    out.append(tile("ketones", "🧪", "Ketones", round(v, 1), "mmol/L", v / 1.5, word, tone, fc(ser["ketones"], 2),
                    "Made when the body burns fat instead of sugar. Above 0.6 with high glucose means you need more insulin.",
                    max(min(v / 1.5, 1.0), rate(ser["ketones"], 1.5) * 2)))
    v = float(ser["energy_score"][0])
    word, tone = _status(v, [(45, "low", "bad"), (70, "okay", "warn")], ("good", "good"))
    out.append(tile("energy", "⚡", "Energy", round(v), "/ 100", v / 100.0, word, tone, fc(ser["energy_score"], 0),
                    "How ready you are right now: steady glucose, enough sleep, not too much caffeine, well hydrated.",
                    max(max(0.0, 0.7 - v / 100.0) * 1.5, rate(ser["energy_score"], 100.0) * 2)))
    load, debt = float(s.training_load), float(s.sleep_debt)
    rec = recovery_score(load, debt)
    word, tone = ("recovered", "good") if rec >= 70 else ("tired", "warn") if rec >= 45 else ("run down", "bad")
    out.append(tile("recovery", "🛌", "Recovery", round(rec), "/ 100", rec / 100.0, word, tone,
                    {"times": times, "values": [round(rec)] * len(times)},
                    f"Sleep pays back what training takes out. Sleep debt {debt:.1f} h, training load {load:.0f}.",
                    max(0.0, 0.7 - rec / 100.0) * 1.5))
    v = float(s.insulin_sensitivity) * (1 - p.get("sleep_debt_coef", 0.2) * min(debt, 3.0) / 2.5)
    word, tone = ("less than usual", "warn") if v < 0.9 else ("better than usual", "good") if v > 1.1 else ("as usual", "good")
    out.append(tile("insulin", "💉", "Insulin working", round(100 * v), "% of usual", (v - 0.6) / 0.8, word, tone,
                    {"times": times, "values": [round(100 * v)] * len(times)},
                    "Compared with your normal. Short sleep, a hard week and illness make insulin work less well; exercise makes it work better.",
                    abs(v - 1.0) * 3))
    if alcohol_recent:
        v = float(ser["blood_alcohol"][0])
        word, tone = _status(v, [(0.01, "almost gone", "good"), (0.05, "clearing", "warn")], ("in your blood", "bad"))
        gone = next((times[i] for i, x in enumerate(ser["blood_alcohol"]) if x < 0.005), None)
        out.append(tile("alcohol", "🍺", "Alcohol", round(v, 3), "% BAC", v / 0.10, word, tone, fc(ser["blood_alcohol"], 3),
                        "While your liver clears alcohol it releases less sugar, so a low can come hours later, often overnight." + (f" Gone by about {gone[11:16]}." if gone else ""),
                        min(v / 0.10, 1.0) * 2 + 0.3))
    if caffeine_recent:
        v = float(ser["caffeine"][0])
        word, tone = _status(v, [(25, "almost gone", "good"), (100, "some left", "good")], ("plenty left", "warn"))
        out.append(tile("caffeine", "☕", "Caffeine", round(v), "mg", v / 200.0, word, tone, fc(ser["caffeine"], 0),
                        "Caffeine halves about every 5 hours. It makes insulin work a little less well and can spoil sleep.",
                        min(v / 200.0, 1.0) + 0.2))
    hot = sorted([t for t in out if t["score"] >= 0.35], key=lambda t: -t["score"])
    rest = sorted([t for t in out if t["score"] < 0.35], key=lambda t: TILE_ORDER.index(t["key"]))
    return hot + rest


# ------------------------------------------------------------------ batched "what if at each time" scan

TEMPLATES = {
    "exercise": Event(type="exercise", start_time="2025-01-01T00:00", duration_min=30, exercise_kind="aerobic", intensity=0.6, uncertainty=0.15, source="tap", label="30 min workout"),
    "caffeine": Event(type="caffeine", start_time="2025-01-01T00:00", caffeine_mg=95, uncertainty=0.15, source="tap", label="coffee"),
    "alcohol": Event(type="alcohol", start_time="2025-01-01T00:00", duration_min=90, alcohol_g=28, carbs_g=26, uncertainty=0.25, source="tap", label="2 drinks"),
}
AFTER_MIN = {"exercise": 240, "caffeine": 240, "alcohol": 8 * 60}


def routine_future(twin, days: int = 2) -> List[Event]:
    """The person's usual meals (and boluses) after now, today and tomorrow, as predicted events."""
    out: List[Event] = []
    for d in range(days):
        day = (twin.now + timedelta(days=d)).replace(hour=0, minute=0)
        for e in typical_day_events(twin, day):
            if e.type in ("meal", "insulin") and e.start > twin.now + timedelta(minutes=10):
                out.append(e)
    return out


def scan_starts(twin, kind: str, starts: List[datetime], ctx: List[Event], per_start_ctx: Optional[List[List[Event]]] = None) -> List[Dict[str, Any]]:
    """For each candidate start time, put the template event there on top of the
    context and integrate every candidate in one batch. Returns colour + reason per start."""
    if not starts:
        return []
    tmpl = TEMPLATES[kind]
    after = AFTER_MIN[kind]
    dur = max(tmpl.duration_min, 30.0)
    p = state_params(twin.medium_state(), twin.params)
    basal_i = float(fast.steady_basal_insulin(p, 120.0)) if hasattr(fast, "steady_basal_insulin") else 6.0
    last = max(starts) + timedelta(minutes=dur + after)
    horizon = int((last - twin.now).total_seconds() // 60) + DT
    n_steps = max(horizon // DT, 2)
    cands = [tmpl.copy(start_time=_iso(st)) for st in starts]
    sets = []
    for i, c in enumerate(cands):
        base = per_start_ctx[i] if per_start_ctx is not None else ctx
        sets.append(sorted(base + [c], key=lambda e: e.start))
    inputs = np.stack([events_to_inputs(evs, twin.now, n_steps, DT, p) for evs in sets], axis=1)
    x0 = np.repeat(twin.hidden_now()[None, :], len(cands), axis=0)
    X = fast.integrate(x0, inputs, p, DT, substeps=2)
    G = fast.glucose_mgdl(X, p)   # (T+1, B)
    I = X[:, :, IDX["I"]]
    BAC = X[:, :, IDX["BAC"]]
    out = []
    for i, st in enumerate(starts):
        a = int((st - twin.now).total_seconds() // 60) // DT
        b = min(a + int((dur + after) // DT), G.shape[0] - 1)
        seg = G[a:b + 1, i]
        k = int(np.argmin(seg))
        t_min = st + timedelta(minutes=k * DT)
        g0, i0, bac0, gmin = float(G[a, i]), float(I[a, i]), float(BAC[a, i]), float(seg.min())
        color, reason = "green", ""
        if kind == "exercise" and g0 < 90:
            color, reason = "red", f"your glucose would be too low to start (about {g0:.0f} mg/dL)"
        elif gmin < 70:
            color, reason = "red", f"you'd likely go low around {_hhmm(t_min)}"
        elif kind == "exercise" and g0 > 250:
            color, reason = "amber", f"your glucose would be high (about {g0:.0f} mg/dL); check ketones first"
        elif gmin < 85:
            color, reason = "amber", f"you'd get close to low around {_hhmm(t_min)}"
        elif i0 > 1.8 * basal_i:
            bol = [e for e in ctx if e.type == "insulin" and e.insulin_kind == "bolus" and e.start <= st]
            src = (bol[-1].label or "your last dose").replace("bolus for ", "insulin from ") if bol else "insulin from your last dose"
            color, reason = "amber", f"{src} still active"
        elif bac0 > 0.02:
            color, reason = "amber", "alcohol still in your system"
        out.append({"start": _iso(st), "color": color, "reason": reason, "min_glucose": round(gmin), "glucose_at_start": round(g0)})
    return out


def _runs(rows: List[Dict[str, Any]], color: str = "green") -> List[Tuple[str, str, float]]:
    """Contiguous runs of a colour: (start, end, mean min glucose)."""
    runs, cur = [], []
    for r in rows + [None]:
        if r is not None and r["color"] == color:
            cur.append(r)
        elif cur:
            s = datetime.fromisoformat(cur[0]["start"])
            e = datetime.fromisoformat(cur[-1]["start"]) + timedelta(minutes=30)
            runs.append((_iso(s), _iso(e), float(np.mean([c["min_glucose"] for c in cur]))))
            cur = []
    return runs


def _slots(twin, a: datetime, b: datetime, step_min: int = 30) -> List[datetime]:
    t = a.replace(minute=(a.minute // step_min) * step_min) + timedelta(minutes=step_min)
    out = []
    while t <= b:
        out.append(t)
        t += timedelta(minutes=step_min)
    return out


# ------------------------------------------------------------------ coming up

def _fmt_window(a: str, b: str, now: datetime) -> str:
    da, db = datetime.fromisoformat(a), datetime.fromisoformat(b)
    day = _day_word(da, now)
    return f"{_hhmm(da)}–{_hhmm(db)}" + ("" if day == "today" else f" {day}")


def coming_up(twin, mc) -> List[Dict[str, Any]]:
    now = twin.now
    routine = routine_future(twin)
    ctx = twin.context_events() + routine
    cards: List[Dict[str, Any]] = []

    # --- next meal
    med = np.asarray(mc.median)
    low_i = next((i for i, g in enumerate(med) if g < 80), None)
    meals = [e for e in routine if e.type == "meal"]
    if low_i is not None and low_i <= 8 * 12:
        t_low = now + timedelta(minutes=5 * low_i)
        t_eat = max(now + timedelta(minutes=15), t_low - timedelta(minutes=45))
        cards.append({"key": "meal", "icon": "🍽", "title": "Next meal", "time": _iso(t_eat),
                      "text": f"Eat something by {_hhmm(t_eat)}: you'll be low by {_hhmm(t_low)} without food."})
    elif meals:
        m = meals[0]
        name = (m.label or "meal").replace("usual ", "")
        cards.append({"key": "meal", "icon": "🍽", "title": "Next meal", "time": m.start_time,
                      "text": f"Usual {name} around {_hhmm(m.start)} {_day_word(m.start, now)}. No low expected before then."})
    else:
        cards.append({"key": "meal", "icon": "🍽", "title": "Next meal", "time": None, "text": "No meal needed soon; your glucose should hold."})

    # --- next workout: a planned one, else the best window in what is left of today (or tomorrow morning)
    planned = [e for e in twin.future_events() if e.type == "exercise"]
    today_end = now.replace(hour=21, minute=30)
    starts = _slots(twin, now, today_end) if now < today_end else []
    scan_today = scan_starts(twin, "exercise", starts, ctx)
    greens = _runs(scan_today, "green")
    if planned:
        e = planned[0]
        cards.append({"key": "workout", "icon": "🏃", "title": "Next workout", "time": e.start_time,
                      "text": f"Planned: {e.label or 'workout'} at {_hhmm(e.start)} {_day_word(e.start, now)}."})
    elif greens:
        a, b, _ = max(greens, key=lambda r: r[2])
        cards.append({"key": "workout", "icon": "🏃", "title": "Next workout", "time": a,
                      "text": f"Best time to exercise: {_fmt_window(a, b, now)}."})
    else:
        tom = (now + timedelta(days=1)).replace(hour=6, minute=0)
        scan_tom = scan_starts(twin, "exercise", _slots(twin, tom - timedelta(minutes=30), tom.replace(hour=20)), ctx)
        g2 = _runs(scan_tom, "green")
        if g2:
            a, b, _ = max(g2, key=lambda r: r[2])
            cards.append({"key": "workout", "icon": "🏃", "title": "Next workout", "time": a,
                          "text": f"No good time left today. Best time to exercise: {_fmt_window(a, b, now)}."})
        else:
            cards.append({"key": "workout", "icon": "🏃", "title": "Next workout", "time": None,
                          "text": "No safe window found without a snack first; ask in the chat before you go."})

    # --- risk: next predicted high or low
    alerts = twin.cached("alerts", lambda: compute_alerts(twin))
    if alerts:
        a = alerts[0]
        kind = {"hypo": "low", "hyper": "high", "dka": "ketone problem"}[a.kind]
        cards.append({"key": "risk", "icon": "⚠️", "title": "Risk", "time": a.window_start, "tone": "bad" if a.kind != "hyper" else "warn",
                      "text": f"A {kind} is {likelihood(a.probability)} between {_hhmm(datetime.fromisoformat(a.window_start))} and {_hhmm(datetime.fromisoformat(a.window_end))}."
                              + (f" Most likely because of {(a.cause_event.label or a.cause_event.type).replace('bolus for', 'the insulin for')} at {a.cause_event.start_time[11:16]}." if a.cause_event else "")})
    else:
        cards.append({"key": "risk", "icon": "✅", "title": "Risk", "time": None, "tone": "good", "text": "No risks in the next 8 hours."})

    # --- best window for what the person does most (exercise by default)
    cnt = Counter(e.type for e in twin.pt.events if e.type in ("exercise", "caffeine", "alcohol") and e.start >= now - timedelta(days=14))
    kind = cnt.most_common(1)[0][0] if cnt else "exercise"
    kind_word = {"exercise": "exercise", "caffeine": "coffee", "alcohol": "a drink"}[kind]
    tom = (now + timedelta(days=1)).replace(hour=6, minute=0)
    end = now.replace(hour=22, minute=0) if kind != "caffeine" else now.replace(hour=15, minute=0)
    starts = _slots(twin, now, end) if now < end else []
    if len(starts) < 3:
        starts += _slots(twin, tom - timedelta(minutes=30), tom.replace(hour=15 if kind == "caffeine" else 21))
    scan = scan_starts(twin, kind, starts, ctx)
    g = _runs(scan, "green")
    if g:
        a, b, _ = max(g, key=lambda r: r[2])
        cards.append({"key": "best", "icon": {"exercise": "🏃", "caffeine": "☕", "alcohol": "🍷"}[kind], "title": "Best window", "time": a,
                      "text": f"Best time for {kind_word}: {_fmt_window(a, b, now)}."})
    else:
        cards.append({"key": "best", "icon": "🕒", "title": "Best window", "time": None,
                      "text": f"No clearly safe window for {kind_word} in the next day; ask in the chat before you do."})
    return cards


# ------------------------------------------------------------------ plan timeline

def bedtime(twin) -> datetime:
    sleeps = [e for e in twin.pt.events if e.type == "sleep" and e.start >= twin.now - timedelta(days=14)]
    if sleeps:
        mins = sorted(((e.start.hour * 60 + e.start.minute + 720) % 1440) for e in sleeps)   # shift so ~midnight sorts sanely
        med = mins[len(mins) // 2]
        h, m = divmod((med - 720) % 1440, 60)
    else:
        h, m = 23, 0
    bt = twin.now.replace(hour=int(h), minute=int(m // 5 * 5))
    if bt <= twin.now:
        bt += timedelta(days=1)
    return bt


def wake_time(twin) -> datetime:
    """This morning's wake-up: the last logged sleep that started before today's noon, plus its hours; else 07:00."""
    now = twin.now
    noon = now.replace(hour=12, minute=0)
    sleeps = [e for e in twin.pt.events if e.type == "sleep" and e.start < noon and e.start >= now - timedelta(hours=30)]
    if sleeps:
        e = sleeps[-1]
        w = e.start + timedelta(hours=float(e.sleep_hours or 7.5))
        if now.replace(hour=3, minute=0) <= w <= noon:
            return w.replace(minute=(w.minute // 5) * 5)
    return now.replace(hour=7, minute=0)


def _band_color_glucose(seg: np.ndarray) -> Tuple[str, str]:
    lo, hi = float(np.nanmin(seg)), float(np.nanmax(seg))
    if lo < 70:
        return "red", "a low here"
    if hi > 250:
        return "red", "well above range here"
    if lo < 85:
        return "amber", "close to a low here"
    if hi > 180:
        return "amber", "above range here"
    return "green", "in range"


def _kind(e: Event) -> Optional[str]:
    if e.type == "meal":
        return "snack" if e.carbs_g < 25 else "meal"
    if e.type == "insulin":
        return None if e.insulin_kind == "basal" else "insulin"
    return {"exercise": "workout", "alcohol": "drink", "caffeine": "coffee"}.get(e.type)


def _label(e: Event) -> str:
    return (e.label or e.type).replace("bolus for ", "insulin for ")


def timeline(twin, workout: Optional[Dict[str, Any]] = None, snacks: Optional[List[str]] = None) -> Dict[str, Any]:
    """The Plan tab: today from wake time to bedtime on one horizontal axis. Past = what happened
    (logged events, sensor trace); future = what is predicted and suggested (bands, usual meals,
    the suggested workout and snacks)."""
    now = twin.now
    wake, bt = wake_time(twin), bedtime(twin)
    routine = [e for e in routine_future(twin) if e.start <= bt]
    accepted = [e for e in twin.future_events() if e.start <= bt]
    w_ev = None
    if workout and workout.get("start"):
        w_ev = Event(type="exercise", start_time=workout["start"], duration_min=float(workout.get("duration_min", 30)),
                     exercise_kind=workout.get("kind", "aerobic"), intensity=float(workout.get("intensity", 0.6)), uncertainty=0.15,
                     source="tap", label=workout.get("label") or "30 min workout")
    s_evs = [Event(type="meal", start_time=t, carbs_g=15, duration_min=5, uncertainty=0.1, source="tap", label="small snack") for t in (snacks or []) if t]
    suggestions = ([w_ev] if w_ev else []) + s_evs
    ctx_base = twin.context_events() + routine

    # ---- sparkline: sensor trace since wake (display series), then the predicted path to bedtime
    past = history(twin, hours=max((now - wake).total_seconds() / 3600.0, 0.5))
    fut = twin.deterministic(extra=accepted + suggestions, horizon_min=max(int((bt - now).total_seconds() // 60), 30))
    fut_times, fut_g = fut.times(), [round(float(x), 1) for x in fut.series["glucose"]]
    spark_t = past["times"] + fut_times[1:]
    spark_v = past["display"] + fut_g[1:]
    spark_kind = ["actual"] * len(past["times"]) + ["forecast"] * (len(fut_times) - 1)

    # ---- glucose band (30-min slots over the whole window)
    g_by_t = {t: v for t, v in zip(spark_t, spark_v)}
    slot = wake.replace(minute=(wake.minute // 30) * 30)
    glucose_band = []
    while slot < bt:
        seg = np.array([np.nan if g_by_t.get(_iso(slot + timedelta(minutes=k * 5))) is None else g_by_t.get(_iso(slot + timedelta(minutes=k * 5))) for k in range(7)], dtype=float)
        if np.all(np.isnan(seg)):
            color, reason = "none", "no sensor data"
        else:
            color, reason = _band_color_glucose(seg)
        glucose_band.append({"start": _iso(slot), "end": _iso(slot + timedelta(minutes=30)), "color": color, "reason": reason, "past": slot < now})
        slot += timedelta(minutes=30)

    # ---- exercise band (future slots only; each judged with everything else in place)
    starts = _slots(twin, now, bt - timedelta(minutes=30))
    per = []
    for st in starts:
        base = list(ctx_base) + list(accepted) + list(s_evs)
        if w_ev is not None and abs((st - w_ev.start).total_seconds()) >= 30 * 60:
            base.append(w_ev)
        per.append(base)
    scan = scan_starts(twin, "exercise", starts, ctx_base + accepted + suggestions, per_start_ctx=per) if starts else []
    exercise_band = [{"start": r["start"], "end": _iso(datetime.fromisoformat(r["start"]) + timedelta(minutes=30)), "color": r["color"], "reason": r["reason"] or "a good time to exercise"} for r in scan]

    # ---- items on the axis
    items: List[Dict[str, Any]] = [{"time": _iso(wake), "kind": "wake", "label": "woke up", "state": "logged", "reason": "when you got up"}]
    for e in twin.pt.events:
        if wake <= e.start <= now:
            k = _kind(e)
            if k:
                items.append({"time": e.start_time, "kind": k, "label": _label(e), "state": "logged", "reason": _label(e) + " (logged)"})
    for e in accepted:
        k = _kind(e)
        if k:
            items.append({"time": e.start_time, "kind": k, "label": _label(e), "state": "logged", "reason": _label(e) + " (added to your plan)"})
    for e in routine:
        if e.type == "meal" and e.start > now:
            items.append({"time": e.start_time, "kind": "meal", "label": _label(e), "state": "predicted", "reason": "your usual " + (e.label or "meal").replace("usual ", "") + " time"})
    for e in suggestions:
        items.append({"time": e.start_time, "kind": _kind(e), "label": e.label, "state": "suggested", "event": e.to_dict(),
                      "reason": "suggested workout: tap to accept, drag to move" if e.type == "exercise" else "suggested snack before the workout: tap to accept"})
    items.append({"time": _iso(bt), "kind": "sleep", "label": "bedtime", "state": "predicted", "reason": "your usual bedtime"})
    items.sort(key=lambda x: x["time"])

    # ---- headline
    mc = twin.cached("forecast:480", lambda: twin.forecast(horizon_min=480))
    med = np.asarray(mc.median)
    low_i = next((i for i, g in enumerate(med) if g < 80), None)
    parts = []
    if low_i is not None and now + timedelta(minutes=5 * low_i) <= bt + timedelta(hours=2):
        t_eat = max(now + timedelta(minutes=15), now + timedelta(minutes=5 * low_i) - timedelta(minutes=45))
        parts.append("eat by " + _hhmm(t_eat))
    else:
        nm = next((e for e in routine if e.type == "meal" and e.start > now), None)
        parts.append(("next meal around " + _hhmm(nm.start)) if nm else "no more meals needed today")
    greens = _runs(scan, "green") if scan else []
    planned_ex = next((e for e in accepted if e.type == "exercise"), None)
    if planned_ex is not None:
        parts.append("your workout at " + _hhmm(planned_ex.start))
    elif w_ev is not None:
        parts.append("suggested workout at " + _hhmm(w_ev.start) + (" after a small snack" if s_evs else ""))
    elif greens:
        a, b, _ = max(greens, key=lambda r: r[2])
        parts.append("best workout window " + _hhmm(datetime.fromisoformat(a)) + "–" + _hhmm(datetime.fromisoformat(b)))
    elif any(r["color"] == "amber" for r in scan):
        parts.append("a light workout with a snack first would be safest")
    else:
        parts.append("no good workout window left today")
    alerts = twin.cached("alerts", lambda: compute_alerts(twin))
    if alerts:
        a0 = alerts[0]
        what = "low" if a0.kind == "hypo" else "high" if a0.kind == "hyper" else "ketone problem"
        parts.append("watch for a " + what + " around " + a0.window_start[11:16])
    else:
        parts.append("no lows or highs expected before bed")
    headline = ", ".join(parts) + "."
    headline = headline[0].upper() + headline[1:]

    return {"start": _iso(wake), "end": _iso(bt), "now": _iso(now), "headline": headline,
            "sparkline": {"times": spark_t, "values": spark_v, "kind": spark_kind, "gaps": past["gaps"]},
            "glucose_band": glucose_band, "exercise_band": exercise_band, "items": items,
            "workout": ({"start": w_ev.start_time, "duration_min": w_ev.duration_min, "kind": w_ev.exercise_kind, "label": w_ev.label} if w_ev else None),
            "snacks": [e.start_time for e in s_evs]}


def auto_plan(twin) -> Dict[str, Any]:
    """'Suggest my day': place a workout in what is left of today and a snack before it when needed."""
    now = twin.now
    bt = bedtime(twin)
    if (bt - now) < timedelta(hours=1, minutes=30):
        return {"workout": None, "snacks": []}
    ctx = twin.context_events() + routine_future(twin)
    scan = scan_starts(twin, "exercise", _slots(twin, now, bt - timedelta(hours=1)), ctx)
    greens = [r for r in scan if r["color"] == "green"]
    if greens:
        best = max(greens, key=lambda r: r["min_glucose"])
        return {"workout": {"start": best["start"], "duration_min": 30, "kind": "aerobic", "label": "30 min workout"}, "snacks": []}
    ambers = [r for r in scan if r["color"] == "amber"]
    if ambers:
        best = max(ambers, key=lambda r: r["min_glucose"])
        return {"workout": {"start": best["start"], "duration_min": 30, "kind": "aerobic", "label": "30 min workout"},
                "snacks": [_iso(datetime.fromisoformat(best["start"]) - timedelta(minutes=20))]}
    return {"workout": None, "snacks": []}
