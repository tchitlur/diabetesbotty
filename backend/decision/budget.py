"""Budget: weekly alcohol, caffeine and off-plan meals that keep 10-year
organ risk within 5 % of the clean baseline.

Marginal effects of each item on the representative week are measured by
simulation (one day with / without the item, batched), then the slow-layer
hazard is solved by bisection for each item's share of the 5 % headroom."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np

from backend.schema.events import Event
from backend.schema.state import State
from backend.schema.api import BudgetResponse
from backend.engine import fast
from backend.engine.fast import IDX
from backend.engine.simulate import events_to_inputs, initial_vector, state_params
from backend.engine.slow import run_slow, WeekProfile, DayProfile
from backend.decision.planner import typical_day_events

TOLERANCE = 0.05
DT = 5


def _risk(profile: WeekProfile, state: State) -> float:
    return float(np.mean(list(run_slow(profile, state).probabilities.values())))


def _clean_profile(twin) -> WeekProfile:
    base = twin.week_profile()
    days = []
    for d in base.days:
        days.append(DayProfile(mean_glucose=d.mean_glucose, sd_glucose=d.sd_glucose, frac_above_180=d.frac_above_180,
                               hydration=max(d.hydration, 0.88), alcohol_g=0.0, sleep_debt=min(d.sleep_debt, 1.0),
                               fat_mass=d.fat_mass, hypo_minutes=d.hypo_minutes, tir=d.tir))
    return WeekProfile(days)


def marginal_effects(twin) -> Dict[str, Dict[str, float]]:
    """Per-unit daily effects measured by simulating a typical day with the item added."""
    day = (twin.now + timedelta(days=1)).replace(hour=0, minute=0)
    routine = typical_day_events(twin, day)
    variants = {
        "base": [],
        "drink": [Event(type="alcohol", start_time=day.replace(hour=20).isoformat(), duration_min=90, alcohol_g=28.0, carbs_g=20.0, source="tap", label="2 drinks")],
        "coffee": [Event(type="caffeine", start_time=day.replace(hour=15).isoformat(), caffeine_mg=200.0, source="tap", label="200 mg afternoon coffee")],
        "meal": [Event(type="meal", start_time=day.replace(hour=16).isoformat(), carbs_g=45.0, fat_g=15.0, source="tap", label="off-plan 45 g snack, no bolus")],
    }
    p = state_params(twin.medium_state(), twin.params)
    n_steps = 30 * 60 // DT
    keys = list(variants)
    inputs = np.stack([events_to_inputs(sorted(routine + variants[k], key=lambda e: e.start), day, n_steps, DT, p) for k in keys], axis=1)
    s0 = State(glucose=130.0, plasma_insulin=float(fast.steady_basal_insulin(p, 130.0)), liver_glycogen=60.0)
    x0 = np.repeat(initial_vector(s0, p), len(keys), axis=0)
    X = fast.integrate(x0, inputs, p, DT, substeps=2)
    G = fast.glucose_mgdl(X, p)
    H = X[:, :, IDX["H"]]
    out = {}
    g0, sd0, h0 = G[:, 0].mean(), G[:, 0].std(), H[:, 0].mean()
    for i, k in enumerate(keys[1:], start=1):
        out[k] = {"d_mean": float(G[:, i].mean() - g0), "d_sd": float(G[:, i].std() - sd0), "d_hydration": float(H[:, i].mean() - h0)}
    out["drink"]["per_g"] = 1.0 / 28.0
    out["coffee"]["per_mg"] = 1.0 / 200.0
    return out


def current_levels(twin) -> Dict[str, float]:
    """Current weekly alcohol (g), caffeine (mg) and off-plan meals (unbolused meals/snacks), averaged over the last 4 weeks."""
    lo = twin.now - timedelta(days=28)
    ev = [e for e in twin.pt.events if lo <= e.start <= twin.now]
    alcohol = sum(e.alcohol_g for e in ev if e.type == "alcohol") / 4.0
    caffeine = sum(e.caffeine_mg for e in ev if e.type == "caffeine") / 4.0
    boluses = [e.start for e in ev if e.type == "insulin" and e.insulin_kind == "bolus"]
    off_plan = 0
    for m in (e for e in ev if e.type == "meal" and e.carbs_g >= 15):
        if not any(abs((bt - m.start).total_seconds()) <= 45 * 60 for bt in boluses):
            off_plan += 1
    return {"alcohol_g_week": alcohol, "caffeine_mg_week": caffeine, "off_plan_meals_week": off_plan / 4.0}


def _profile_with(clean: WeekProfile, eff: Dict[str, Dict[str, float]], alcohol_g_week: float, caffeine_mg_week: float, meals_week: float) -> WeekProfile:
    days = []
    for i, d in enumerate(clean.days):
        alc = alcohol_g_week / 7.0
        caf = caffeine_mg_week / 7.0
        m = meals_week / 7.0
        e_a, e_c, e_m = eff["drink"], eff["coffee"], eff["meal"]
        days.append(DayProfile(
            mean_glucose=d.mean_glucose + e_a["d_mean"] * alc / 28.0 + e_c["d_mean"] * caf / 200.0 + e_m["d_mean"] * m,
            sd_glucose=d.sd_glucose + e_a["d_sd"] * alc / 28.0 + e_c["d_sd"] * caf / 200.0 + e_m["d_sd"] * m,
            frac_above_180=d.frac_above_180, hydration=d.hydration + e_a["d_hydration"] * alc / 28.0,
            alcohol_g=alc, sleep_debt=d.sleep_debt + 0.3 * caf / 200.0, fat_mass=d.fat_mass,
            hypo_minutes=d.hypo_minutes, tir=d.tir))
    return WeekProfile(days)


def _solve(fn, target: float, lo: float, hi: float, iters: int = 30) -> float:
    if fn(hi) <= target:
        return hi
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if fn(mid) <= target:
            lo = mid
        else:
            hi = mid
    return lo


def compute_budget(twin) -> BudgetResponse:
    """Weekly allowances that keep the 10-year mean organ risk within 5 % of
    the baseline (= the current lifestyle). Each item receives one third of the
    headroom with the other two held at their current levels, so the three
    allowances are jointly feasible."""
    ms = twin.medium_state()
    clean = _clean_profile(twin)
    eff = marginal_effects(twin)
    cur = current_levels(twin)
    a0, c0, m0 = cur["alcohol_g_week"], cur["caffeine_mg_week"], cur["off_plan_meals_week"]
    base = _risk(_profile_with(clean, eff, a0, c0, m0), ms)
    share = TOLERANCE / 3.0
    alc = _solve(lambda a: _risk(_profile_with(clean, eff, a, c0, m0), ms), base * (1 + share), 0.0, 400.0)
    caf = _solve(lambda c: _risk(_profile_with(clean, eff, a0, c, m0), ms), base * (1 + share), 0.0, 2800.0)
    meals = _solve(lambda m: _risk(_profile_with(clean, eff, a0, c0, m), ms), base * (1 + share), 0.0, 21.0)
    meals_i = int(np.floor(meals))
    at_budget = _risk(_profile_with(clean, eff, alc, caf, meals_i), ms)
    return BudgetResponse(alcohol_g_per_week=round(alc, 1), caffeine_mg_per_week=round(caf, 0), off_plan_meals_per_week=meals_i,
                          baseline_risk=round(base, 4), risk_at_budget=round(at_budget, 4), tolerance=TOLERANCE)
