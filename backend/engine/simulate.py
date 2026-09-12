"""simulate(): the one entry point every decision function loops over.

Converts a list of Events into piecewise-constant inputs, initialises the
Hovorka sub-states consistently with the observed State, integrates the
fast-layer ODE, and packs the result into Trajectories (one array per State
field plus summary statistics).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np

from backend.schema.state import State, ALL_FIELDS, FAST_FIELDS
from backend.schema.events import Event
from backend.engine import fast
from backend.engine.fast import IDX, UIDX, NS, NU
from backend.engine.params import build_params


@dataclass
class Trajectories:
    t_min: np.ndarray
    series: Dict[str, np.ndarray]
    t0: Optional[datetime] = None
    min_glucose: float = 0.0
    max_glucose: float = 0.0
    tir: float = 0.0
    hypo_minutes: float = 0.0
    hyper_minutes: float = 0.0
    flags: Dict[str, bool] = field(default_factory=dict)
    hidden_final: Optional[np.ndarray] = None   # full fast-layer vector at the end (NS,)
    X: Optional[np.ndarray] = None               # raw (T+1, NS) state matrix

    def final_state(self) -> State:
        s = State()
        for k in ALL_FIELDS:
            if k in self.series:
                setattr(s, k, float(self.series[k][-1]))
        return s

    def times(self) -> List[str]:
        if self.t0 is None:
            return [str(int(t)) for t in self.t_min]
        return [(self.t0 + timedelta(minutes=float(t))).isoformat(timespec="minutes") for t in self.t_min]

    def summarize(self) -> None:
        g = self.series["glucose"]
        self.min_glucose = float(np.min(g))
        self.max_glucose = float(np.max(g))
        n = len(g)
        self.tir = float(np.mean((g >= 70) & (g <= 180))) if n else 0.0
        dt = float(self.t_min[1] - self.t_min[0]) if n > 1 else 5.0
        self.hypo_minutes = float(np.sum(g < 70) * dt)
        self.hyper_minutes = float(np.sum(g > 250) * dt)
        k = self.series.get("ketones")
        if k is not None:
            self.flags["dka"] = bool(np.any((k > 1.5) & (g > 250)))


# ---------------------------------------------------------------- inputs

def _tod_bin(dt: datetime) -> int:
    return min(dt.hour // 8, 2)


def events_to_inputs(events: List[Event], t0: datetime, n_steps: int, dt_min: int, p: Dict) -> np.ndarray:
    """Build the (T, NU) input array at 1-minute resolution, averaged to dt_min blocks."""
    total_min = n_steps * dt_min
    u = np.zeros((total_min, NU))
    # time-of-day bin per minute
    minutes = np.arange(total_min)
    hours = ((t0.hour * 60 + t0.minute + minutes) // 60) % 24
    u[:, UIDX["tod"]] = np.minimum(hours // 8, 2)
    u[:, UIDX["tau_g"]] = 1.0   # multiplier on the (fitted) tau_carb; fat/fiber raise it

    tau_default = 1.0
    meal_windows = []  # (start_min, carbs, tau multiplier)

    for e in events:
        start = (e.start - t0).total_seconds() / 60.0
        if start >= total_min:
            continue
        if e.type == "meal":
            spread = max(e.duration_min, p["gut_meal_spread_min"])
            tau = 1.0 + p["gut_fat_tau_gain"] * e.fat_g / 50.0 + p["gut_fiber_tau_gain"] * e.fiber_g / 10.0
            _add_rate(u, UIDX["carb"], start, spread, e.carbs_g, total_min)
            meal_windows.append((start, e.carbs_g, tau))
            if e.insulin_units > 0:   # a meal that carries its own dose (the /compare page doses each person at their ratio)
                _add_rate(u, UIDX["bolus"], start, 1.0, e.insulin_units * 1000.0, total_min)
        elif e.type == "insulin":
            if e.insulin_kind == "basal":
                dur = max(e.duration_min, 60.0)
                _add_rate(u, UIDX["basal"], start, dur, e.insulin_units * 1000.0, total_min)
                _add_rate(u, UIDX["basal_override"], start, dur, dur, total_min)  # ->1 while active
            else:
                _add_rate(u, UIDX["bolus"], start, 1.0, e.insulin_units * 1000.0, total_min)
        elif e.type == "alcohol":
            spread = max(e.duration_min, 30.0)
            _add_rate(u, UIDX["alc"], start, spread, e.alcohol_g, total_min)
            if e.carbs_g > 0:
                _add_rate(u, UIDX["carb"], start, spread, e.carbs_g, total_min)
                meal_windows.append((start, e.carbs_g, tau_default))
        elif e.type == "caffeine":
            spread = max(e.duration_min, 5.0)
            _add_rate(u, UIDX["caf"], start, spread, e.caffeine_mg, total_min)
            if e.carbs_g > 0:
                _add_rate(u, UIDX["carb"], start, spread, e.carbs_g, total_min)
                meal_windows.append((start, e.carbs_g, tau_default))
            if e.insulin_units > 0:
                _add_rate(u, UIDX["bolus"], start, 1.0, e.insulin_units * 1000.0, total_min)
        elif e.type == "exercise":
            dur = max(e.duration_min, 30.0)
            kind = e.exercise_kind or "aerobic"
            inten = float(np.clip(e.intensity if e.intensity > 0 else 0.6, 0, 1))
            aer = inten if kind == "aerobic" else (0.5 * inten if kind == "mixed" else 0.15 * inten)
            an = inten if kind == "anaerobic" else (0.5 * inten if kind == "mixed" else 0.0)
            _set_level(u, UIDX["ex_int"], start, dur, aer, total_min)
            _set_level(u, UIDX["an_int"], start, dur, an, total_min)
            if dur > p["exercise_long_exercise_ketone_after_min"]:
                _set_level(u, UIDX["ex_long"], start + p["exercise_long_exercise_ketone_after_min"],
                           dur - p["exercise_long_exercise_ketone_after_min"], 1.0, total_min)
        elif e.type == "water":
            spread = max(e.duration_min, 5.0)
            _add_rate(u, UIDX["water"], start, spread, e.water_ml if e.water_ml > 0 else 300.0, total_min)
        elif e.type == "illness":
            dur = max(e.duration_min, 1440.0)
            _set_level(u, UIDX["ill"], start, dur, float(np.clip(e.severity, 0, 1)), total_min)
        elif e.type == "stress":
            dur = max(e.duration_min, 480.0)
            _set_level(u, UIDX["stress"], start, dur, float(np.clip(e.severity, 0, 1)), total_min)
        # sleep: medium layer only

    # carb-weighted absorption time constant over meals started in the last 3 h
    if meal_windows:
        num = np.zeros(total_min)
        den = np.zeros(total_min)
        for s, c, tau in meal_windows:
            if c <= 0:
                continue
            a = int(np.floor(max(s - 1, 0)))
            b = int(np.ceil(min(s + 180, total_min)))
            if b > a:
                num[a:b] += c * tau
                den[a:b] += c
        mask = den > 0
        u[mask, UIDX["tau_g"]] = num[mask] / den[mask]
    u[:, UIDX["basal_override"]] = (u[:, UIDX["basal_override"]] > 0).astype(float)

    # average to dt blocks (rates are per-minute so the mean preserves the total)
    ub = u.reshape(n_steps, dt_min, NU).mean(axis=1)
    ub[:, UIDX["tod"]] = np.round(ub[:, UIDX["tod"]])
    ub[:, UIDX["basal_override"]] = (ub[:, UIDX["basal_override"]] > 0.5).astype(float)
    return ub


def _add_rate(u: np.ndarray, col: int, start: float, dur: float, total: float, total_min: int) -> None:
    """Deliver `total` uniformly over [start, start+dur) minutes (clipped to horizon)."""
    if dur <= 0:
        dur = 1.0
    a = int(np.floor(max(start, 0)))
    b = int(np.ceil(min(start + dur, total_min)))
    if b <= a:
        return
    u[a:b, col] += total / dur


def _set_level(u: np.ndarray, col: int, start: float, dur: float, level: float, total_min: int) -> None:
    a = int(np.floor(max(start, 0)))
    b = int(np.ceil(min(start + dur, total_min)))
    if b <= a:
        return
    u[a:b, col] = np.maximum(u[a:b, col], level)


# ---------------------------------------------------------------- init/pack

def initial_vector(state: State, p: Dict, hidden: Optional[np.ndarray] = None) -> np.ndarray:
    if hidden is not None and len(hidden) == NS:
        x = np.array(hidden, dtype=float).reshape(1, NS)
        # observed fast fields override the carried-over hidden vector
        x[0, IDX["Q1"]] = state.glucose / fast.MG_PER_MMOL * p["VG"]
        x[0, IDX["I"]] = state.plasma_insulin
        return x
    si = p["si_tod0"] * p["insulin_sensitivity"]
    x = fast.steady_state_init(np.array([state.glucose]), np.array([state.plasma_insulin]), p, si=si)
    x[0, IDX["D1"]] = state.gut_carbs_1
    x[0, IDX["D2"]] = state.gut_carbs_2
    x[0, IDX["L"]] = state.liver_glycogen
    x[0, IDX["M"]] = state.muscle_glycogen
    x[0, IDX["BAC"]] = state.blood_alcohol
    x[0, IDX["C"]] = state.caffeine
    x[0, IDX["K"]] = state.ketones
    x[0, IDX["H"]] = state.hydration
    return x


def pack_trajectories(X: np.ndarray, state: State, p: Dict, dt_min: int, t0: Optional[datetime]) -> Trajectories:
    """X: (T+1, NS) -> Trajectories."""
    T1 = X.shape[0]
    t = np.arange(T1) * dt_min
    series: Dict[str, np.ndarray] = {}
    series["glucose"] = fast.glucose_mgdl(X, p)
    series["plasma_insulin"] = X[:, IDX["I"]]
    series["gut_carbs_1"] = X[:, IDX["D1"]]
    series["gut_carbs_2"] = X[:, IDX["D2"]]
    series["liver_glycogen"] = X[:, IDX["L"]]
    series["muscle_glycogen"] = X[:, IDX["M"]]
    series["blood_alcohol"] = X[:, IDX["BAC"]]
    series["caffeine"] = X[:, IDX["C"]]
    series["ketones"] = X[:, IDX["K"]]
    series["hydration"] = X[:, IDX["H"]]
    series["energy_score"] = fast.energy_score(X, p)
    for k in ALL_FIELDS:
        if k not in FAST_FIELDS:
            series[k] = np.full(T1, float(getattr(state, k)))
    # extra diagnostics
    series["_ex_effect"] = X[:, IDX["ex"]]
    series["_hangover"] = X[:, IDX["hang"]]
    tr = Trajectories(t_min=t, series=series, t0=t0, hidden_final=X[-1].copy(), X=X)
    tr.summarize()
    return tr


def resolve_t0(events: List[Event], t0) -> datetime:
    if t0 is not None:
        return datetime.fromisoformat(t0) if isinstance(t0, str) else t0
    if events:
        return min(e.start for e in events)
    return datetime.now().replace(second=0, microsecond=0)


def state_params(state: State, params: Dict) -> Dict:
    """Merge State's medium-layer modulators into the flat param dict."""
    p = dict(params) if params else build_params()
    if "VG" not in p:
        p = build_params(p)
    p["insulin_sensitivity"] = float(state.insulin_sensitivity) * (1.0 - float(p.get("sleep_debt_coef", 0.2)) * min(float(state.sleep_debt), 3.0) / 2.5)
    p["insulin_sensitivity"] = max(p["insulin_sensitivity"], 0.3)
    p["sleep_debt"] = float(state.sleep_debt)
    return p


def simulate(state: State, events: List[Event], params: dict, horizon_min: int, dt_min: int = 5,
             t0=None, hidden: Optional[np.ndarray] = None, method: str = "rk4", substeps: int = 2) -> Trajectories:
    """Simulate the fast layer forward from `state` for `horizon_min` minutes.

    params: flat dict from `build_params` (or overrides; will be built if needed).
    t0: datetime/ISO string the state refers to (default: earliest event or now).
    hidden: optional full NS vector carried over from a previous Trajectories.hidden_final.
    method: "rk4" (vectorised, default) or "solve_ivp" (scipy reference).
    """
    p = state_params(state, params)
    t0 = resolve_t0(events, t0)
    n_steps = max(int(horizon_min // dt_min), 1)
    inputs = events_to_inputs(events, t0, n_steps, dt_min, p)
    x0 = initial_vector(state, p, hidden)
    if method == "solve_ivp":
        X = fast.integrate_solve_ivp(x0, inputs, p, dt_min)
    else:
        X = fast.integrate(x0, inputs, p, dt_min, substeps=substeps)
    return pack_trajectories(X[:, 0, :], state, p, dt_min, t0)
