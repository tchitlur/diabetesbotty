"""Residual model: gradient boosting that predicts the personalised ODE's
forecast error at 30 / 60 / 120 minutes from simple features. The combined
forecast is ODE + residual.

LightGBM is used when importable; otherwise sklearn's
HistGradientBoostingRegressor with the same feature set.

Features: hour, weekday, recent CGM slope, last-meal macros and age, last
night's sleep, and an HRV proxy. There is no HRV sensor in the synthetic
data, so the proxy is derived from logged sleep debt, alcohol in the last 12 h
and stress events (a real HRV feed would replace `hrv_proxy` in one line).
"""
from __future__ import annotations

import json
import pickle
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.schema.state import State
from backend.data.store import load_patient, PatientData
from backend.inference.windows import build_windows, batch_params, run_batch, pick_starts, twin_daily_states, WindowBatch

HORIZONS = (30, 60, 120)
FEATURES = ["hour", "weekday", "slope_15", "g0", "carbs_last", "fat_last", "protein_last", "min_since_meal",
            "bolus_last", "min_since_bolus", "sleep_last_night", "sleep_debt", "hrv_proxy", "alcohol_12h", "exercise_6h", "caffeine_6h"]
TRAIN_DAYS = (0, 60)
HOLDOUT_DAYS = (60, 90)


def _make_model():
    try:
        import lightgbm as lgb
        return lgb.LGBMRegressor(n_estimators=250, learning_rate=0.04, num_leaves=15, min_child_samples=25,
                                 subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1), "lightgbm"
    except Exception:
        from sklearn.ensemble import HistGradientBoostingRegressor
        return HistGradientBoostingRegressor(max_iter=250, learning_rate=0.04, max_leaf_nodes=15, min_samples_leaf=25, l2_regularization=1.0), "sklearn_hgb"


def features_at(pt: PatientData, t: datetime, g0: float, slope: float) -> Dict[str, float]:
    ev = [e for e in pt.events if t - timedelta(hours=14) <= e.start <= t]
    meals = [e for e in ev if e.type == "meal"]
    boluses = [e for e in ev if e.type == "insulin" and e.insulin_kind == "bolus"]
    last_meal = meals[-1] if meals else None
    last_bolus = boluses[-1] if boluses else None
    daily = twin_daily_states(pt)
    ds = daily.get((t - timedelta(days=1)).date().isoformat()) or State()
    sleep_ev = [e for e in pt.events if e.type == "sleep" and t - timedelta(hours=30) <= e.start <= t]
    sleep_last = float(sleep_ev[-1].sleep_hours) if sleep_ev else 7.5
    alc12 = sum(e.alcohol_g for e in ev if e.type == "alcohol" and e.start >= t - timedelta(hours=12))
    ex6 = sum((e.intensity or 0.6) * max(e.duration_min, 30) for e in ev if e.type == "exercise" and e.start >= t - timedelta(hours=6))
    caf6 = sum(e.caffeine_mg for e in ev if e.type == "caffeine" and e.start >= t - timedelta(hours=6))
    stress = any(e.type == "stress" and e.start <= t <= e.start + timedelta(minutes=e.duration_min or 480) for e in ev)
    hrv = 65.0 - 4.0 * ds.sleep_debt - 0.15 * alc12 - (8.0 if stress else 0.0) + 2.0 * (sleep_last - 7.0)
    return {
        "hour": t.hour + t.minute / 60.0, "weekday": float(t.weekday()), "slope_15": slope, "g0": g0,
        "carbs_last": last_meal.carbs_g if last_meal else 0.0, "fat_last": last_meal.fat_g if last_meal else 0.0,
        "protein_last": last_meal.protein_g if last_meal else 0.0,
        "min_since_meal": (t - last_meal.start).total_seconds() / 60.0 if last_meal else 900.0,
        "bolus_last": last_bolus.insulin_units if last_bolus else 0.0,
        "min_since_bolus": (t - last_bolus.start).total_seconds() / 60.0 if last_bolus else 900.0,
        "sleep_last_night": sleep_last, "sleep_debt": ds.sleep_debt, "hrv_proxy": hrv,
        "alcohol_12h": alc12, "exercise_6h": ex6, "caffeine_6h": caf6,
    }


def _slope_at(pt: PatientData, t: datetime) -> float:
    i = int(pt.cgm.times.searchsorted(pd.Timestamp(t)))
    i = min(max(i, 3), len(pt.cgm.glucose) - 1)
    g = pt.cgm.glucose[i - 3:i + 1]
    v = pt.cgm.valid[i - 3:i + 1]
    if v.sum() >= 2:
        x = np.arange(4)[v] * 5.0
        return float(np.polyfit(x, g[v], 1)[0])
    return 0.0


def ode_forecast_errors(pt: PatientData, params: Dict, starts: List[datetime]) -> Tuple[WindowBatch, np.ndarray, np.ndarray]:
    """Run the personalised ODE from each start (with warm-up) and return
    (batch, ode_glucose (B, 25), errors (B, 3) at 30/60/120 min)."""
    wb = build_windows(pt, starts, params, warmup_min=180, horizon_min=120)
    p = batch_params(params, {}, wb)
    G = run_batch(wb, p)
    # anchor the forecast to the observed starting glucose (as the live twin does through the UKF)
    G = G - G[:, [0]] + wb.g0[:, None]
    steps = [h // 5 for h in HORIZONS]
    err = wb.obs[:, steps] - G[:, steps]
    return wb, G, err


def build_dataset(pt: PatientData, params: Dict, starts: List[datetime]) -> Tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    wb, G, err = ode_forecast_errors(pt, params, starts)
    rows = [features_at(pt, st, float(g0), _slope_at(pt, st)) for st, g0 in zip(wb.starts, wb.g0)]
    X = pd.DataFrame(rows)[FEATURES]
    return X, err, G


class ResidualModel:
    def __init__(self):
        self.models: Dict[int, object] = {}
        self.backend = "none"
        self.metrics: Dict[str, float] = {}

    def fit(self, X: pd.DataFrame, err: np.ndarray) -> None:
        for i, h in enumerate(HORIZONS):
            y = err[:, i]
            ok = ~np.isnan(y)
            m, self.backend = _make_model()
            m.fit(X[ok], y[ok])
            self.models[h] = m

    def predict(self, feats: Dict[str, float]) -> Dict[int, float]:
        X = pd.DataFrame([feats])[FEATURES]
        return {h: float(np.clip(m.predict(X)[0], -80, 80)) for h, m in self.models.items()}

    def predict_batch(self, X: pd.DataFrame) -> np.ndarray:
        return np.stack([self.models[h].predict(X) for h in HORIZONS], axis=1)

    def correction_curve(self, feats: Dict[str, float], t_min: np.ndarray) -> np.ndarray:
        """Piecewise-linear residual over a forecast horizon: 0 at t=0, the
        predicted residuals at 30/60/120 min, decaying back to 0 by 240 min."""
        r = self.predict(feats)
        knots_t = np.array([0.0, 30.0, 60.0, 120.0, 240.0])
        knots_v = np.array([0.0, r[30], r[60], r[120], 0.0])
        return np.interp(t_min, knots_t, knots_v, right=0.0)


def train_residual_model(patient_id: str = "demo", save: bool = True, verbose: bool = True) -> Dict[str, float]:
    from backend.inference.fitter import fitted_params
    pt = load_patient(patient_id)
    params = fitted_params(pt)
    rng = np.random.default_rng(1)
    tic = time.time()
    starts_tr = pick_starts(pt, TRAIN_DAYS[0], TRAIN_DAYS[1], per_day=list(range(0, 24, 2)), rng=rng)
    X, err, _ = build_dataset(pt, params, starts_tr)
    model = ResidualModel()
    model.fit(X, err)
    starts_ho = pick_starts(pt, HOLDOUT_DAYS[0], HOLDOUT_DAYS[1], per_day=list(range(1, 24, 2)), rng=rng)
    Xh, errh, _ = build_dataset(pt, params, starts_ho)
    pred = model.predict_batch(Xh)
    metrics: Dict[str, float] = {"backend": model.backend, "n_train": int(len(X)), "n_holdout": int(len(Xh)), "elapsed_s": time.time() - tic}
    for i, h in enumerate(HORIZONS):
        ok = ~np.isnan(errh[:, i])
        metrics[f"rmse_ode_{h}"] = float(np.sqrt(np.mean(errh[ok, i] ** 2)))
        metrics[f"rmse_combined_{h}"] = float(np.sqrt(np.mean((errh[ok, i] - pred[ok, i]) ** 2)))
    model.metrics = metrics
    if save:
        with open(pt.path / "residual.pkl", "wb") as f:
            pickle.dump(model, f)
        (pt.path / "residual_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    if verbose:
        print(f"residual model ({model.backend}): " + ", ".join(f"{h}min ODE {metrics[f'rmse_ode_{h}']:.1f} -> +res {metrics[f'rmse_combined_{h}']:.1f}" for h in HORIZONS) + f"  ({metrics['elapsed_s']:.1f} s)")
    return metrics


def load_residual_model(pt: PatientData) -> Optional[ResidualModel]:
    path = pt.path / "residual.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)
