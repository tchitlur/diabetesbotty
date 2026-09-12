"""Batched simulation windows built from a patient's logged data.

A window = warm-up (hidden states settle from a steady-state guess while the
logged events of the preceding hours are replayed) + scored horizon. Every
inference component (fitter, residual model, drift monitor, validation) uses
these so their numbers are comparable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from backend.schema.state import State
from backend.engine import fast
from backend.engine.fast import IDX, NS, NU
from backend.engine.simulate import events_to_inputs, initial_vector
from backend.engine.medium import daily_update, summarize_day
from backend.data.store import PatientData

DT = 5


@dataclass
class WindowBatch:
    starts: List[datetime]          # scored-horizon start times
    x0: np.ndarray                  # (B, NS)
    inputs: np.ndarray              # (T, B, NU) covering warm-up + horizon
    obs: np.ndarray                 # (B, H+1) observed glucose over the horizon (NaN = missing)
    warm_steps: int
    horizon_steps: int
    sleep_debt: np.ndarray          # (B,) twin's sleep debt on the window's day
    insulin_sens: np.ndarray        # (B,) twin's medium-layer sensitivity (training component)
    g0: np.ndarray                  # (B,) observed glucose at horizon start

    @property
    def B(self) -> int:
        return self.x0.shape[0]


def twin_daily_states(pt: PatientData) -> Dict[str, State]:
    """The twin's own medium-layer trajectory computed from *logged* events and CGM."""
    if getattr(pt, "_twin_daily", None) is not None:
        return pt._twin_daily  # type: ignore[attr-defined]
    frame = pt.cgm.to_frame()
    frame["date"] = frame["time"].dt.date
    means = frame[frame["valid"]].groupby("date")["glucose"].mean()
    sds = frame[frame["valid"]].groupby("date")["glucose"].std()
    by_day: Dict[datetime.date, List] = {}
    for e in pt.events:
        by_day.setdefault(e.start.date(), []).append(e)
    days = sorted(set(frame["date"]))
    s = State(fat_mass=pt.meta.get("fat_mass_kg", 18.0), lean_mass=pt.meta.get("lean_mass_kg", 57.0), hba1c=7.0)
    out: Dict[str, State] = {}
    for d in days:
        summ = summarize_day(by_day.get(d, []), float(means.get(d, 130.0)), float(sds.get(d, 30.0) if not np.isnan(sds.get(d, 30.0)) else 30.0))
        s = daily_update(s, summ)
        out[d.isoformat()] = s
    pt._twin_daily = out  # type: ignore[attr-defined]
    return out


def observed_at(pt: PatientData, t: datetime, tol_min: int = 15) -> Optional[float]:
    """Nearest valid CGM value within tol_min of t."""
    times = pt.cgm.times
    i = int(times.searchsorted(pd.Timestamp(t)))
    best, bestd = None, tol_min + 1
    for j in range(max(0, i - 3), min(len(times), i + 4)):
        if pt.cgm.valid[j]:
            d = abs((times[j].to_pydatetime() - t).total_seconds()) / 60.0
            if d < bestd:
                best, bestd = float(pt.cgm.glucose[j]), d
    return best if bestd <= tol_min else None


def build_windows(pt: PatientData, starts: Sequence[datetime], params: Dict, warmup_min: int = 180,
                  horizon_min: int = 360, events: Optional[List] = None) -> WindowBatch:
    events = pt.events if events is None else events
    warm = warmup_min // DT
    hor = horizon_min // DT
    T = warm + hor
    daily = twin_daily_states(pt)
    xs, us, obs, sd, isens, g0s, kept = [], [], [], [], [], [], []
    ev_sorted = sorted(events, key=lambda e: e.start)
    ev_times = np.array([e.start for e in ev_sorted], dtype="datetime64[m]")
    for st in starts:
        t_warm = st - timedelta(minutes=warmup_min)
        g_warm = observed_at(pt, t_warm)
        g_start = observed_at(pt, st)
        if g_warm is None or g_start is None:
            continue
        day_state = daily.get((st - timedelta(days=1)).date().isoformat()) or State()
        lo = np.searchsorted(ev_times, np.datetime64(t_warm - timedelta(hours=8), "m"))
        hi = np.searchsorted(ev_times, np.datetime64(st + timedelta(minutes=horizon_min), "m"))
        window_events = ev_sorted[lo:hi]
        I0 = fast.steady_basal_insulin(params, g_warm) if g_warm > 60 else fast.steady_basal_insulin(params, 90.0)
        s0 = State(glucose=g_warm, plasma_insulin=float(I0), liver_glycogen=60.0)
        x0 = initial_vector(s0, params)[0]
        u = events_to_inputs(window_events, t_warm, T, DT, params)
        # observed glucose over horizon
        i0 = int(pt.cgm.times.searchsorted(pd.Timestamp(st)))
        seg = np.full(hor + 1, np.nan)
        n = min(hor + 1, len(pt.cgm.glucose) - i0)
        if n > 0:
            g = pt.cgm.glucose[i0:i0 + n].copy()
            g[~pt.cgm.valid[i0:i0 + n]] = np.nan
            seg[:n] = g
        xs.append(x0)
        us.append(u)
        obs.append(seg)
        sd.append(day_state.sleep_debt)
        isens.append(day_state.insulin_sensitivity)
        g0s.append(g_start)
        kept.append(st)
    if not xs:
        raise ValueError("no usable windows")
    return WindowBatch(starts=kept, x0=np.stack(xs), inputs=np.stack(us, axis=1), obs=np.stack(obs),
                       warm_steps=warm, horizon_steps=hor, sleep_debt=np.array(sd), insulin_sens=np.array(isens),
                       g0=np.array(g0s))


def batch_params(base: Dict, theta: Dict[str, np.ndarray | float], wb: WindowBatch, reps: int = 1) -> Dict:
    """Flat params for a batch of B*reps rows: fitted keys may be (reps,) arrays
    (one value per replicate block); medium modulators are per window."""
    p = dict(base)
    B = wb.B
    for k, v in theta.items():
        if np.ndim(v) == 0:
            p[k] = float(v)
        else:
            p[k] = np.repeat(np.asarray(v, dtype=float), B)  # block layout: rep-major
    debt = np.tile(np.minimum(wb.sleep_debt, 3.0), reps)
    isens = np.tile(wb.insulin_sens, reps)
    coef = p["sleep_debt_coef"]
    p["insulin_sensitivity"] = np.maximum(isens * (1.0 - coef * debt / 2.5), 0.3)
    p["sleep_debt"] = np.tile(wb.sleep_debt, reps)
    return p


def run_batch(wb: WindowBatch, p: Dict, reps: int = 1, substeps: int = 2) -> np.ndarray:
    """Integrate all windows (tiled `reps` times) and return glucose over the
    scored horizon as (reps*B, H+1)."""
    x0 = np.tile(wb.x0, (reps, 1))
    u = np.tile(wb.inputs, (1, reps, 1))
    # re-derive insulin-action states with each row's own sensitivity (steady-state consistency)
    si = (p["si_tod0"] if np.ndim(p["si_tod0"]) else p["si_tod0"]) * p["insulin_sensitivity"]
    I = x0[:, IDX["I"]]
    x0[:, IDX["x1"]] = p["SIT"] * si * I
    x0[:, IDX["x2"]] = p["SID"] * si * I
    x0[:, IDX["x3"]] = np.minimum(p["SIE"] * si * I, 0.95)
    x0[:, IDX["Q2"]] = x0[:, IDX["x1"]] * x0[:, IDX["Q1"]] / (p["k12"] + x0[:, IDX["x2"]])
    X = fast.integrate(x0, u, p, DT, substeps=substeps)
    G = fast.glucose_mgdl(X, p)             # (T+1, rows)
    return G[wb.warm_steps:, :].T           # (rows, H+1)


def pick_starts(pt: PatientData, day_lo: int, day_hi: int, per_day: Sequence[int], rng: np.random.Generator,
                n_max: Optional[int] = None) -> List[datetime]:
    start_day = pt.cgm.times[0].to_pydatetime().replace(hour=0, minute=0)
    out = []
    for d in range(day_lo, day_hi):
        base = start_day + timedelta(days=d)
        for h in per_day:
            out.append(base + timedelta(hours=int(h), minutes=int(rng.integers(0, 12)) * 5))
    if n_max is not None and len(out) > n_max:
        idx = rng.choice(len(out), size=n_max, replace=False)
        out = [out[i] for i in sorted(idx)]
    return out
