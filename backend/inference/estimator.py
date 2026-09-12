"""Unscented Kalman filter over the fast-layer ODE.

A minimal, self-contained UKF (Merwe scaled sigma points) in which all 2n+1
sigma points are propagated through the vectorised RK4 in a single batched
call, so filtering the last 12 hours of CGM takes well under a second.
`filterpy` is installed and its sigma-point weights are used when available;
its per-point propagation loop is not, for speed.

Output: mean and covariance of the hidden fast-layer state *now*, exposed as
`State` values with a standard deviation per fast-layer field.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.schema.state import State, FAST_FIELDS
from backend.engine import fast
from backend.engine.fast import IDX, NS, NU
from backend.engine.simulate import events_to_inputs, initial_vector, pack_trajectories
from backend.data.store import PatientData
from backend.inference.windows import twin_daily_states

DT = 5
CGM_SD = 8.0


def _merwe_weights(n: int, alpha: float = 0.3, beta: float = 2.0, kappa: float = 0.0) -> Tuple[np.ndarray, np.ndarray, float]:
    try:
        from filterpy.kalman import MerweScaledSigmaPoints
        sp = MerweScaledSigmaPoints(n, alpha=alpha, beta=beta, kappa=kappa)
        return sp.Wm, sp.Wc, alpha ** 2 * (n + kappa) - n
    except Exception:  # pragma: no cover
        lam = alpha ** 2 * (n + kappa) - n
        Wm = np.full(2 * n + 1, 0.5 / (n + lam))
        Wc = Wm.copy()
        Wm[0] = lam / (n + lam)
        Wc[0] = lam / (n + lam) + (1 - alpha ** 2 + beta)
        return Wm, Wc, lam


@dataclass
class UKFResult:
    mean: np.ndarray                 # (NS,)
    cov: np.ndarray                  # (NS, NS)
    times: List[datetime]
    filtered_glucose: np.ndarray
    observed: np.ndarray
    innovation_rmse: float
    as_of: datetime

    def state(self, template: Optional[State] = None) -> State:
        s = (template or State()).copy()
        tr_vals = _series_from_vector(self.mean, self.p)
        for k, v in tr_vals.items():
            setattr(s, k, float(v))
        return s

    def std_fast(self) -> Dict[str, float]:
        sd = np.sqrt(np.maximum(np.diag(self.cov), 0.0))
        out = {
            "glucose": float(sd[IDX["Q1"]] / self.p["VG"] * fast.MG_PER_MMOL),
            "plasma_insulin": float(sd[IDX["I"]]),
            "gut_carbs_1": float(sd[IDX["D1"]]),
            "gut_carbs_2": float(sd[IDX["D2"]]),
            "liver_glycogen": float(sd[IDX["L"]]),
            "muscle_glycogen": float(sd[IDX["M"]]),
            "blood_alcohol": float(sd[IDX["BAC"]]),
            "caffeine": float(sd[IDX["C"]]),
            "ketones": float(sd[IDX["K"]]),
            "hydration": float(sd[IDX["H"]]),
        }
        out["energy_score"] = float(0.3 * out["glucose"])
        return out


def _series_from_vector(x: np.ndarray, p: Dict) -> Dict[str, float]:
    X = x[None, :]
    return {
        "glucose": fast.glucose_mgdl(X, p)[0], "plasma_insulin": x[IDX["I"]], "gut_carbs_1": x[IDX["D1"]],
        "gut_carbs_2": x[IDX["D2"]], "liver_glycogen": x[IDX["L"]], "muscle_glycogen": x[IDX["M"]],
        "blood_alcohol": x[IDX["BAC"]], "caffeine": x[IDX["C"]], "ketones": x[IDX["K"]], "hydration": x[IDX["H"]],
        "energy_score": fast.energy_score(X, p)[0],
    }


def _process_noise(p: Dict) -> np.ndarray:
    q = np.full(NS, 1e-6)
    q[IDX["Q1"]] = (3.0 / fast.MG_PER_MMOL * p["VG"]) ** 2     # ~3 mg/dL per step unmodelled
    q[IDX["Q2"]] = (1.0 / fast.MG_PER_MMOL * p["VG"]) ** 2
    q[IDX["I"]] = 0.3 ** 2
    q[IDX["S1"]] = q[IDX["S2"]] = 0.05 ** 2
    q[IDX["x1"]] = 1e-6; q[IDX["x2"]] = 1e-7; q[IDX["x3"]] = 1e-4
    q[IDX["D1"]] = q[IDX["D2"]] = 1.0 ** 2
    q[IDX["L"]] = 0.5 ** 2; q[IDX["M"]] = 0.5 ** 2
    q[IDX["BAC"]] = 0.002 ** 2; q[IDX["Agut"]] = 0.5 ** 2
    q[IDX["C"]] = 3.0 ** 2; q[IDX["Cgut"]] = 3.0 ** 2
    q[IDX["K"]] = 0.01 ** 2; q[IDX["H"]] = 0.005 ** 2
    q[IDX["ex"]] = 0.01 ** 2; q[IDX["anaer"]] = 0.01 ** 2; q[IDX["hang"]] = 0.002 ** 2
    return np.diag(q)


def run_ukf(pt: PatientData, p: Dict, hours: float = 12.0, end: Optional[datetime] = None, alpha: float = 0.3) -> UKFResult:
    end = end or pt.now
    start = end - timedelta(hours=hours)
    n_steps = int(hours * 60 // DT)
    # inputs from logged events (8 h of context before the window for insulin/carbs on board)
    events = [e for e in pt.events if start - timedelta(hours=8) <= e.start < end]
    day_state = twin_daily_states(pt).get((start - timedelta(days=1)).date().isoformat()) or State()
    p = dict(p)
    p["insulin_sensitivity"] = max(float(day_state.insulin_sensitivity) * (1.0 - p["sleep_debt_coef"] * min(day_state.sleep_debt, 3.0) / 2.5), 0.3)
    p["sleep_debt"] = float(day_state.sleep_debt)
    u_all = events_to_inputs(events, start, n_steps, DT, p)
    # observations on the grid
    times = pd.date_range(start, periods=n_steps + 1, freq=f"{DT}min")
    idx = pt.cgm.times.searchsorted(times)
    obs = np.full(n_steps + 1, np.nan)
    for i, j in enumerate(idx):
        if j < len(pt.cgm.times) and abs((pt.cgm.times[j] - times[i]).total_seconds()) < 150 and pt.cgm.valid[j]:
            obs[i] = pt.cgm.glucose[j]
    # initial mean: steady state at the first valid observation
    g0 = next((g for g in obs if not np.isnan(g)), 120.0)
    s0 = State(glucose=float(g0), plasma_insulin=float(fast.steady_basal_insulin(p, float(g0) if g0 > 60 else 90.0)), liver_glycogen=60.0)
    x = initial_vector(s0, p)[0]
    P = _process_noise(p) * 25.0
    P[IDX["Q1"], IDX["Q1"]] = (15.0 / fast.MG_PER_MMOL * p["VG"]) ** 2
    P[IDX["L"], IDX["L"]] = 20.0 ** 2
    P[IDX["M"], IDX["M"]] = 40.0 ** 2
    Q = _process_noise(p)
    R = CGM_SD ** 2
    n = NS
    Wm, Wc, lam = _merwe_weights(n, alpha=alpha)
    H = np.zeros(n)
    H[IDX["Q1"]] = fast.MG_PER_MMOL / p["VG"]   # linear measurement of glucose
    filt = np.zeros(n_steps + 1)
    innov = []
    filt[0] = float(H @ x)
    for k in range(n_steps):
        # ---- sigma points
        try:
            S = np.linalg.cholesky((n + lam) * (P + 1e-12 * np.eye(n)))
        except np.linalg.LinAlgError:
            P = np.diag(np.maximum(np.diag(P), 1e-10))
            S = np.linalg.cholesky((n + lam) * P)
        sig = np.vstack([x[None, :], x[None, :] + S.T, x[None, :] - S.T])   # (2n+1, n)
        sig = fast.clamp(sig, p)
        # ---- propagate all sigma points in one batched RK4 step
        u = np.broadcast_to(u_all[k][None, :], (sig.shape[0], NU))
        prop = fast.integrate(sig, u[None, :, :], p, DT, substeps=2)[-1]   # (2n+1, n)
        x_pred = Wm @ prop
        d = prop - x_pred
        P_pred = (d.T * Wc) @ d + Q
        # ---- update with CGM if available
        z = obs[k + 1]
        if not np.isnan(z):
            z_sig = prop @ H
            z_pred = Wm @ z_sig
            dz = z_sig - z_pred
            Pzz = float(np.sum(Wc * dz * dz)) + R
            Pxz = (d.T * Wc) @ dz
            K = Pxz / Pzz
            innov.append(z - z_pred)
            x = x_pred + K * (z - z_pred)
            P = P_pred - np.outer(K, K) * Pzz
        else:
            x, P = x_pred, P_pred
        x = fast.clamp(x[None, :], p)[0]
        P = 0.5 * (P + P.T)
        filt[k + 1] = float(H @ x)
    res = UKFResult(mean=x, cov=P, times=[t.to_pydatetime() for t in times], filtered_glucose=filt, observed=obs,
                    innovation_rmse=float(np.sqrt(np.mean(np.square(innov)))) if innov else 0.0, as_of=end)
    res.p = p  # type: ignore[attr-defined]
    return res
