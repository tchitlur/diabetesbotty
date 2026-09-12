"""Explanation layer: confidence, data used / missing, and the top-3 factors
(from Monte Carlo sensitivity) attached to every card."""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from backend.schema.api import Factor
from backend.engine.montecarlo import MCResult, sensitivity_factors

FACTOR_NAMES = {
    "param:si_tod0": "overnight insulin sensitivity", "param:si_tod1": "daytime insulin sensitivity",
    "param:si_tod2": "evening insulin sensitivity", "param:carb_ratio": "carb absorption (bioavailability)",
    "param:tau_carb": "carb absorption speed", "param:exercise_mult": "your exercise response",
    "param:alcohol_gain": "your alcohol response (liver glucose output)", "param:basal_drift": "basal insulin balance",
    "param:sleep_debt_coef": "sleep-debt sensitivity", "input:carb": "carb estimate of the meal",
    "input:alc": "amount of alcohol", "input:caf": "caffeine dose", "input:bolus": "insulin dose", "input:ex": "exercise intensity",
}


def factors_from_mc(mc: MCResult, top: int = 3) -> List[Factor]:
    rows = sensitivity_factors(mc, top=top)
    out = []
    for r in rows:
        name = FACTOR_NAMES.get(r["name"], r["name"])
        direction = "raises" if r["corr"] > 0 else "lowers"
        out.append(Factor(name=name, effect=f"higher value {direction} the glucose low point", weight=round(float(r["weight"]), 3)))
    return out


def confidence_score(data_quality: float, posterior: Dict[str, Dict[str, float]], mc: Optional[MCResult] = None,
                     staleness_min: float = 0.0, drift_score: float = 1.0) -> float:
    """0-1: data quality x parameter certainty x forecast agreement x drift."""
    q = float(np.clip(data_quality, 0, 1))
    if posterior:
        rel = [v["std"] / max(abs(v["mean"]), 1e-3) for v in posterior.values()]
        cert = float(np.clip(1.0 - 0.5 * np.mean(rel), 0.3, 1.0))
    else:
        cert = 0.5
    agree = 1.0
    if mc is not None:
        spread = float(np.mean(mc.p90 - mc.p10))
        agree = float(np.clip(1.0 - spread / 150.0, 0.2, 1.0))
    stale = float(np.clip(1.0 - staleness_min / 60.0, 0.3, 1.0))
    drift = float(np.clip(1.5 - drift_score * 0.5, 0.4, 1.0))
    return round(float(np.clip(q * cert * agree * stale * drift, 0.0, 1.0)), 2)


def data_inventory(has_cgm: bool, staleness_min: float, has_fit: bool, has_residual: bool, events_24h: Dict[str, int],
                   ukf_ok: bool = True) -> Dict[str, List[str]]:
    used, missing = [], []
    if has_cgm and staleness_min <= 20:
        used.append(f"CGM (last reading {staleness_min:.0f} min ago)")
    else:
        missing.append("fresh CGM reading")
    used.append("personalised parameters (fit + 30-sample posterior)" if has_fit else "population parameters (no personal fit yet)")
    if not has_fit:
        missing.append("personal fit")
    if has_residual:
        used.append("residual model (ODE error correction)")
    if ukf_ok:
        used.append("state estimate (UKF over last 12 h)")
    for k in ("meal", "insulin", "alcohol", "caffeine", "exercise", "sleep"):
        n = events_24h.get(k, 0)
        if n:
            used.append(f"{n} logged {k} event{'s' if n > 1 else ''} (24 h)")
    if events_24h.get("sleep", 0) == 0:
        missing.append("last night's sleep")
    if events_24h.get("meal", 0) == 0:
        missing.append("meals today")
    missing.append("heart-rate / HRV feed (proxy in use)")
    return {"data_used": used, "data_missing": missing}
