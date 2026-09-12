"""Drift monitor: rolling daily RMSE of the combined (ODE + residual) 60-min
forecast. Flags when the RMSE has risen for 3+ consecutive days; the safety
layer escalates when it has been flagged for 5+ days.

Also records the day-by-day parameter drift the clinician page plots: the
fitter is re-run on a sliding 14-day window every 7 days (cheap, few
iterations) so the twin's parameters have a history.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from backend.schema.api import DriftStatus
from backend.data.store import load_patient, PatientData
from backend.inference.windows import pick_starts
from backend.inference.residual import build_dataset, load_residual_model, HORIZONS

LIVE_DAYS = (60, 90)


def daily_residual_log(pt: PatientData, params: Dict, model=None) -> List[Dict[str, float]]:
    rng = np.random.default_rng(3)
    starts = pick_starts(pt, LIVE_DAYS[0], LIVE_DAYS[1], per_day=list(range(0, 24, 3)), rng=rng)
    X, err, _ = build_dataset(pt, params, starts)
    # the dataset drops starts without CGM; recover their dates from the builder's kept list
    from backend.inference.windows import build_windows
    wb = build_windows(pt, starts, params, warmup_min=180, horizon_min=120)
    dates = [st.date().isoformat() for st in wb.starts]
    pred = model.predict_batch(X) if model is not None else np.zeros_like(err)
    df = pd.DataFrame({"date": dates, "e30": err[:, 0], "e60": err[:, 1], "e120": err[:, 2],
                       "c30": err[:, 0] - pred[:, 0], "c60": err[:, 1] - pred[:, 1], "c120": err[:, 2] - pred[:, 2]})
    rows = []
    for d, g in df.groupby("date"):
        rows.append({"date": d, "n": int(len(g)),
                     "rmse_ode_60": float(np.sqrt(np.nanmean(g["e60"] ** 2))),
                     "rmse_combined_60": float(np.sqrt(np.nanmean(g["c60"] ** 2))),
                     "rmse_combined_30": float(np.sqrt(np.nanmean(g["c30"] ** 2))),
                     "rmse_combined_120": float(np.sqrt(np.nanmean(g["c120"] ** 2))),
                     "bias_60": float(np.nanmean(g["c60"]))})
    return rows


def drift_status_from_log(log: List[Dict[str, float]], key: str = "rmse_combined_60") -> DriftStatus:
    if not log:
        return DriftStatus(score=0.0, flagged=False, since=None, days_flagged=0, history=[])
    vals = np.array([r[key] for r in log])
    # smooth with a 3-day rolling mean before testing for a monotone rise
    sm = pd.Series(vals).rolling(3, min_periods=1).mean().to_numpy()
    rise = 0
    since = None
    for i in range(1, len(sm)):
        if sm[i] > sm[i - 1] * 1.02:
            rise += 1
            if rise == 3:
                since = log[i - 2]["date"]
        else:
            rise = 0
            since = None
    flagged = rise >= 3
    ref = float(np.median(vals[: max(3, len(vals) // 2)]))
    score = float(sm[-1] / ref) if ref > 0 else 1.0
    days_flagged = max(rise - 2, 0) if flagged else 0
    return DriftStatus(score=round(score, 3), flagged=flagged, since=since, days_flagged=days_flagged,
                       history=[{"date": r["date"], "rmse": round(r[key], 2), "rmse_ode": round(r["rmse_ode_60"], 2)} for r in log])


def parameter_history(pt: PatientData, every_days: int = 7, window_days: int = 14) -> List[Dict[str, object]]:
    """Sliding-window refits (few iterations) for the clinician drift chart."""
    from backend.inference.fitter import Fitter
    from backend.engine.params import FITTED_KEYS
    out = []
    n_days = len(pt.daily)
    for end in range(window_days, n_days + 1, every_days):
        rng = np.random.default_rng(end)
        try:
            f = Fitter(pt, n_windows=24, seed=end)
            starts = pick_starts(pt, end - window_days, end, per_day=[2, 9, 15, 20], rng=rng, n_max=24)
            from backend.inference.windows import build_windows
            f.wb = build_windows(pt, starts, f.base, warmup_min=180, horizon_min=360)
            f.mask = ~np.isnan(f.wb.obs)
            f.n_obs = int(f.mask.sum())
            res = f.fit(max_nfev=8, verbose=False)
            row = {"day": end, "date": (pt.cgm.times[0].to_pydatetime() + timedelta(days=end - 1)).date().isoformat(),
                   "rmse": res["rmse_train_mgdl"]}
            row.update({k: res["params"][k]["mean"] for k in FITTED_KEYS})
            out.append(row)
        except ValueError:
            continue
    return out


def compute_drift(patient_id: str = "demo", save: bool = True, verbose: bool = True, with_history: bool = True) -> Dict[str, object]:
    from backend.inference.fitter import fitted_params
    pt = load_patient(patient_id)
    params = fitted_params(pt)
    model = load_residual_model(pt)
    log = daily_residual_log(pt, params, model)
    status = drift_status_from_log(log)
    out: Dict[str, object] = {"residual_log": log, "status": status.model_dump(),
                              "parameter_history": parameter_history(pt) if with_history else []}
    if save:
        (pt.path / "drift.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    if verbose:
        print(f"drift: score {status.score} flagged={status.flagged} since={status.since}  ({len(log)} live days, {len(out['parameter_history'])} refits)")
    return out
