"""The chat's tools: plain Python functions over the session's Twin, each returning a
JSON-serialisable dict. The router (Gemini function calling, or the local keyword classifier)
chooses among them and phrases the result; every number the chat says comes from here.

Each tool's docstring is the description the router sees; `TOOLS` carries the parameter
schemas. The first argument of every tool is the Twin and is not part of the schema."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.engine import fast
from backend.engine.fast import IDX, UIDX, MG_PER_MMOL, MMOL_PER_G
from backend.engine.simulate import events_to_inputs, simulate, state_params
from backend.schema.events import Event
from backend.decision import home as home_view
from backend.decision.permission import evaluate_permission
from backend.decision.plain import permission_plain, understood_line, plan_plain, change_plain, fmt12, fmt_date, likelihood, event_phrase
from backend.decision.planner import plan_day as _plan_day
from backend.decision.change import evaluate_change, CHANGES
from backend.decision.personal import as_population
from backend.adapters.parse import parse_text
from backend.adapters.local_parser import parse_text_local

log = logging.getLogger("glucopilot.chat")


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="minutes")


def _r(x, d: int = 0):
    v = round(float(x), d)
    return int(v) if d == 0 else v


def _when(iso: str, now: datetime) -> str:
    """'at 7:30 pm' today, 'yesterday at 8:20 am', 'tomorrow at 7:00 am', else the date."""
    d = datetime.fromisoformat(iso)
    dd = (d.date() - now.date()).days
    t = fmt12(iso)
    if dd == 0:
        return f"at {t}"
    if dd == -1:
        return f"yesterday at {t}"
    if dd == 1:
        return f"tomorrow at {t}"
    return f"on {fmt_date(iso)} at {t}"


def _target(twin) -> Tuple[float, float]:
    from backend.api.twin import target_range
    return target_range(twin)


# ------------------------------------------------------------------ 1. current state

def get_current_state(twin) -> Dict[str, Any]:
    """Use for any question about right now: current glucose / blood sugar, whether it is rising
    or falling, how many carbs are digesting, insulin working, liver stores, ketones, energy,
    recovery, caffeine or alcohol in the body, the time of the last reading and whether the
    sensor is stale. No parameters."""
    s, std = twin.state_now()
    lo, hi = _target(twin)
    tr = home_view.trend(twin)
    tiles = twin.cached("tiles", lambda: home_view.tiles(twin))
    stale = twin.staleness_min()
    g = float(s.glucose)
    out = {
        "as_of": _iso(twin.now), "as_of_text": fmt12(_iso(twin.now)),
        "glucose": _r(g), "glucose_uncertainty": _r(std.get("glucose", 0.0)),
        "target_low": _r(lo), "target_high": _r(hi),
        "position": "in range" if lo <= g <= hi else ("low" if g < lo else "high"),
        "trend": tr["word"], "trend_arrow": tr["arrow"], "trend_mgdl_per_min": tr["slope_mgdl_per_min"],
        "trend_mgdl_per_hour": _r(tr["slope_mgdl_per_min"] * 60),
        "last_reading_time": _iso(twin.now), "sensor_staleness_min": _r(stale), "sensor_stale": bool(stale > 20),
        "tiles": [{"key": t["key"], "label": t["label"], "value": t["value"], "unit": t["unit"], "value_text": t["value_text"],
                   "status": t["status"], "tone": t["tone"], "note": t["note"]} for t in tiles],
    }
    by = {t["key"]: t for t in tiles}
    out["carbs_digesting_g"] = by["carbs"]["value"] if "carbs" in by else 0
    out["insulin_working_pct"] = by["insulin"]["value"] if "insulin" in by else None
    out["liver_stores_g"] = by["liver"]["value"] if "liver" in by else None
    out["ketones_mmol"] = by["ketones"]["value"] if "ketones" in by else None
    out["energy"] = by["energy"]["value"] if "energy" in by else None
    out["recovery"] = by["recovery"]["value"] if "recovery" in by else None
    out["caffeine_mg"] = by["caffeine"]["value"] if "caffeine" in by else 0
    out["blood_alcohol_pct"] = by["alcohol"]["value"] if "alcohol" in by else 0
    return out


# ------------------------------------------------------------------ 2. forecast

def _extremes(times: List[str], med: np.ndarray, n: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    seg = med[:n]
    k_hi, k_lo = int(np.argmax(seg)), int(np.argmin(seg))
    return ({"value": _r(seg[k_hi]), "time": times[k_hi], "time_text": fmt12(times[k_hi])},
            {"value": _r(seg[k_lo]), "time": times[k_lo], "time_text": fmt12(times[k_lo])})


def get_forecast(twin, hours: float = 4.0) -> Dict[str, Any]:
    """Use for questions about the future: what glucose will be in N hours, tonight, by
    bedtime or by morning; whether a low or a high is coming; the predicted peak and low and
    when. Parameters: hours (1-16; 'tonight' or 'overnight' = 12, 'in 2 hours' = 2)."""
    h = float(min(max(hours or 4.0, 1.0), 16.0))
    horizon = int(round(h * 60 / 5.0) * 5)
    mc = twin.cached(f"forecast:{max(horizon, 480)}", lambda: twin.forecast(horizon_min=max(horizon, 480)))
    n = horizon // 5 + 1
    times = list(mc.times[:n])
    med, p10, p90 = np.asarray(mc.median[:n]), np.asarray(mc.p10[:n]), np.asarray(mc.p90[:n])
    samples = np.asarray(mc.glucose_samples[:, :n])
    p_low = float(np.mean(samples.min(axis=1) < 70))
    p_severe = float(np.mean(samples.min(axis=1) < 54))
    p_high = float(np.mean(samples.max(axis=1) > 250))
    peak, low = _extremes(times, med, n)
    below = next((t for t, v in zip(times, med) if v < 70), None)
    lo, hi = _target(twin)
    return {
        "hours": h, "from": _iso(twin.now), "from_text": fmt12(_iso(twin.now)), "to": times[-1], "to_text": fmt12(times[-1]),
        "now_glucose": _r(med[0]), "expected_at_end": _r(med[-1]), "range_at_end": [_r(p10[-1]), _r(p90[-1])],
        "peak": peak, "low": low,
        "p_low": round(p_low, 3), "p_low_pct": _r(100 * p_low), "p_low_word": likelihood(p_low),
        "p_severe_low_pct": _r(100 * p_severe), "p_high": round(p_high, 3), "p_high_pct": _r(100 * p_high), "p_high_word": likelihood(p_high),
        "median_first_below_70": below, "median_first_below_70_text": fmt12(below) if below else None,
        "target_low": _r(lo), "target_high": _r(hi),
        "times": times, "median": [_r(x, 1) for x in med], "p10": [_r(x, 1) for x in p10], "p90": [_r(x, 1) for x in p90],
        "parameters": "your fitted twin",
    }


# ------------------------------------------------------------------ 3. explain now

def _gut_after(carbs_g: float, fat_g: float, fiber_g: float, minutes: float, p: Dict[str, Any]) -> Tuple[float, float, float]:
    """Two-compartment gut chain run for `minutes` after a meal: (D1, D2, absorbed so far) in bioavailable grams."""
    tau = max((1.0 + p["gut_fat_tau_gain"] * fat_g / 50.0 + p["gut_fiber_tau_gain"] * fiber_g / 10.0) * p["tau_carb"], 5.0)
    spread = max(15.0, p["gut_meal_spread_min"])
    rate = carbs_g * p["carb_ratio"] / spread
    d1 = d2 = absorbed = 0.0
    for m in range(int(minutes)):
        cin = rate if m < spread else 0.0
        out2 = d2 / tau
        d1 += cin - d1 / tau
        d2 += d1 / tau - out2
        absorbed += out2
    return d1, d2, absorbed


def explain_now(twin, mentioned_meal_minutes_ago: Optional[float] = None, mentioned_carbs_g: Optional[float] = None) -> Dict[str, Any]:
    """Use for 'why' questions about the present: why glucose is not rising after eating, why it
    is dropping or climbing, what is pushing it right now, how much insulin is still active
    (insulin on board) and when it peaks, how many carbs are still digesting and when they hit,
    whether the liver is releasing sugar, what alcohol, exercise or caffeine are doing.
    Decomposes the model's glucose rate of change into its terms (mg/dL per hour).
    Parameters (optional): mentioned_meal_minutes_ago (the person says they ate N minutes ago;
    if that meal is not logged it is assumed), mentioned_carbs_g (grams if they said)."""
    now = twin.now
    s, _ = twin.state_now()
    p = state_params(twin.medium_state(), twin.params)
    x = np.array(twin.hidden_now(), dtype=float).reshape(1, -1)
    x[0, IDX["Q1"]] = float(s.glucose) / MG_PER_MMOL * p["VG"]
    x[0, IDX["I"]] = float(s.plasma_insulin)
    ctx = twin.context_events(past_hours=8)
    assumed = None
    if mentioned_meal_minutes_ago is not None:
        m = float(max(min(mentioned_meal_minutes_ago, 240), 1))
        t_meal = now - timedelta(minutes=m)
        near = [e for e in ctx if e.type == "meal" and abs((e.start - t_meal).total_seconds()) <= 30 * 60]
        if not near:
            carbs = float(mentioned_carbs_g) if mentioned_carbs_g else 45.0
            assumed = Event(type="meal", start_time=_iso(t_meal), duration_min=15, carbs_g=carbs, fat_g=12, protein_g=15, fiber_g=3,
                            uncertainty=0.5, source="chat", label="meal you mentioned")
            d1, d2, _ = _gut_after(carbs, 12.0, 3.0, m, p)
            x[0, IDX["D1"]] += d1
            x[0, IDX["D2"]] += d2
            ctx = sorted(ctx + [assumed], key=lambda e: e.start)
    u = events_to_inputs(ctx, now, 1, 5, p)[:1]
    if assumed is not None:
        # the meal is a past event: its input already went through the gut chain above
        u[0, UIDX["carb"]] = 0.0
        u[0, UIDX["tau_g"]] = max(u[0, UIDX["tau_g"]], 1.0 + p["gut_fat_tau_gain"] * 12.0 / 50.0 + p["gut_fiber_tau_gain"] * 3.0 / 10.0)

    Q1, Q2, I = x[:, 0], x[:, 1], x[:, 4]
    x1, x2, x3 = x[:, 5], x[:, 6], x[:, 7]
    D1, D2, L = x[:, 8], x[:, 9], x[:, 10]
    BAC, C, hang, anaer = x[:, 12], x[:, 14], x[:, 20], x[:, 19]
    S1, S2 = x[:, 2], x[:, 3]
    BW, VG = p["BW"], p["VG"]
    G_mmol = Q1 / VG
    tau_g = max(float(u[0, UIDX["tau_g"]]) * p["tau_carb"], 5.0)
    UG_g = D2 / tau_g
    UG = UG_g * MMOL_PER_G / BW
    Lh, Lfloor = p["liver_L_half"], p["liver_L_floor"]
    gly_fac = (Lfloor + (1 - Lfloor) * L / (L + Lh)) / (Lfloor + (1 - Lfloor) * 60.0 / (60.0 + Lh))
    alc_drive = 0.6 * BAC + p["alcohol_hangover_gain"] * hang
    alc_sup = np.clip(1.0 - p["alcohol_gain"] * p["alcohol_egp_suppression_per_bac"] * alc_drive, p["alcohol_egp_floor"], 1.0)
    stress_ill = 1.0 + p["illness_egp_gain"] * u[:, UIDX["ill"]] + p["stress_egp_gain"] * u[:, UIDX["stress"]]
    anaer_fac = 1.0 + p["exercise_anaerobic_egp_gain"] * anaer * p["exercise_mult"]
    EGP = np.maximum(p["EGP0"] * (1.0 - x3) * gly_fac * alc_sup * stress_ill * anaer_fac, 0.0)
    ex_int = u[:, UIDX["ex_int"]]
    F01 = p["F01"] * (1.0 + p["exercise_uptake_gain"] * ex_int * p["exercise_mult"])
    thr = p["G_F01_threshold_mmol"]
    F01c = np.where(G_mmol >= thr, F01, F01 * G_mmol / thr)
    F01c_base = np.where(G_mmol >= thr, p["F01"], p["F01"] * G_mmol / thr)
    FR = np.where(G_mmol >= p["renal_threshold_mmol"], p["renal_k"] * (G_mmol - p["renal_threshold_mmol"]) * VG, 0.0)
    ins_net = -(x1 * Q1 - p["k12"] * Q2)

    def mgdl_h(v) -> float:
        return float(v) / VG * MG_PER_MMOL * 60.0

    carbs_t, liver_t, ins_t = mgdl_h(UG), mgdl_h(EGP), mgdl_h(ins_net)
    basic_t, ex_t, renal_t = -mgdl_h(F01c_base), -mgdl_h(F01c - F01c_base), -mgdl_h(FR)
    caf_t = 0.0
    caf_fac = float(1.0 / (1.0 + p["caffeine_si_drop_per_200mg"] * C / 200.0))
    if float(C) > 5.0 and caf_fac < 0.999:
        ins_cf = -(x1 / caf_fac * Q1 - p["k12"] * Q2)
        egp_cf = EGP * (1.0 - np.minimum(x3 / caf_fac, 0.99)) / np.maximum(1.0 - x3, 1e-6)
        caf_t = (ins_t + liver_t) - (mgdl_h(ins_cf) + mgdl_h(egp_cf))
        ins_t -= ins_t - mgdl_h(ins_cf)
        liver_t -= liver_t - mgdl_h(egp_cf)
    total = carbs_t + liver_t + ins_t + basic_t + ex_t + renal_t + caf_t

    # ---- what is pending: carbs in the gut and their timing, insulin on board and its peak
    tr = simulate(s, [e for e in ctx if e is not assumed], twin.params, 240, t0=now, hidden=x[0])
    times = tr.times()
    gut = np.asarray(tr.series["gut_carbs_1"]) + np.asarray(tr.series["gut_carbs_2"])
    rate = np.asarray(tr.series["gut_carbs_2"]) / tau_g * 60.0   # g per hour still to be absorbed (same units as the Home tile)
    gut_eaten = float((D1 + D2)[0])
    k_peak = int(np.argmax(rate)) if gut_eaten > 1 else 0
    done = next((i for i, v in enumerate(gut) if v < 0.15 * max(gut[0], 1e-9)), None) if gut_eaten > 1 else 0
    ins = np.asarray(tr.series["plasma_insulin"])
    iob_u = float((S1 + S2)[0]) * BW / 1000.0
    basal_i = float(fast.steady_basal_insulin(p, 120.0))
    k_ins = int(np.argmax(ins[:49]))
    boluses = [e for e in ctx if e.type == "insulin" and e.insulin_kind == "bolus" and e.start <= now]
    meals = [e for e in ctx if e.type == "meal" and e.start <= now]
    last_bolus = boluses[-1] if boluses else None
    last_meal = meals[-1] if meals else None
    tau_mult = float(u[0, UIDX["tau_g"]])
    sensor_slope = home_view.trend(twin)["slope_mgdl_per_min"] * 60.0

    terms = [
        {"key": "carbs", "label": "Carbs absorbing", "mgdl_per_hour": _r(carbs_t, 1),
         "detail": f"{gut_eaten:.0f} g of carbs still in the gut" + (f"; fat and fibre are slowing absorption ({tau_mult:.1f}x slower)" if tau_mult > 1.05 else "")},
        {"key": "liver", "label": "Liver releasing sugar", "mgdl_per_hour": _r(liver_t, 1),
         "detail": f"stores at {float(L[0]):.0f} g ({100 * float(L[0]) / p['liver_L_max']:.0f}% full)"
                   + (f"; insulin is holding it down by {100 * float(x3[0]):.0f}%" if float(x3[0]) > 0.05 else "")
                   + (f"; alcohol is suppressing it by {100 * (1 - float(alc_sup[0])):.0f}%" if float(alc_sup[0]) < 0.97 else "")
                   + ("; low stores are limiting it" if float(gly_fac[0]) < 0.9 else "")},
        {"key": "insulin", "label": "Insulin moving sugar into cells", "mgdl_per_hour": _r(ins_t, 1),
         "detail": f"{iob_u:.1f} U still to act, plasma insulin {float(I[0]):.0f} mU/L ({float(I[0]) / max(basal_i, 1e-6):.1f}x your basal level)"},
        {"key": "basic", "label": "Brain and body baseline use", "mgdl_per_hour": _r(basic_t, 1), "detail": "insulin-independent uptake"},
    ]
    if abs(ex_t) > 0.5:
        terms.append({"key": "exercise", "label": "Exercise uptake", "mgdl_per_hour": _r(ex_t, 1), "detail": f"activity at {100 * float(ex_int[0]):.0f}% intensity"})
    if abs(caf_t) > 0.5:
        terms.append({"key": "caffeine", "label": "Caffeine blunting insulin", "mgdl_per_hour": _r(caf_t, 1), "detail": f"{float(C[0]):.0f} mg in the body; insulin works {100 * (1 - caf_fac):.0f}% less well"})
    if abs(renal_t) > 0.5:
        terms.append({"key": "renal", "label": "Sugar lost in urine", "mgdl_per_hour": _r(renal_t, 1), "detail": "glucose above the kidney threshold"})

    pending = {
        "carbs_g": _r(gut_eaten), "carbs_absorbing_g_per_hour": _r(rate[0], 1),
        "carbs_peak_in_min": int(k_peak * 5) if gut_eaten > 1 else None, "carbs_peak_time": times[k_peak] if gut_eaten > 1 else None,
        "carbs_done_in_min": int(done * 5) if (gut_eaten > 1 and done is not None) else None,
        "absorption_slowdown": _r(tau_mult, 2),
        "insulin_on_board_u": _r(iob_u, 1), "plasma_insulin_mU_L": _r(float(I[0]), 1), "insulin_vs_basal": _r(float(I[0]) / max(basal_i, 1e-6), 1),
        "insulin_peak_in_min": int(k_ins * 5), "insulin_peak_time": times[k_ins], "insulin_peaked_already": bool(k_ins == 0),
        "last_bolus": {"units": _r(last_bolus.insulin_units, 1), "time": last_bolus.start_time, "time_text": fmt12(last_bolus.start_time), "minutes_ago": _r((now - last_bolus.start).total_seconds() / 60)} if last_bolus else None,
        "last_meal": {"label": last_meal.label or "meal", "carbs_g": _r(last_meal.carbs_g), "time": last_meal.start_time, "time_text": fmt12(last_meal.start_time), "minutes_ago": _r((now - last_meal.start).total_seconds() / 60), "logged": last_meal is not assumed} if last_meal else None,
        "assumed_meal": bool(assumed is not None),
    }
    return {
        "as_of": _iso(now), "as_of_text": fmt12(_iso(now)), "glucose": _r(float(s.glucose)),
        "sensor_rate_mgdl_per_hour": _r(sensor_slope, 1), "model_rate_mgdl_per_hour": _r(total, 1),
        "direction": "rising" if total > 6 else "falling" if total < -6 else "roughly flat",
        "terms": terms, "pending": pending, "summary": _explain_summary(total, sensor_slope, terms, pending, now),
    }


def _explain_summary(total: float, sensor: float, terms: List[Dict[str, Any]], pending: Dict[str, Any], now: datetime) -> str:
    by = {t["key"]: t["mgdl_per_hour"] for t in terms}
    direction = "rising" if total > 6 else "falling" if total < -6 else "roughly flat"
    bits = [f"the model has your glucose {direction} at about {abs(total):.0f} mg/dL per hour"]
    push = [f"carbs adding {by['carbs']:.0f}" if by.get("carbs", 0) > 1 else None, f"your liver adding {by['liver']:.0f}" if by.get("liver", 0) > 1 else None]
    pull = [f"insulin taking {abs(by['insulin']):.0f}" if by.get("insulin", 0) < -1 else None, f"exercise taking {abs(by['exercise']):.0f}" if by.get("exercise", 0) < -1 else None]
    parts = [b for b in push + pull if b]
    if parts:
        bits.append(", ".join(parts) + " mg/dL per hour")
    s = "Right now " + ": ".join(bits) + "."
    if pending["carbs_g"] and pending["carbs_g"] > 3:
        if pending["carbs_peak_in_min"] is not None and pending["carbs_peak_in_min"] > 5:
            s += f" {pending['carbs_g']:.0f} g of carbs are still digesting; they hit fastest in about {pending['carbs_peak_in_min']} min"
        else:
            s += f" {pending['carbs_g']:.0f} g of carbs are still digesting and absorbing at full speed now"
        if pending["carbs_done_in_min"]:
            s += f" and are mostly absorbed in about {pending['carbs_done_in_min']} min"
        s += "."
        if pending["absorption_slowdown"] > 1.05:
            s += f" Fat and fibre are slowing them ({pending['absorption_slowdown']:.1f}x)."
    if pending["assumed_meal"]:
        s += " That meal is not in your log, so I assumed a typical one; log it to make this exact."
    if pending["insulin_on_board_u"] > 0.3:
        s += f" {pending['insulin_on_board_u']:.1f} U of insulin is still to act" + (", peaking now" if pending["insulin_peaked_already"] else f", peaking in about {pending['insulin_peak_in_min']} min") + "."
    return s


# ------------------------------------------------------------------ 4. history

METRICS = ["glucose", "lows", "average", "tir", "events", "carbs", "insulin", "exercise", "sleep", "caffeine", "alcohol"]


def _low_episodes(times: List[datetime], g: np.ndarray, valid: np.ndarray, thresh: float = 70.0) -> List[Dict[str, Any]]:
    """Distinct lows: a run starts at a valid reading under `thresh` and ends after 30 min back above 70."""
    eps, cur, above = [], None, 0
    for t, v, ok in zip(times, g, valid):
        if not ok or np.isnan(v):
            continue
        if v < thresh:
            if cur is None:
                cur = {"start": _iso(t), "min": float(v), "min_time": _iso(t)}
            elif v < cur["min"]:
                cur["min"], cur["min_time"] = float(v), _iso(t)
            above = 0
        elif cur is not None:
            above += 1 if v > 70 else 0
            if above >= 6:
                cur["end"] = _iso(t)
                eps.append(cur)
                cur, above = None, 0
    if cur is not None:
        cur["end"] = _iso(times[-1])
        eps.append(cur)
    for e in eps:
        e["min"] = _r(e["min"])
        e["start_text"], e["min_time_text"], e["date_text"] = fmt12(e["start"]), fmt12(e["min_time"]), fmt_date(e["start"])
    return eps


def query_history(twin, start: str, end: str, metric: str = "glucose") -> Dict[str, Any]:
    """Use for anything about the past: glucose at a time or over a range ('at 3 pm', 'this
    morning', 'yesterday', 'last week'), lows this week, when the last low was, average glucose and
    time in range, what was eaten (events), carbs / insulin / exercise / caffeine / alcohol totals,
    how much sleep last night. Parameters: start, end (ISO local datetimes; for 'at 3 pm' use a
    10-minute window), metric: one of glucose, lows, average, tir, events, carbs, insulin,
    exercise, sleep, caffeine, alcohol. Every call also returns the aggregates for the window."""
    now = twin.now
    a = datetime.fromisoformat(start)
    b = min(datetime.fromisoformat(end), now)
    if b <= a:
        a = b - timedelta(minutes=10)
    metric = metric if metric in METRICS else "glucose"
    t = twin.pt.cgm.times
    m = (t >= pd.Timestamp(a)) & (t <= pd.Timestamp(b))
    tt = [x.to_pydatetime() for x in t[m]]
    g = np.asarray(twin.pt.cgm.glucose[m], dtype=float)
    ok = np.asarray(twin.pt.cgm.valid[m], dtype=bool)
    gv = g[ok & ~np.isnan(g)]
    span_h = (b - a).total_seconds() / 3600.0
    step = 1 if span_h <= 12 else 3 if span_h <= 72 else 6
    from backend.data.series import series_for_display
    disp = series_for_display(tt, g, ok)["display"]     # the shared gap rule, before any downsampling
    series = {"times": [_iso(x) for x in tt[::step]], "values": [None if v is None else _r(v) for v in disp[::step]]}
    lows = _low_episodes(tt, g, ok)
    nearest = None
    if len(tt):
        i = int(np.argmin([abs((x - a).total_seconds()) for x in tt]))
        j = next((k for k in range(i, min(i + 4, len(tt))) if ok[k] and not np.isnan(g[k])), None)
        if j is not None:
            nearest = {"time": _iso(tt[j]), "time_text": fmt12(_iso(tt[j])), "value": _r(g[j])}
    # events in the window (no basal, no water)
    evs = [e for e in twin.pt.events if a <= e.start <= b and not (e.type == "insulin" and e.insulin_kind == "basal") and e.type != "water"]
    ev_rows = [{"time": e.start_time, "time_text": fmt12(e.start_time), "when": _when(e.start_time, now), "type": e.type, "label": e.label or e.type,
                "carbs_g": _r(e.carbs_g), "insulin_units": _r(e.insulin_units, 1), "duration_min": _r(e.duration_min), "alcohol_g": _r(e.alcohol_g),
                "caffeine_mg": _r(e.caffeine_mg), "sleep_hours": _r(e.sleep_hours, 1)} for e in evs if e.type != "sleep"]
    totals = {"carbs_g": _r(sum(e.carbs_g for e in evs)), "bolus_units": _r(sum(e.insulin_units for e in evs if e.type == "insulin"), 1),
              "exercise_min": _r(sum(e.duration_min for e in evs if e.type == "exercise")), "alcohol_g": _r(sum(e.alcohol_g for e in evs)),
              "drinks": _r(sum(e.alcohol_g for e in evs) / 14.0, 1), "caffeine_mg": _r(sum(e.caffeine_mg for e in evs)),
              "meals": sum(1 for e in evs if e.type == "meal"), "workouts": sum(1 for e in evs if e.type == "exercise")}
    # sleep: the sleep records that ended inside the window (bedtime the evening before counts)
    sleeps = [e for e in twin.pt.events if e.type == "sleep" and a - timedelta(hours=14) <= e.start <= b and e.start + timedelta(minutes=e.duration_min) >= a]
    sleep_rows = [{"bed": e.start_time, "bed_text": fmt12(e.start_time), "wake": _iso(e.start + timedelta(minutes=e.duration_min)),
                   "wake_text": fmt12(_iso(e.start + timedelta(minutes=e.duration_min))), "hours": _r(e.sleep_hours or e.duration_min / 60.0, 1),
                   "night_of": fmt_date(e.start_time)} for e in sleeps]
    # the last low even if it is before the window
    last_low = lows[-1] if lows else None
    if last_low is None:
        m2 = (t <= pd.Timestamp(b)) & (t >= pd.Timestamp(b - timedelta(days=30)))
        eps = _low_episodes([x.to_pydatetime() for x in t[m2]], np.asarray(twin.pt.cgm.glucose[m2], dtype=float), np.asarray(twin.pt.cgm.valid[m2], dtype=bool))
        last_low = eps[-1] if eps else None
    out = {
        "metric": metric, "start": _iso(a), "end": _iso(b), "start_text": f"{fmt_date(_iso(a))} {fmt12(_iso(a))}", "end_text": f"{fmt_date(_iso(b))} {fmt12(_iso(b))}",
        "window_hours": _r(span_h, 1), "n_readings": int(len(gv)),
        "average": _r(np.mean(gv)) if len(gv) else None, "sd": _r(np.std(gv)) if len(gv) else None,
        "min": {"value": _r(np.nanmin(gv)), "time": _iso(tt[int(np.nanargmin(np.where(ok, g, np.nan)))]), "time_text": fmt12(_iso(tt[int(np.nanargmin(np.where(ok, g, np.nan)))]))} if len(gv) else None,
        "max": {"value": _r(np.nanmax(gv)), "time": _iso(tt[int(np.nanargmax(np.where(ok, g, np.nan)))]), "time_text": fmt12(_iso(tt[int(np.nanargmax(np.where(ok, g, np.nan)))]))} if len(gv) else None,
        "time_in_range_pct": _r(100 * np.mean((gv >= 70) & (gv <= 180))) if len(gv) else None,
        "time_below_70_pct": _r(100 * np.mean(gv < 70), 1) if len(gv) else None, "time_above_180_pct": _r(100 * np.mean(gv > 180), 1) if len(gv) else None,
        "lows": lows, "n_lows": len(lows), "last_low": last_low,
        "last_low_when": _when(last_low["min_time"], now) if last_low else None,
        "reading_nearest_start": nearest,
        "events": ev_rows, "totals": totals, "sleep": sleep_rows, "series": series,
    }
    return out


# ------------------------------------------------------------------ 5. permission

def _event_from(twin, event: Optional[Dict[str, Any]], text: Optional[str], default_now: bool = True) -> Tuple[Event, str]:
    """An Event from a structured dict (the router's function args) or, failing that, from the text."""
    parser = "router"
    if event and event.get("type"):
        d = {k: v for k, v in event.items() if v is not None}
        if str(d.get("start_time", "")).lower() in ("", "now"):
            d["start_time"] = _iso(twin.now)
        d.setdefault("source", "chat")
        d.setdefault("uncertainty", 0.25)
        ev = Event.from_dict(d)
    else:
        pe = parse_text(text or "", twin.now)
        parser = pe.parser
        ev = Event.from_dict(pe.event.model_dump())
    return ev, parser


def evaluate_action(twin, event: Optional[Dict[str, Any]] = None, text: Optional[str] = None) -> Dict[str, Any]:
    """Use when the person proposes or asks permission for something they have NOT done yet:
    'can I have pizza for dinner', 'run at 7 tomorrow for 30 min', 'is dessert okay', 'two more
    beers tonight', 'large coffee now'. Runs the permission engine (Monte Carlo over the decision
    window) and returns the verdict, condition, probabilities, peak / low with times and the plain
    reason. Parameters: event {type, start_time (ISO or 'now'), duration_min, carbs_g, fat_g,
    protein_g, fiber_g, alcohol_g, caffeine_mg, insulin_units, insulin_kind, exercise_kind,
    intensity, label}; or text (the message) to let the food parser build the event."""
    ev, parser = _event_from(twin, event, text)
    card = evaluate_permission(twin, ev)
    from backend.api.app import _cause_of_pending_low, _chat_log_line   # local import: app imports this module
    card.plain = permission_plain(card, twin.now, _cause_of_pending_low(twin))
    card.plain["understood"] = understood_line(card.proposed.model_dump() if card.proposed else {}, twin.now)
    card.engine["log"] = _chat_log_line(twin, ev, card)
    card.engine["parser"] = parser
    log.info(card.engine["log"])
    d = card.model_dump()
    v = {x["name"]: x for x in card.variants}
    prop, best = v.get("proposed", {}), v.get(card.variant_name, v.get("proposed", {}))
    d["summary"] = {"verdict": card.verdict, "headline": card.plain["headline"], "reason": card.plain["reason"], "condition": card.condition,
                    "p_low_pct": _r(100 * card.p_hypo), "p_high_pct": _r(100 * card.p_hyper),
                    "proposed_low": _r(prop.get("nadir", 0)), "proposed_low_time_text": fmt12(prop.get("nadir_time")) if prop.get("nadir_time") else None,
                    "proposed_peak": _r(prop.get("peak", 0)), "proposed_peak_time_text": fmt12(prop.get("peak_time")) if prop.get("peak_time") else None,
                    "with_condition_low": _r(best.get("nadir", 0)), "event": event_phrase(ev.to_dict()), "when": _when(ev.start_time, twin.now)}
    return d


# ------------------------------------------------------------------ 6. log

def log_event(twin, event: Optional[Dict[str, Any]] = None, text: Optional[str] = None) -> Dict[str, Any]:
    """Use when the person reports something they already DID (past tense or 'just'): 'I just ate
    a bagel', 'I had a large coffee 20 minutes ago', 'just finished a 30 minute run', 'took 4
    units'. Records the event in their log, re-estimates the body state and returns the updated
    state. Not for questions or proposals. Parameters: event {type, start_time (ISO; 'now' if
    unsaid; a workout that just finished starts duration_min ago), duration_min, carbs_g, fat_g,
    protein_g, fiber_g, alcohol_g, caffeine_mg, insulin_units, insulin_kind, exercise_kind,
    intensity, label}; or text (the message) for the food parser."""
    ev, parser = _event_from(twin, event, text)
    if ev.start > twin.now + timedelta(minutes=5):
        ev = ev.copy(start_time=_iso(twin.now))
    if ev.start >= twin.now - timedelta(minutes=1):
        # "just ate" / "just finished": the thing is already behind us, so the estimator can see it
        back = ev.duration_min if ev.type == "exercise" and ev.duration_min > 0 else 10.0
        ev = ev.copy(start_time=_iso(twin.now - timedelta(minutes=back)))
    ev = ev.copy(source="chat")
    twin.log_event(ev)
    state = get_current_state(twin)
    log.info("CHAT logged event=%s parser=%s -> glucose=%s carbs_digesting=%s", ev.to_dict(), parser, state["glucose"], state["carbs_digesting_g"])
    return {"logged": True, "event": ev.to_dict(), "phrase": event_phrase(ev.to_dict()), "when": _when(ev.start_time, twin.now),
            "understood": f"Logged: {event_phrase(ev.to_dict())} {_when(ev.start_time, twin.now)}", "parser": parser, "state": state}


# ------------------------------------------------------------------ 7-9. plan, change, compare

def plan_day(twin, date: str = "tomorrow", drinks: int = 0) -> Dict[str, Any]:
    """Use for '/plan', 'plan tomorrow', 'when should I work out tomorrow', 'best time to
    exercise'. Places tomorrow's workout (and a snack if needed) around the usual meals.
    Parameters: date ('tomorrow' or ISO date), drinks (planned drinks that evening, default 0)."""
    day = datetime.fromisoformat(date) if date and date != "tomorrow" else None
    plan = twin.cached(f"plan:{date}:{drinks}", lambda: _plan_day(twin, day=day, drinks=int(drinks or 0)))
    plan.plain = plan_plain(plan, twin.now)
    d = plan.model_dump()
    d["summary"] = {"headline": plan.plain["headline"], "reason": plan.plain["reason"], "workout_start_text": fmt12(plan.workout_start) if plan.workout_start else None,
                    "snack_time_text": fmt12(plan.snack_time) if plan.snack_time else None, "p_low_pct": _r(100 * plan.p_hypo)}
    return d


def change_lifestyle(twin, name: str) -> Dict[str, Any]:
    """Use for '/change <name>' or 'what if I moved my workouts to the morning / cut caffeine /
    only drank on Fridays / skipped breakfast (16:8)': rewrites a typical week and runs 30 days.
    Parameters: name, one of morning_workouts, cut_caffeine, drink_fridays_only, fasting_16_8."""
    if name not in CHANGES:
        return {"error": f"unknown change {name!r}", "options": CHANGES}
    resp = twin.cached("no_change", lambda: evaluate_change(twin, "no_change"), keyed=False) if name == "no_change" else evaluate_change(twin, name)
    resp.plain = change_plain(resp)
    twin.cards.append({"kind": "change", "at": _iso(twin.now), "card": resp.model_dump()})
    twin.last_change = resp  # type: ignore[attr-defined]
    d = resp.model_dump()
    d["summary"] = {"headline": resp.plain["headline"], "reason": resp.plain["reason"], "verdict": resp.verdict}
    return d


def compare_to_average(twin, event: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Use for 'compared to average', 'what would the answer be for a typical person', 'how am I
    different from the average person with T1D' about the LAST permission question (or a given
    event). Re-runs the permission engine with population parameters. Parameters: event (optional)."""
    if event is None and twin.last_card is not None and twin.last_card.proposed is not None:
        event = twin.last_card.proposed.model_dump()
    if event is None:
        return {"error": "nothing to compare yet: ask about a meal, drink or workout first"}
    ev, _ = _event_from(twin, event, None)
    personal = twin.last_card if (twin.last_card and twin.last_card.proposed and twin.last_card.proposed.start_time == ev.start_time) else evaluate_permission(twin, ev)
    keep = twin.last_card
    with as_population(twin):
        pop = evaluate_permission(twin, ev)
    twin.last_card = keep
    if twin.cards and twin.cards[-1].get("kind") == "permission":
        twin.cards.pop()
    pp, pl = permission_plain(personal, twin.now), permission_plain(pop, twin.now)
    return {"event": event_phrase(ev.to_dict()), "personal": {"verdict": personal.verdict, "headline": pp["headline"], "reason": pp["reason"], "p_low_pct": _r(100 * personal.p_hypo)},
            "population": {"verdict": pop.verdict, "headline": pl["headline"], "reason": pl["reason"], "p_low_pct": _r(100 * pop.p_hypo)},
            "same_verdict": personal.verdict == pop.verdict, "card": pop.model_dump()}


# ------------------------------------------------------------------ 10. what if

def whatif(twin, events: Optional[List[Dict[str, Any]]] = None, skip: Optional[str] = None, hours: float = 8.0, text: Optional[str] = None) -> Dict[str, Any]:
    """Use for hypotheticals that are neither a permission question nor a log: 'what if I skip
    dinner', 'what if I have two coffees', 'what happens if I don't bolus'. Simulates the rest of
    the day with the person's usual meals, with and without the change, and compares. Nothing is
    logged. Parameters: events (list of event objects to add), skip (a usual event to remove:
    'dinner', 'lunch', 'breakfast', 'meal', 'bolus'), hours (horizon, default 8)."""
    now = twin.now
    h = float(min(max(hours or 8.0, 2.0), 16.0))
    horizon = int(h * 60)
    routine = [e for e in home_view.routine_future(twin) if e.start <= now + timedelta(minutes=horizon)]
    extra = []
    for d in events or []:
        ev, _ = _event_from(twin, d, None)
        extra.append(ev)
    if not extra and text and not skip:
        ev, _ = _event_from(twin, None, text)
        extra.append(ev)
    removed = []
    scen = list(routine)
    if skip:
        k = skip.lower()
        meals = [e for e in routine if e.type == "meal"]
        pick = None
        if k in ("dinner", "supper", "tonight"):
            pick = next((e for e in meals if e.start.hour >= 16), None)
        elif k == "lunch":
            pick = next((e for e in meals if 11 <= e.start.hour < 16), None)
        elif k == "breakfast":
            pick = next((e for e in meals if e.start.hour < 11), None)
        elif k in ("meal", "next meal", "food"):
            pick = meals[0] if meals else None
        elif k in ("bolus", "insulin"):
            pick = next((e for e in routine if e.type == "insulin"), None)
        if pick is not None:
            removed.append(pick)
            scen = [e for e in routine if e is not pick]
            if pick.type == "meal":   # the usual bolus for that meal goes with it
                bol = [e for e in scen if e.type == "insulin" and abs((e.start - pick.start).total_seconds()) <= 30 * 60]
                removed += bol
                scen = [e for e in scen if e not in bol]
    scen = sorted(scen + extra, key=lambda e: e.start)
    base_mc = twin.forecast(extra=routine, horizon_min=horizon)
    scen_mc = twin.forecast(extra=scen, horizon_min=horizon)

    def pack(mc):
        n = len(mc.times)
        peak, low = _extremes(mc.times, np.asarray(mc.median), n)
        p_low = float(np.mean(np.asarray(mc.min_glucose_samples) < 70))
        return {"peak": peak, "low": low, "p_low_pct": _r(100 * p_low), "p_low_word": likelihood(p_low), "p_high_pct": _r(100 * mc.p_hyper),
                "median": [_r(x, 1) for x in mc.median], "p10": [_r(x, 1) for x in mc.p10], "p90": [_r(x, 1) for x in mc.p90], "expected_at_end": _r(mc.median[-1])}

    b, s = pack(base_mc), pack(scen_mc)
    return {"hours": h, "times": list(base_mc.times), "to_text": fmt12(base_mc.times[-1]),
            "baseline": {"label": "as usual", "assumes": [f"{event_phrase(e.to_dict())} {_when(e.start_time, now)}" for e in routine if e.type == "meal"], **b},
            "scenario": {"label": "what if", "removed": [f"{event_phrase(e.to_dict())} {_when(e.start_time, now)}" for e in removed],
                         "added": [f"{event_phrase(e.to_dict())} {_when(e.start_time, now)}" for e in extra], **s},
            "difference": {"low_delta": _r(s["low"]["value"] - b["low"]["value"]), "peak_delta": _r(s["peak"]["value"] - b["peak"]["value"]),
                           "p_low_delta_pct": _r(s["p_low_pct"] - b["p_low_pct"]), "end_delta": _r(s["expected_at_end"] - b["expected_at_end"])},
            "skip": skip, "nothing_changed": bool(not removed and not extra)}


# ------------------------------------------------------------------ registry

EVENT_SCHEMA = {
    "type": "OBJECT",
    "description": "One event for the physiology model.",
    "properties": {
        "type": {"type": "STRING", "enum": ["meal", "insulin", "alcohol", "caffeine", "exercise", "sleep", "illness", "stress", "water"]},
        "start_time": {"type": "STRING", "description": "ISO local datetime like 2026-09-12T19:00, or 'now'"},
        "duration_min": {"type": "NUMBER"}, "carbs_g": {"type": "NUMBER"}, "fat_g": {"type": "NUMBER"}, "protein_g": {"type": "NUMBER"},
        "fiber_g": {"type": "NUMBER"}, "alcohol_g": {"type": "NUMBER", "description": "grams of ethanol; one drink = 14"},
        "caffeine_mg": {"type": "NUMBER", "description": "coffee 95, large coffee 190, espresso 63, tea 45"},
        "insulin_units": {"type": "NUMBER"}, "insulin_kind": {"type": "STRING", "enum": ["bolus", "basal"]},
        "exercise_kind": {"type": "STRING", "enum": ["aerobic", "anaerobic", "mixed"]}, "intensity": {"type": "NUMBER", "description": "0-1"},
        "sleep_hours": {"type": "NUMBER"}, "label": {"type": "STRING", "description": "short human label, e.g. 'bagel', 'large coffee', '30 min run'"},
    },
    "required": ["type"],
}

TOOLS: Dict[str, Dict[str, Any]] = {
    "get_current_state": {"fn": get_current_state, "parameters": {"type": "OBJECT", "properties": {}}},
    "get_forecast": {"fn": get_forecast, "parameters": {"type": "OBJECT", "properties": {"hours": {"type": "NUMBER", "description": "1-16"}}}},
    "explain_now": {"fn": explain_now, "parameters": {"type": "OBJECT", "properties": {
        "mentioned_meal_minutes_ago": {"type": "NUMBER", "description": "if the person says they ate N minutes ago"},
        "mentioned_carbs_g": {"type": "NUMBER"}}}},
    "query_history": {"fn": query_history, "parameters": {"type": "OBJECT", "properties": {
        "start": {"type": "STRING", "description": "ISO local datetime"}, "end": {"type": "STRING", "description": "ISO local datetime"},
        "metric": {"type": "STRING", "enum": METRICS}}, "required": ["start", "end"]}},
    "evaluate_action": {"fn": evaluate_action, "parameters": {"type": "OBJECT", "properties": {"event": EVENT_SCHEMA, "text": {"type": "STRING"}}}},
    "log_event": {"fn": log_event, "parameters": {"type": "OBJECT", "properties": {"event": EVENT_SCHEMA, "text": {"type": "STRING"}}}},
    "plan_day": {"fn": plan_day, "parameters": {"type": "OBJECT", "properties": {"date": {"type": "STRING"}, "drinks": {"type": "INTEGER"}}}},
    "change_lifestyle": {"fn": change_lifestyle, "parameters": {"type": "OBJECT", "properties": {"name": {"type": "STRING", "enum": CHANGES}}, "required": ["name"]}},
    "compare_to_average": {"fn": compare_to_average, "parameters": {"type": "OBJECT", "properties": {"event": EVENT_SCHEMA}}},
    "whatif": {"fn": whatif, "parameters": {"type": "OBJECT", "properties": {
        "events": {"type": "ARRAY", "items": EVENT_SCHEMA}, "skip": {"type": "STRING", "enum": ["dinner", "lunch", "breakfast", "meal", "bolus"]},
        "hours": {"type": "NUMBER"}}}},
}


def describe(name: str) -> str:
    return " ".join((TOOLS[name]["fn"].__doc__ or "").split())


def call(twin, name: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run one tool by name with keyword args (unknown keys dropped)."""
    spec = TOOLS[name]
    fn = spec["fn"]
    allowed = set(spec["parameters"].get("properties", {}).keys())
    kw = {k: v for k, v in (args or {}).items() if k in allowed}
    if name in ("evaluate_action", "log_event", "whatif") and not kw.get("event") and not kw.get("events") and not kw.get("skip") and args and args.get("text"):
        kw["text"] = args["text"]
    return fn(twin, **kw)
