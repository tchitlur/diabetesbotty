"""Per-patient parameter fitter.

Least squares (scipy `least_squares`, trust-region reflective with bounds) on
9 parameters -- insulin sensitivity in 3 time-of-day bins, carb ratio
(effective bioavailability), carb absorption time constant, exercise
sensitivity multiplier, alcohol suppression gain, basal drift and the
sleep-debt sensitivity coefficient -- against 6-hour windows of logged CGM
(days 0-59; days 60-89 are held out for validation). Everything else stays at
the population prior in params.yaml.

Posterior: 30 bootstrap resamples of the windows. Each resample is solved
with the Gauss-Newton linearisation at the optimum (the Jacobian is already
computed by finite differences in one batched pass), so the bootstrap adds
milliseconds rather than minutes. The whole fit runs in well under 60 s.

Usage:  python -m backend.inference.fitter --patient demo
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
from scipy.optimize import least_squares

from backend.engine.params import build_params, FITTED_KEYS, FITTED_BOUNDS
from backend.data.store import load_patient, PatientData
from backend.inference.windows import build_windows, batch_params, run_batch, pick_starts, WindowBatch

PRIOR_SD = {"si_tod0": 0.25, "si_tod1": 0.25, "si_tod2": 0.25, "carb_ratio": 0.15, "tau_carb": 12.0,
            "exercise_mult": 0.4, "alcohol_gain": 0.5, "basal_drift": 0.15, "sleep_debt_coef": 0.1}
PRIOR_WEIGHT = 3.0        # residual units (mg/dL) per prior sd
N_BOOT = 30
TRAIN_DAYS = (0, 60)


def _theta_to_dict(theta: np.ndarray) -> Dict[str, float]:
    return {k: float(v) for k, v in zip(FITTED_KEYS, theta)}


def event_anchored_starts(pt: PatientData, days, rng: np.random.Generator, n_alc: int = 8, n_ex: int = 8) -> List[datetime]:
    """Windows that start when a drink or a workout starts (the 3 h warm-up
    then covers the event itself and the 6 h horizon covers its after-effects),
    so alcohol_gain and exercise_mult are identifiable."""
    from datetime import timedelta
    day0 = pt.cgm.times[0].to_pydatetime().replace(hour=0, minute=0)
    lo, hi = day0 + timedelta(days=days[0]), day0 + timedelta(days=days[1])
    alc = [e.start + timedelta(hours=2) for e in pt.events if e.type == "alcohol" and lo <= e.start < hi]
    ex = [e.start for e in pt.events if e.type == "exercise" and lo <= e.start < hi]
    out: List[datetime] = []
    for lst, n in ((alc, n_alc), (ex, n_ex)):
        if lst:
            idx = rng.choice(len(lst), size=min(n, len(lst)), replace=False)
            out += [lst[i].replace(minute=(lst[i].minute // 5) * 5) for i in idx]
    return out


class Fitter:
    def __init__(self, pt: PatientData, n_windows: int = 48, seed: int = 0, params_override: Optional[Dict] = None):
        self.pt = pt
        self.rng = np.random.default_rng(seed)
        base = build_params({"body_weight_kg": pt.meta["body_weight_kg"],
                             "basal_u_per_h": pt.true_params.get("basal_u_per_h", 0.38),
                             "alcohol_widmark_r": pt.true_params.get("alcohol_widmark_r", 0.62)})
        if params_override:
            base.update(params_override)
        self.base = base
        starts = pick_starts(pt, TRAIN_DAYS[0], TRAIN_DAYS[1], per_day=[0, 7, 12, 18], rng=self.rng, n_max=n_windows)
        starts += event_anchored_starts(pt, TRAIN_DAYS, self.rng)
        self.wb: WindowBatch = build_windows(pt, starts, base, warmup_min=180, horizon_min=360)
        self.mask = ~np.isnan(self.wb.obs)
        self.n_obs = int(self.mask.sum())
        self.prior = np.array([base[k] for k in FITTED_KEYS])
        self.prior_sd = np.array([PRIOR_SD[k] for k in FITTED_KEYS])
        self.lo = np.array([FITTED_BOUNDS[k][0] for k in FITTED_KEYS])
        self.hi = np.array([FITTED_BOUNDS[k][1] for k in FITTED_KEYS])
        self.n_eval = 0

    # residual for one parameter vector (batched over windows)
    def residuals(self, theta: np.ndarray) -> np.ndarray:
        self.n_eval += 1
        p = batch_params(self.base, _theta_to_dict(theta), self.wb)
        G = run_batch(self.wb, p)
        r = (G - self.wb.obs)[self.mask]
        prior = PRIOR_WEIGHT * (theta - self.prior) / self.prior_sd
        return np.concatenate([r, prior])

    # finite-difference Jacobian with all perturbations in one batched integration
    def jacobian(self, theta: np.ndarray) -> np.ndarray:
        k = len(theta)
        eps = np.maximum(1e-3 * np.abs(theta), 1e-4) * (self.hi - self.lo) / (self.hi - self.lo)
        eps = np.maximum(eps, 0.01 * self.prior_sd)
        thetas = np.tile(theta, (k + 1, 1))
        for j in range(k):
            thetas[j + 1, j] = min(theta[j] + eps[j], self.hi[j])
            if thetas[j + 1, j] == theta[j]:
                thetas[j + 1, j] = theta[j] - eps[j]
        th = {key: thetas[:, i] for i, key in enumerate(FITTED_KEYS)}
        p = batch_params(self.base, th, self.wb, reps=k + 1)
        G = run_batch(self.wb, p, reps=k + 1)             # ((k+1)*B, H+1)
        B = self.wb.B
        G = G.reshape(k + 1, B, -1)
        base = G[0][self.mask]
        J = np.zeros((self.n_obs + k, k))
        for j in range(k):
            d = thetas[j + 1, j] - theta[j]
            J[:self.n_obs, j] = (G[j + 1][self.mask] - base) / d
        J[self.n_obs:, :] = np.diag(PRIOR_WEIGHT / self.prior_sd)
        return J

    def fit(self, max_nfev: int = 40, verbose: bool = True) -> Dict:
        tic = time.time()
        theta0 = self.prior.copy()
        res = least_squares(self.residuals, theta0, jac=self.jacobian, bounds=(self.lo, self.hi),
                            method="trf", x_scale=self.prior_sd, max_nfev=max_nfev, xtol=1e-6, ftol=1e-6, gtol=1e-8)
        theta = res.x
        r = res.fun[:self.n_obs]
        rmse = float(np.sqrt(np.mean(r ** 2)))
        J = self.jacobian(theta)
        # ---- bootstrap over windows (Gauss-Newton solve per resample)
        win_idx = np.repeat(np.arange(self.wb.B), self.mask.sum(axis=1))
        samples = []
        for b in range(N_BOOT):
            pick = self.rng.integers(0, self.wb.B, size=self.wb.B)
            rows = np.concatenate([np.where(win_idx == w)[0] for w in pick])
            Jb = np.vstack([J[rows], J[self.n_obs:]])
            rb = np.concatenate([res.fun[rows], res.fun[self.n_obs:]])
            delta, *_ = np.linalg.lstsq(Jb, -rb, rcond=None)
            samples.append(np.clip(theta + delta, self.lo, self.hi))
        S = np.array(samples)
        post = {k: {"mean": float(S[:, i].mean()), "std": float(max(S[:, i].std(), 0.05 * self.prior_sd[i])),
                    "point": float(theta[i]), "prior": float(self.prior[i])}
                for i, k in enumerate(FITTED_KEYS)}
        elapsed = time.time() - tic
        out = {
            "patient_id": self.pt.patient_id,
            "fitted_at": datetime.now().isoformat(timespec="seconds"),
            "params": post,
            "rmse_train_mgdl": rmse,
            "n_windows": int(self.wb.B),
            "n_obs": self.n_obs,
            "n_evaluations": self.n_eval,
            "elapsed_s": elapsed,
            "train_days": list(TRAIN_DAYS),
            "success": bool(res.success),
            "base": {k: self.base[k] for k in ("BW", "basal_u_per_h", "alcohol_widmark_r")},
        }
        if verbose:
            print(f"fit {self.pt.patient_id}: rmse {rmse:.1f} mg/dL over {self.n_obs} points, {self.n_eval} evals, {elapsed:.1f} s")
            for k in FITTED_KEYS:
                print(f"   {k:16s} {post[k]['mean']:8.4f} +- {post[k]['std']:.4f}   (prior {post[k]['prior']:.4f})")
        return out


def fitted_params(pt: PatientData) -> Dict:
    """Flat param dict for this patient using the posterior means (or priors if unfitted)."""
    over = {"body_weight_kg": pt.meta["body_weight_kg"],
            "basal_u_per_h": pt.true_params.get("basal_u_per_h", 0.38),
            "alcohol_widmark_r": pt.true_params.get("alcohol_widmark_r", 0.62),
            "carb_ratio_g_per_u": pt.true_params.get("carb_ratio_g_per_u", 10.0)}
    p = build_params(over)
    if pt.fit:
        for k in FITTED_KEYS:
            p[k] = pt.fit["params"][k]["mean"]
    return p


def posterior(pt: PatientData) -> Dict[str, Dict[str, float]]:
    return pt.fit["params"] if pt.fit else {}


def fit_patient(patient_id: str = "demo", save: bool = True, verbose: bool = True, n_windows: int = 48, max_nfev: int = 40) -> Dict:
    pt = load_patient(patient_id)
    f = Fitter(pt, n_windows=n_windows)
    out = f.fit(max_nfev=max_nfev, verbose=verbose)
    if save:
        (pt.path / "fit.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        if verbose:
            print("saved", pt.path / "fit.json")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient", default="demo")
    ap.add_argument("--windows", type=int, default=48)
    args = ap.parse_args()
    fit_patient(args.patient, n_windows=args.windows)
    # residual model + drift log are produced alongside the fit
    from backend.inference.residual import train_residual_model
    from backend.inference.drift import compute_drift
    train_residual_model(args.patient)
    compute_drift(args.patient)
    write_replay_suggestion(args.patient)


def write_replay_suggestion(patient_id: str = "demo") -> None:
    """Precompute which past drink night best shows the alcohol effect in the Replay tab
    (depends only on the fit; ~15 s), so the app never computes it at request time."""
    if patient_id != "demo":
        return
    from datetime import datetime
    from backend.api.twin import Twin
    from backend.config import DEMO_ANCHOR
    from backend.decision.replay import suggest_day
    tw = Twin(now=datetime.fromisoformat(DEMO_ANCHOR))   # synthetic dates: the app shifts them onto the wall clock itself
    tw._replay_suggest = None
    out = suggest_day(tw)
    (tw.pt.path / "replay_suggest.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("replay suggestion:", out["suggested"])


if __name__ == "__main__":
    main()
