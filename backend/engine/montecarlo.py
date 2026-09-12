"""Monte Carlo over the fitted parameter posterior and input uncertainty.

200 trajectories are integrated in a single vectorised RK4 pass (batch axis),
which keeps a full 8-hour run well under the 2-second budget.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from backend.schema.state import State
from backend.schema.events import Event
from backend.engine import fast
from backend.engine.fast import IDX, UIDX, NS, NU
from backend.engine.params import FITTED_KEYS, FITTED_BOUNDS
from backend.engine.simulate import events_to_inputs, initial_vector, resolve_t0, state_params, pack_trajectories, Trajectories

DEFAULT_POSTERIOR_STD = {
    "si_tod0": 0.10, "si_tod1": 0.10, "si_tod2": 0.10, "carb_ratio": 0.08, "tau_carb": 6.0,
    "exercise_mult": 0.15, "alcohol_gain": 0.2, "basal_drift": 0.06, "sleep_debt_coef": 0.05,
}


@dataclass
class MCResult:
    t_min: np.ndarray
    times: List[str]
    median: np.ndarray
    p10: np.ndarray
    p90: np.ndarray
    p_hypo: float          # P(glucose < 70 within horizon)
    p_hyper: float         # P(glucose > 250 within horizon)
    tir: float
    energy: float
    min_glucose_samples: np.ndarray
    glucose_samples: np.ndarray            # (N, T+1)
    param_samples: Dict[str, np.ndarray]
    input_scales: Dict[str, np.ndarray]
    representative: Trajectories
    substances: Dict[str, np.ndarray] = field(default_factory=dict)
    p_dka: float = 0.0


def sample_posterior(posterior: Dict[str, Dict[str, float]], n: int, rng: np.random.Generator) -> Dict[str, np.ndarray]:
    out = {}
    for k in FITTED_KEYS:
        mean = posterior.get(k, {}).get("mean")
        std = posterior.get(k, {}).get("std", DEFAULT_POSTERIOR_STD[k])
        if mean is None:
            continue
        lo, hi = FITTED_BOUNDS[k]
        out[k] = np.clip(rng.normal(mean, std, size=n), lo, hi)
    return out


def run_monte_carlo(state: State, events: List[Event], params: Dict, posterior: Dict[str, Dict[str, float]],
                    horizon_min: int = 480, dt_min: int = 5, n: int = 200, t0=None,
                    hidden: Optional[np.ndarray] = None, glucose_std: float = 5.0, seed: int = 0) -> MCResult:
    rng = np.random.default_rng(seed)
    p = state_params(state, params)
    t0 = resolve_t0(events, t0)
    n_steps = max(int(horizon_min // dt_min), 1)

    # ---- parameter samples (posterior) as (n,) arrays
    pb = dict(p)
    samples = sample_posterior(posterior, n, rng)
    for k, v in samples.items():
        pb[k] = v
    for k in FITTED_KEYS:
        if k not in samples:
            pb[k] = np.full(n, float(p[k]))
    # ---- input uncertainty: scale each event's own channels by its uncertainty
    base = events_to_inputs(events, t0, n_steps, dt_min, p)  # (T, NU)
    inputs = np.repeat(base[:, None, :], n, axis=1)         # (T, n, NU)
    scales: Dict[str, np.ndarray] = {}
    for ch in ("carb", "alc", "caf", "bolus"):
        unc = _channel_uncertainty(events, ch)
        s = np.clip(rng.normal(1.0, unc, size=n), 0.3, 2.0) if unc > 0 else np.ones(n)
        scales[ch] = s
        inputs[:, :, UIDX[ch]] *= s[None, :]
    ex_unc = _channel_uncertainty(events, "ex")
    if ex_unc > 0:
        s = np.clip(rng.normal(1.0, ex_unc, size=n), 0.4, 1.6)
        scales["ex"] = s
        inputs[:, :, UIDX["ex_int"]] = np.clip(inputs[:, :, UIDX["ex_int"]] * s[None, :], 0, 1)
        inputs[:, :, UIDX["an_int"]] = np.clip(inputs[:, :, UIDX["an_int"]] * s[None, :], 0, 1)

    # ---- initial state uncertainty
    x0 = np.repeat(initial_vector(state, p, hidden), n, axis=0)
    x0[:, IDX["Q1"]] = np.maximum(x0[:, IDX["Q1"]] + rng.normal(0, glucose_std, n) / fast.MG_PER_MMOL * p["VG"], 0.05)
    x0[:, IDX["I"]] = np.maximum(x0[:, IDX["I"]] * np.clip(rng.normal(1.0, 0.15, n), 0.5, 1.5), 0.0)
    if hidden is None:
        # re-derive the insulin-action states for each sample's own sensitivity
        si = pb["si_tod0"] * p["insulin_sensitivity"]
        x0[:, IDX["x1"]] = pb["SIT"] * si * x0[:, IDX["I"]] if np.ndim(pb["SIT"]) else p["SIT"] * si * x0[:, IDX["I"]]
        x0[:, IDX["x2"]] = p["SID"] * si * x0[:, IDX["I"]]
        x0[:, IDX["x3"]] = np.minimum(p["SIE"] * si * x0[:, IDX["I"]], 0.95)
        x0[:, IDX["Q2"]] = x0[:, IDX["x1"]] * x0[:, IDX["Q1"]] / (p["k12"] + x0[:, IDX["x2"]])

    X = fast.integrate(x0, inputs, pb, dt_min, substeps=2)   # (T+1, n, NS)
    G = fast.glucose_mgdl(X, pb).T                             # (n, T+1)
    K = X[:, :, IDX["K"]].T
    t = np.arange(n_steps + 1) * dt_min
    median = np.median(G, axis=0)
    p10 = np.percentile(G, 10, axis=0)
    p90 = np.percentile(G, 90, axis=0)
    gmin = G.min(axis=1)
    p_hypo = float(np.mean(gmin < 70))
    p_hyper = float(np.mean(G.max(axis=1) > 250))
    p_dka = float(np.mean(np.any((K > 1.5) & (G > 250), axis=1)))
    tir = float(np.mean((G >= 70) & (G <= 180)))
    # representative trajectory: the sample whose min glucose is the median of mins
    rep_idx = int(np.argsort(gmin)[len(gmin) // 2])
    pr = {k: (v[rep_idx] if isinstance(v, np.ndarray) and v.shape == (n,) else v) for k, v in pb.items()}
    rep = pack_trajectories(X[:, rep_idx, :], state, pr, dt_min, t0)
    energy = float(np.mean(rep.series["energy_score"]))
    substances = {
        "insulin": np.median(X[:, :, IDX["I"]], axis=1),
        "alcohol": np.median(X[:, :, IDX["BAC"]], axis=1),
        "caffeine": np.median(X[:, :, IDX["C"]], axis=1),
        "ketones": np.median(K, axis=0),
    }
    times = rep.times()
    return MCResult(t_min=t, times=times, median=median, p10=p10, p90=p90, p_hypo=p_hypo, p_hyper=p_hyper,
                    tir=tir, energy=energy, min_glucose_samples=gmin, glucose_samples=G,
                    param_samples=samples, input_scales=scales, representative=rep, substances=substances, p_dka=p_dka)


def _channel_uncertainty(events: List[Event], ch: str) -> float:
    kinds = {"carb": ("meal",), "alc": ("alcohol",), "caf": ("caffeine",), "bolus": ("insulin",), "ex": ("exercise",)}[ch]
    u = [e.uncertainty for e in events if e.type in kinds]
    return float(np.mean(u)) if u else 0.0


def sensitivity_factors(mc: MCResult, top: int = 3) -> List[Dict[str, object]]:
    """Rank parameter/input samples by |correlation| with the minimum glucose
    across Monte Carlo samples: the top-3 factors for the explanation layer."""
    y = mc.min_glucose_samples
    rows = []
    cands: Dict[str, np.ndarray] = {}
    cands.update({f"param:{k}": v for k, v in mc.param_samples.items()})
    cands.update({f"input:{k}": v for k, v in mc.input_scales.items()})
    for name, v in cands.items():
        if np.std(v) < 1e-9 or np.std(y) < 1e-9:
            continue
        r = float(np.corrcoef(v, y)[0, 1])
        if np.isnan(r):
            continue
        rows.append({"name": name, "corr": r, "weight": abs(r)})
    rows.sort(key=lambda d: -d["weight"])
    return rows[:top]
