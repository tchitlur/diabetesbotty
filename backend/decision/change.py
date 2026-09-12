"""Change requests: a named lifestyle change rewrites the representative
week, which is simulated (fast layer, both weeks batched), rolled through the
medium layer for 30 days and the slow layer for 10 years. Returns the diff of
every State variable and organ risk with a verdict."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np

from backend.schema.events import Event
from backend.schema.state import State, ALL_FIELDS, FAST_FIELDS, MEDIUM_FIELDS, SLOW_FIELDS, UNITS
from backend.schema.api import ChangeResponse, DiffRow
from backend.engine import fast
from backend.engine.fast import IDX
from backend.engine.simulate import events_to_inputs, initial_vector, state_params
from backend.engine.medium import daily_update, summarize_day, run_medium, DaySummary
from backend.engine.slow import run_slow, WeekProfile, DayProfile, ORGANS

CHANGES = ["morning_workouts", "cut_caffeine", "drink_fridays_only", "fasting_16_8", "no_change"]
DT = 5


def rewrite_week(name: str, week_start: datetime, events: List[Event]) -> List[Event]:
    ev = [e.copy() for e in events]
    if name == "no_change":
        return ev
    if name == "morning_workouts":
        # move every existing workout to 07:00 the same day (same kind/duration) and top up to 3 per week
        moved, days_used = [], set()
        for e in ev:
            if e.type == "exercise":
                t = e.start.replace(hour=7, minute=0)
                if e.start.date() in days_used:
                    continue
                days_used.add(e.start.date())
                moved.append(e.copy(start_time=t.isoformat(timespec="minutes"), label=f"morning {e.label or 'workout'}"))
        ev = [e for e in ev if e.type != "exercise"]
        for d in (0, 2, 4):
            day = (week_start + timedelta(days=d)).date()
            if len(moved) >= 3:
                break
            if day not in days_used:
                t = week_start + timedelta(days=d, hours=7)
                moved.append(Event(type="exercise", start_time=t.isoformat(timespec="minutes"), duration_min=30, exercise_kind="aerobic", intensity=0.6, uncertainty=0.15, source="tap", label="morning run"))
                days_used.add(day)
        return sorted(ev + moved, key=lambda e: e.start)
    if name == "cut_caffeine":
        out = []
        for e in ev:
            if e.type == "caffeine":
                continue
            if e.type == "sleep":
                e = e.copy(sleep_hours=min(e.sleep_hours + 0.5, 9.0))
            out.append(e)
        return out
    if name == "drink_fridays_only":
        out = []
        for e in ev:
            if e.type == "alcohol":
                if e.start.weekday() != 4:
                    continue
                n = max(e.alcohol_g / 14.0, 1.0)
                if n > 3:
                    e = e.copy(alcohol_g=42.0, carbs_g=e.carbs_g * 3.0 / n, duration_min=min(e.duration_min, 150))
            out.append(e)
        return out
    if name == "fasting_16_8":
        out = []
        drop_bolus_times = set()
        for e in ev:
            if e.type == "meal" and e.start.hour < 12:
                drop_bolus_times.add((e.start.date(), e.start.hour))
                continue
            out.append(e)
        out2 = []
        for e in out:
            if e.type == "insulin" and e.insulin_kind == "bolus" and (e.start.date(), e.start.hour) in drop_bolus_times:
                continue
            if e.type in ("meal", "insulin") and e.start.hour >= 20 and not (e.type == "insulin" and e.insulin_kind == "basal"):
                e = e.copy(start_time=e.start.replace(hour=19, minute=45).isoformat(timespec="minutes"))
            out2.append(e)
        return sorted(out2, key=lambda e: e.start)
    raise ValueError(f"unknown change {name!r}; choose one of {CHANGES}")


def simulate_weeks(twin, week_start: datetime, weeks: List[List[Event]], state: State) -> Tuple[np.ndarray, np.ndarray]:
    """Batched 7-day simulation of several event weeks. Returns (glucose (B, T), X (T+1, B, NS))."""
    p = state_params(state, twin.params)
    n_steps = 7 * 24 * 60 // DT
    inputs = np.stack([events_to_inputs(ev, week_start, n_steps, DT, p) for ev in weeks], axis=1)
    s0 = State(glucose=130.0, plasma_insulin=float(fast.steady_basal_insulin(p, 130.0)), liver_glycogen=60.0, muscle_glycogen=350.0)
    x0 = np.repeat(initial_vector(s0, p), len(weeks), axis=0)
    X = fast.integrate(x0, inputs, p, DT, substeps=1)
    G = fast.glucose_mgdl(X, p).T
    return G, X


def week_summaries(events: List[Event], week_start: datetime, G: np.ndarray, X: np.ndarray, p: Dict) -> Tuple[List[DaySummary], WeekProfile]:
    steps = 24 * 60 // DT
    days_s, days_p = [], []
    H = X[:, IDX["H"]]
    for d in range(7):
        day_ev = [e for e in events if (e.start - week_start).days == d]
        g = G[d * steps:(d + 1) * steps]
        ds = summarize_day(day_ev, float(g.mean()), float(g.std()))
        days_s.append(ds)
        days_p.append(DayProfile(mean_glucose=float(g.mean()), sd_glucose=float(g.std()), frac_above_180=float(np.mean(g > 180)),
                                 hydration=float(H[d * steps:(d + 1) * steps].mean()), alcohol_g=ds.alcohol_g,
                                 hypo_minutes=float(np.mean(g < 70) * 1440), tir=float(np.mean((g >= 70) & (g <= 180)))))
    return days_s, WeekProfile(days_p)


def evaluate_change(twin, name: str) -> ChangeResponse:
    if name not in CHANGES:
        raise ValueError(f"unknown change {name!r}; choose one of {CHANGES}")
    week_start, base_ev = twin.representative_week_events()
    new_ev = rewrite_week(name, week_start, base_ev)
    ms = twin.medium_state()
    p = state_params(ms, twin.params)
    G, X = simulate_weeks(twin, week_start, [base_ev, new_ev], ms)
    results = {}
    for label, ev, i in (("baseline", base_ev, 0), ("change", new_ev, 1)):
        days_s, profile = week_summaries(ev, week_start, G[i], X[:, i, :], p)
        med = run_medium(ms, days_s, 30, sleep_debt_coef=twin.params["sleep_debt_coef"])
        m30 = med[-1]
        for d in profile.days:
            d.sleep_debt = m30.sleep_debt
            d.fat_mass = m30.fat_mass
        slow = run_slow(profile, m30, years=10.0)
        fast_means = {k: float(np.mean(_series(X[:, i, :], k, p))) for k in FAST_FIELDS}
        results[label] = {"m30": m30, "slow": slow, "fast": fast_means, "profile": profile, "week_events": ev}
    b, c = results["baseline"], results["change"]
    diff: List[DiffRow] = []
    for k in ALL_FIELDS:
        if k in FAST_FIELDS:
            b30, c30 = b["fast"][k], c["fast"][k]
            b10, c10 = b30, c30
        elif k in MEDIUM_FIELDS:
            b30, c30 = getattr(b["m30"], k), getattr(c["m30"], k)
            b10, c10 = getattr(b["slow"].final_state, k), getattr(c["slow"].final_state, k)
        else:
            b30 = b["slow"].yearly[0][k] * 30 / 365 if b["slow"].yearly else 0.0
            c30 = c["slow"].yearly[0][k] * 30 / 365 if c["slow"].yearly else 0.0
            b10, c10 = getattr(b["slow"].final_state, k), getattr(c["slow"].final_state, k)
        diff.append(DiffRow(variable=k, unit=UNITS[k], baseline_30d=round(b30, 4), change_30d=round(c30, 4), baseline_10y=round(b10, 4), change_10y=round(c10, 4)))
    pb, pc = b["slow"].probabilities, c["slow"].probabilities
    risk_b, risk_c = float(np.mean(list(pb.values()))), float(np.mean(list(pc.values())))
    hypo_b, hypo_c = b["profile"].total("hypo_minutes"), c["profile"].total("hypo_minutes")
    tir_b, tir_c = b["profile"].mean("tir"), c["profile"].mean("tir")
    if name == "no_change":
        verdict, reason = "merged", "No change requested; baseline kept."
    elif risk_c <= risk_b * 1.01 and hypo_c <= hypo_b * 1.2 + 10:
        verdict = "merged"
        reason = f"10-year mean organ risk {risk_b:.1%} -> {risk_c:.1%}; weekly hypo minutes {hypo_b:.0f} -> {hypo_c:.0f}; TIR {tir_b:.0%} -> {tir_c:.0%}."
    elif risk_c <= risk_b * 1.01:
        verdict = "merged_with_changes"
        reason = (f"Long-term risk improves ({risk_b:.1%} -> {risk_c:.1%}) but weekly hypo minutes rise {hypo_b:.0f} -> {hypo_c:.0f}. "
                  f"Merged with a 20 g snack before each new workout and a 10 % lower bolus at the meal after it.")
    else:
        verdict = "rejected"
        reason = f"10-year mean organ risk would rise {risk_b:.1%} -> {risk_c:.1%} (TIR {tir_b:.0%} -> {tir_c:.0%})."
    return ChangeResponse(change=name, verdict=verdict, reason=reason, diff=diff,
                          organ_risk_baseline={k: round(v, 4) for k, v in pb.items()},
                          organ_risk_change={k: round(v, 4) for k, v in pc.items()},
                          week_summary={"baseline": b["profile"].summary(), "change": c["profile"].summary(),
                                        "week_start": week_start.date().isoformat(),
                                        "events_removed": len(base_ev) - len(new_ev) if len(new_ev) < len(base_ev) else 0,
                                        "events_added": len(new_ev) - len(base_ev) if len(new_ev) > len(base_ev) else 0})


def _series(X: np.ndarray, k: str, p: Dict) -> np.ndarray:
    m = {"glucose": None, "plasma_insulin": "I", "gut_carbs_1": "D1", "gut_carbs_2": "D2", "liver_glycogen": "L", "muscle_glycogen": "M",
         "blood_alcohol": "BAC", "caffeine": "C", "ketones": "K", "hydration": "H"}
    if k == "glucose":
        return fast.glucose_mgdl(X, p)
    if k == "energy_score":
        return fast.energy_score(X, p)
    return X[:, IDX[m[k]]]
