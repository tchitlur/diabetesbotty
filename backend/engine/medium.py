"""Medium layer: daily update of sleep debt, insulin sensitivity, training
load, body composition and HbA1c.

`daily_update` is pure: it takes yesterday's State, the day's events and the
day's mean glucose, and returns today's State. `run_medium` loops it over a
representative week for N days (used by the change-request engine).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from backend.schema.state import State
from backend.schema.events import Event
from backend.engine.params import medium_params


@dataclass
class DaySummary:
    mean_glucose: float
    sleep_hours: float
    caffeine_at_bed_mg: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    protein_g: float = 0.0
    alcohol_g: float = 0.0
    exercise_load: float = 0.0     # sum(intensity * minutes) / 10
    glucose_sd: float = 0.0


def summarize_day(events: List[Event], mean_glucose: float, glucose_sd: float = 0.0, default_sleep: float = 7.5) -> DaySummary:
    sleep = [e for e in events if e.type == "sleep"]
    sleep_h = float(sleep[-1].sleep_hours) if sleep else default_sleep
    caf_bed = 0.0
    for e in events:
        if e.type == "caffeine":
            hrs_before_bed = max(0.0, 23.0 - (e.start.hour + e.start.minute / 60.0))
            caf_bed += e.caffeine_mg * 0.5 ** (hrs_before_bed / 5.0)
    return DaySummary(
        mean_glucose=float(mean_glucose),
        sleep_hours=sleep_h,
        caffeine_at_bed_mg=caf_bed,
        carbs_g=sum(e.carbs_g for e in events),
        fat_g=sum(e.fat_g for e in events),
        protein_g=sum(e.protein_g for e in events),
        alcohol_g=sum(e.alcohol_g for e in events),
        exercise_load=sum((e.intensity if e.intensity > 0 else 0.6) * max(e.duration_min, 30.0) for e in events if e.type == "exercise") / 10.0,
        glucose_sd=float(glucose_sd),
    )


def daily_update(state: State, day: DaySummary, mp: Optional[Dict[str, float]] = None, sleep_debt_coef: float = 0.2) -> State:
    mp = mp or medium_params()
    s = state.copy()
    # ---- sleep debt (hours): bounded exponential accumulator; caffeine near bedtime degrades sleep
    eff_sleep = day.sleep_hours * (1.0 - mp["caffeine_sleep_drop_per_200mg"] * min(day.caffeine_at_bed_mg, 400.0) / 200.0)
    shortfall = mp["sleep_target_h"] - eff_sleep
    s.sleep_debt = float(np.clip(state.sleep_debt * (1.0 - mp["sleep_debt_decay_per_day"]) + max(shortfall, 0.0), 0.0, 8.0))
    # ---- training load (Banister-style fast component)
    s.training_load = state.training_load * mp["training_load_decay"] + day.exercise_load
    # ---- insulin sensitivity multiplier (training only; the sleep-debt effect is applied in the
    #      fast layer through the fitted sleep_debt_coef, see simulate.state_params)
    target = float(np.clip(1.0 + mp["training_load_si_gain"] * (s.training_load - 10.0), 0.8, 1.2))
    s.insulin_sensitivity = state.insulin_sensitivity + (target - state.insulin_sensitivity) / mp["si_recovery_tau_days"]
    # ---- body composition from energy balance
    intake = 4.0 * day.carbs_g + 9.0 * day.fat_g + 4.0 * day.protein_g + mp["alcohol_kcal_per_g"] * day.alcohol_g
    expend = mp["bmr_kcal_per_kg_lean"] * state.lean_mass + 400.0 + mp["activity_kcal_per_intensity_min"] * day.exercise_load * 10.0 / 6.0
    delta_kcal = intake - expend
    s.fat_mass = float(max(state.fat_mass + delta_kcal / mp["kcal_per_kg_fat"], 3.0))
    s.lean_mass = float(state.lean_mass + 0.0005 * day.exercise_load - 0.0002 * max(-delta_kcal, 0) / 100.0)
    # ---- HbA1c: dA/dt = k G (1 - A) - A / 120   (A as a fraction, daily Euler step)
    A = state.hba1c / 100.0
    dA = mp["hba1c_k"] * day.mean_glucose * (1.0 - A) - A / mp["hba1c_rbc_life_days"]
    s.hba1c = float(np.clip((A + dA) * 100.0, 3.5, 15.0))
    return s


def hba1c_steady_state(mean_glucose: float, mp: Optional[Dict[str, float]] = None) -> float:
    """Closed-form steady state of the A1c ODE (percent)."""
    mp = mp or medium_params()
    k, life = mp["hba1c_k"], mp["hba1c_rbc_life_days"]
    A = k * mean_glucose * life / (1.0 + k * mean_glucose * life)
    return 100.0 * A


def run_medium(state: State, week_days: List[DaySummary], n_days: int, sleep_debt_coef: float = 0.2) -> List[State]:
    """Loop a representative week for n_days. Returns the daily State list."""
    mp = medium_params()
    out = [state]
    s = state
    for d in range(n_days):
        s = daily_update(s, week_days[d % len(week_days)], mp, sleep_debt_coef)
        out.append(s)
    return out
