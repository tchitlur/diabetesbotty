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
TILE_ORDER = ["carbs", "liver", "ketones", "hydration", "energy", "body", "training", "insulin", "alcohol", "caffeine"]


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


def history(twin, hours: float = 3.0) -> Dict[str, List]:
    t = twin.pt.cgm.times
    m = (t > pd.Timestamp(twin.now - timedelta(hours=hours))) & (t <= pd.Timestamp(twin.now))
    g, v = twin.pt.cgm.glucose[m], twin.pt.cgm.valid[m]
    return {"times": [x.isoformat(timespec="minutes") for x in t[m]],
            "glucose": [None if (not ok or np.isnan(x)) else round(float(x), 1) for x, ok in zip(g, v)]}


# ------------------------------------------------------------------ tiles

def _status(v: float, cuts: List[Tuple[float, str, str]], last: Tuple[str, str]) -> Tuple[str, str]:
    for lim, word, tone in cuts:
        if v < lim:
            return word, tone
    return last


def tiles(twin) -> List[Dict[str, Any]]:
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
        # change over the next hour relative to the tile's full scale
        k = min(12, len(arr) - 1)
        return abs(float(arr[k] - arr[0])) / max(scale, 1e-9)

    out: List[Dict[str, Any]] = []
    # carbs still digesting
    carbs = ser["gut_carbs_1"] + ser["gut_carbs_2"]
    v = float(carbs[0])
    word, tone = _status(v, [(3, "none left", "good"), (15, "a little", "good"), (40, "some", "good")], ("a lot", "warn"))
    out.append({"key": "carbs", "icon": "🍞", "label": "Carbs digesting", "value": round(v), "unit": "g", "value_text": f"{v:.0f} g",
                "level": min(v / 60.0, 1.0), "status": word, "tone": tone, "visual": "bar", "forecast": fc(carbs, 0),
                "note": "Carbs from recent food that are still being absorbed. They push glucose up over the next hour or two.",
                "score": max(min(v / 60.0, 1.0) * 0.8, rate(carbs, 60.0) * 2)})
    # liver energy stores
    lmax = float(p.get("liver_L_max", 120.0))
    v = float(ser["liver_glycogen"][0])
    lvl = v / lmax
    word, tone = _status(lvl, [(0.3, "running low", "bad"), (0.6, "half full", "warn")], ("well stocked", "good"))
    out.append({"key": "liver", "icon": "🫀", "label": "Liver energy stores", "value": round(v), "unit": "g", "value_text": f"{v:.0f} g", "sub": f"of {lmax:.0f} g",
                "level": lvl, "status": word, "tone": tone, "visual": "level", "forecast": fc(ser["liver_glycogen"], 0),
                "note": "Sugar your liver keeps in reserve. It releases it between meals and overnight; alcohol and long gaps run it down.",
                "score": max(max(0.0, 0.6 - lvl) * 2, rate(ser["liver_glycogen"], lmax) * 2)})
    # ketones
    v = float(ser["ketones"][0])
    word, tone = _status(v, [(0.6, "normal", "good"), (1.5, "raised", "warn")], ("high", "bad"))
    out.append({"key": "ketones", "icon": "🧪", "label": "Ketones", "value": round(v, 2), "unit": "mmol/L", "value_text": f"{v:.1f}", "sub": "mmol/L",
                "level": min(v / 1.5, 1.0), "status": word, "tone": tone, "visual": "gauge", "forecast": fc(ser["ketones"], 2),
                "note": "Made when the body burns fat instead of sugar. Above 0.6 with high glucose means you need more insulin.",
                "score": max(min(v / 1.5, 1.0), rate(ser["ketones"], 1.5) * 2)})
    # hydration
    v = float(ser["hydration"][0])
    word, tone = _status(v, [(0.6, "dehydrated", "bad"), (0.8, "drink some water", "warn")], ("well hydrated", "good"))
    out.append({"key": "hydration", "icon": "💧", "label": "Hydration", "value": round(100 * v), "unit": "%", "value_text": f"{100 * v:.0f}%",
                "level": v, "status": word, "tone": tone, "visual": "level", "forecast": fc(100 * ser["hydration"], 0),
                "note": "How much water your body has on board. High glucose and alcohol both dry you out.",
                "score": max(max(0.0, 0.85 - v) * 2, rate(ser["hydration"], 1.0) * 2)})
    # energy / readiness
    v = float(ser["energy_score"][0])
    word, tone = _status(v, [(45, "low", "bad"), (70, "okay", "warn")], ("good", "good"))
    out.append({"key": "energy", "icon": "⚡", "label": "Energy & readiness", "value": round(v), "unit": "/100", "value_text": f"{v:.0f}", "sub": "out of 100",
                "level": v / 100.0, "status": word, "tone": tone, "visual": "gauge", "forecast": fc(ser["energy_score"], 0),
                "note": "How ready you are right now: steady glucose, enough sleep, not too much caffeine, well hydrated.",
                "score": max(max(0.0, 0.7 - v / 100.0) * 1.5, rate(ser["energy_score"], 100.0) * 2)})
    # body composition
    fat, lean = float(s.fat_mass), float(s.lean_mass)
    frac = fat / max(fat + lean, 1e-6)
    daily = list(twin._daily.values())
    d30 = (fat - float(daily[-31].fat_mass)) if len(daily) > 31 else 0.0
    word, tone = ("stable", "good") if abs(d30) < 0.3 else ("trimming", "good") if d30 < 0 else ("gaining", "warn")
    out.append({"key": "body", "icon": "🧍", "label": "Body composition", "value": round(100 * frac, 1), "unit": "% fat", "value_text": f"{100 * frac:.0f}% fat", "sub": f"{fat + lean:.0f} kg body weight",
                "level": min(frac / 0.4, 1.0), "status": word, "tone": tone, "visual": "bar",
                "forecast": {"times": times, "values": [round(100 * frac, 1)] * len(times)},
                "note": f"Fat {fat:.1f} kg, muscle and the rest {lean:.1f} kg. Changes slowly: {d30:+.1f} kg of fat over the last 30 days.",
                "score": min(abs(d30) / 2.0, 1.0) * 0.5})
    # training load & recovery
    load, debt = float(s.training_load), float(s.sleep_debt)
    if debt > 3:
        word, tone = "needs rest", "warn"
    elif load > 25:
        word, tone = "heavy week", "warn"
    elif load < 5:
        word, tone = "light week", "good"
    else:
        word, tone = "recovered", "good"
    out.append({"key": "training", "icon": "🏃", "label": "Training load & recovery", "value": round(load), "unit": "", "value_text": f"load {load:.0f}", "sub": f"sleep debt {debt:.1f} h",
                "level": min(load / 40.0, 1.0), "status": word, "tone": tone, "visual": "bar",
                "forecast": {"times": times, "values": [round(load, 1)] * len(times)},
                "note": "Recent exercise adds to the load; sleep pays it back. A heavy week or a short night makes insulin work harder.",
                "score": max(debt / 6.0, abs(load - 12.0) / 30.0)})
    # how well insulin is working today
    v = float(s.insulin_sensitivity) * (1 - p.get("sleep_debt_coef", 0.2) * min(debt, 3.0) / 2.5)
    word, tone = ("working less well", "warn") if v < 0.9 else ("better than usual", "good") if v > 1.1 else ("as usual", "good")
    out.append({"key": "insulin", "icon": "💉", "label": "How well insulin is working", "value": round(100 * v), "unit": "% of usual", "value_text": f"{100 * v:.0f}%", "sub": "of your usual",
                "level": float(np.clip((v - 0.6) / 0.8, 0, 1)), "status": word, "tone": tone, "visual": "gauge",
                "forecast": {"times": times, "values": [round(100 * v)] * len(times)},
                "note": "Compared with your normal. Short sleep, a hard week and illness make insulin work less well; exercise makes it work better.",
                "score": abs(v - 1.0) * 3})
    # alcohol in system (only when relevant)
    if alcohol_recent:
        v = float(ser["blood_alcohol"][0])
        word, tone = _status(v, [(0.01, "almost gone", "good"), (0.05, "clearing", "warn")], ("in your blood", "bad"))
        gone = next((times[i] for i, x in enumerate(ser["blood_alcohol"]) if x < 0.005), None)
        out.append({"key": "alcohol", "icon": "🍺", "label": "Alcohol in system", "value": round(v, 3), "unit": "% BAC", "value_text": f"{v:.3f}%", "sub": "blood alcohol",
                    "level": min(v / 0.10, 1.0), "status": word, "tone": tone, "visual": "level", "forecast": fc(ser["blood_alcohol"], 3),
                    "note": "While your liver is busy clearing alcohol it releases less sugar, so a low can come hours later, often overnight." + (f" Gone by about {gone[11:16]}." if gone else ""),
                    "score": min(v / 0.10, 1.0) * 2 + 0.3})
    # caffeine in system (only when relevant)
    if caffeine_recent:
        v = float(ser["caffeine"][0])
        word, tone = _status(v, [(25, "almost gone", "good"), (100, "some left", "good")], ("plenty left", "warn"))
        out.append({"key": "caffeine", "icon": "☕", "label": "Caffeine in system", "value": round(v), "unit": "mg", "value_text": f"{v:.0f} mg",
                    "level": min(v / 200.0, 1.0), "status": word, "tone": tone, "visual": "level", "forecast": fc(ser["caffeine"], 0),
                    "note": "Caffeine halves about every 5 hours. It makes insulin work a little less well and can spoil sleep.",
                    "score": min(v / 200.0, 1.0) + 0.2})
    for t in out:
        t["level"] = round(float(np.clip(t["level"], 0, 1)), 3)
        t["score"] = round(float(t["score"]), 3)
    # dynamic order: anything far from normal or moving fast first, then the fixed order
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


def timeline(twin, workout: Optional[Dict[str, Any]] = None, snack: Optional[str] = None) -> Dict[str, Any]:
    now = twin.now
    bt = bedtime(twin)
    end = bt if (bt - now) >= timedelta(hours=6) else bt + timedelta(days=1)
    routine = [e for e in routine_future(twin) if e.start <= end]
    accepted = [e for e in twin.future_events() if e.start <= end]
    ctx_base = twin.context_events() + routine
    w_ev = None
    if workout and workout.get("start"):
        w_ev = Event(type="exercise", start_time=workout["start"], duration_min=float(workout.get("duration_min", 30)),
                     exercise_kind=workout.get("kind", "aerobic"), intensity=float(workout.get("intensity", 0.6)), uncertainty=0.15,
                     source="tap", label=workout.get("label") or f"{int(workout.get('duration_min', 30))} min workout")
    s_ev = Event(type="meal", start_time=snack, carbs_g=15, duration_min=5, uncertainty=0.1, source="tap", label="small snack (15 g)") if snack else None
    extras = [e for e in (w_ev, s_ev) if e is not None]
    starts = _slots(twin, now, end - timedelta(minutes=30))
    # each slot is judged with everything else in place; the slot holding the planned workout is judged with that workout alone
    per = []
    for st in starts:
        base = list(ctx_base) + list(accepted) + ([s_ev] if s_ev else [])
        if w_ev is not None and abs((st - w_ev.start).total_seconds()) >= 30 * 60:
            base.append(w_ev)
        per.append(base)
    scan = scan_starts(twin, "exercise", starts, ctx_base + accepted + extras, per_start_ctx=per)
    slots = [{"start": r["start"], "end": _iso(datetime.fromisoformat(r["start"]) + timedelta(minutes=30)), "color": r["color"], "reason": r["reason"]} for r in scan]
    items: List[Dict[str, Any]] = []
    for e in routine:
        if e.type == "meal":
            items.append({"time": e.start_time, "kind": "meal", "label": (e.label or "meal").replace("usual ", "usual "), "predicted": True, "movable": False, "carbs_g": round(e.carbs_g)})
    for e in accepted:
        kind = {"meal": "meal", "exercise": "workout", "alcohol": "drink", "caffeine": "coffee"}.get(e.type)
        if kind:
            items.append({"time": e.start_time, "kind": kind, "label": e.label or e.type, "predicted": False, "movable": False})
    if w_ev is not None:
        items.append({"time": w_ev.start_time, "kind": "workout", "label": w_ev.label, "predicted": False, "movable": True, "duration_min": w_ev.duration_min})
    if s_ev is not None:
        items.append({"time": s_ev.start_time, "kind": "snack", "label": s_ev.label, "predicted": False, "movable": False})
    items.append({"time": _iso(bt), "kind": "sleep", "label": "bedtime", "predicted": True, "movable": False})
    if end > bt:
        items.append({"time": _iso(bt + timedelta(days=1)), "kind": "sleep", "label": "bedtime", "predicted": True, "movable": False})
    items.sort(key=lambda x: x["time"])
    days = [{"date": now.date().isoformat(), "label": "Tonight" if now.hour >= 17 else "Today"}]
    if end.date() > now.date():
        days.append({"date": (now + timedelta(days=1)).date().isoformat(), "label": "Tomorrow"})
    return {"start": _iso(now), "end": _iso(end), "bedtime": _iso(bt), "days": days, "slots": slots, "items": items,
            "workout": ({"start": w_ev.start_time, "duration_min": w_ev.duration_min, "kind": w_ev.exercise_kind, "label": w_ev.label} if w_ev else None),
            "snack": snack}


def auto_plan(twin) -> Dict[str, Any]:
    """'Plan my day': place the workout (and a snack if the planner wants one) automatically."""
    from backend.decision.planner import plan_day
    now = twin.now
    bt = bedtime(twin)
    end = bt if (bt - now) >= timedelta(hours=6) else bt + timedelta(days=1)
    if end.date() > now.date():
        plan = twin.cached("plan:tomorrow:0", lambda: plan_day(twin, day=None, drinks=0))
        w = {"start": plan.workout_start, "duration_min": 30, "kind": "aerobic", "label": "30 min workout"} if plan.workout_start else None
        return {"workout": w, "snack": plan.snack_time}
    ctx = twin.context_events() + routine_future(twin)
    scan = scan_starts(twin, "exercise", _slots(twin, now, end - timedelta(hours=1)), ctx)
    greens = [r for r in scan if r["color"] == "green"]
    if greens:
        best = max(greens, key=lambda r: r["min_glucose"])
        return {"workout": {"start": best["start"], "duration_min": 30, "kind": "aerobic", "label": "30 min workout"}, "snack": None}
    ambers = [r for r in scan if r["color"] == "amber"]
    if ambers:
        best = max(ambers, key=lambda r: r["min_glucose"])
        return {"workout": {"start": best["start"], "duration_min": 30, "kind": "aerobic", "label": "30 min workout"},
                "snack": _iso(datetime.fromisoformat(best["start"]) - timedelta(minutes=20))}
    return {"workout": None, "snack": None}
