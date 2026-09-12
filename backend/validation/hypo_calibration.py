"""Validation 3: hypo calibration. Predicted P(glucose < 70 within 4 h) from
Monte Carlo at many held-out anchor times vs the observed rate, binned.

Writes validation/plots/hypo_calibration.png and validation/hypo_calibration.json.
Run: python -m backend.validation.hypo_calibration [--patients N] [--per-day K]
"""
from __future__ import annotations

import argparse
import json
from datetime import timedelta
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backend.config import PLOTS_DIR, VALIDATION_DIR
from backend.schema.state import State
from backend.engine import fast
from backend.engine.fast import IDX
from backend.engine.montecarlo import run_monte_carlo
from backend.data.store import load_patient, list_cohort
from backend.inference.fitter import Fitter, fitted_params, posterior
from backend.inference.estimator import run_ukf
from backend.inference.windows import pick_starts, observed_at, twin_daily_states
from backend.inference.residual import HOLDOUT_DAYS

HORIZON_MIN = 240


def predictions_for(pid: str, per_day: int, seed: int) -> List[Dict[str, float]]:
    pt = load_patient(pid)
    if pt.fit is None:
        pt.fit = Fitter(pt, n_windows=48, seed=0).fit(max_nfev=40, verbose=False)
    params = fitted_params(pt)
    post = posterior(pt)
    rng = np.random.default_rng(seed)
    hours = sorted(rng.choice(24, size=per_day, replace=False).tolist())
    starts = pick_starts(pt, HOLDOUT_DAYS[0], HOLDOUT_DAYS[1], per_day=hours, rng=rng)
    daily = twin_daily_states(pt)
    out = []
    for st in starts:
        g0 = observed_at(pt, st)
        if g0 is None:
            continue
        # observed outcome over the horizon
        i0 = int(pt.cgm.times.searchsorted(pd.Timestamp(st)))
        i1 = min(i0 + HORIZON_MIN // 5 + 1, len(pt.cgm.glucose))
        seg = pt.cgm.glucose[i0:i1]
        valid = pt.cgm.valid[i0:i1]
        if valid.sum() < 0.6 * (i1 - i0):
            continue
        observed = bool(np.any(seg[valid] < 70))
        # twin state at the anchor: UKF over the preceding 6 h
        u = run_ukf(pt, params, hours=6.0, end=st)
        ms = daily.get((st - timedelta(days=1)).date().isoformat()) or State()
        s = u.state(template=ms)
        events = [e for e in pt.events if st - timedelta(hours=8) <= e.start < st + timedelta(minutes=HORIZON_MIN)]
        mc = run_monte_carlo(s, events, params, post, horizon_min=HORIZON_MIN, n=150, t0=st, hidden=u.mean, seed=int(rng.integers(0, 10 ** 6)))
        out.append({"patient": pid, "start": st.isoformat(timespec="minutes"), "g0": float(g0), "p_hypo": float(mc.p_hypo), "observed": observed})
    return out


def main(n_patients: int = 4, per_day: int = 6) -> Dict[str, object]:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    ids = ["demo"] + list_cohort()[: max(n_patients - 1, 0)]
    rows: List[Dict[str, float]] = []
    for k, pid in enumerate(ids):
        r = predictions_for(pid, per_day, seed=100 + k)
        rows += r
        print(f"  {pid}: {len(r)} anchors, mean predicted {np.mean([x['p_hypo'] for x in r]):.2f}, observed rate {np.mean([x['observed'] for x in r]):.2f}")
    p = np.array([r["p_hypo"] for r in rows])
    y = np.array([r["observed"] for r in rows], dtype=float)
    edges = np.array([0.0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 0.9, 1.0001])
    bins = []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (p >= a) & (p < b)
        if m.sum() >= 5:
            bins.append({"lo": float(a), "hi": float(b), "n": int(m.sum()), "pred": float(p[m].mean()), "obs": float(y[m].mean())})
    brier = float(np.mean((p - y) ** 2))
    base = float(np.mean((y.mean() - y) ** 2))
    ece = float(sum(b["n"] * abs(b["pred"] - b["obs"]) for b in bins) / max(sum(b["n"] for b in bins), 1))
    # AUC (rank-based)
    order = np.argsort(p)
    ranks = np.empty(len(p)); ranks[order] = np.arange(1, len(p) + 1)
    n1, n0 = y.sum(), len(y) - y.sum()
    auc = float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 > 0 and n0 > 0 else float("nan")
    fig, ax = plt.subplots(figsize=(6.5, 6))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect calibration")
    ax.plot([b["pred"] for b in bins], [b["obs"] for b in bins], "o-", color="tab:red", label="twin (Monte Carlo)")
    for b in bins:
        ax.annotate(f"n={b['n']}", (b["pred"], b["obs"]), textcoords="offset points", xytext=(6, -10), fontsize=8)
    ax.set_xlabel(f"predicted P(glucose < 70 within {HORIZON_MIN // 60} h)")
    ax.set_ylabel("observed fraction of anchors with a low")
    ax.set_title(f"Hypo calibration on held-out days ({len(rows)} anchors, {len(ids)} patients)\nBrier {brier:.3f} (climatology {base:.3f}), ECE {ece:.3f}, AUC {auc:.2f}")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "hypo_calibration.png", dpi=110)
    out = {"n_anchors": len(rows), "patients": ids, "bins": bins, "brier": brier, "brier_climatology": base, "ece": ece, "auc": auc,
           "base_rate": float(y.mean()), "rows": rows}
    (VALIDATION_DIR / "hypo_calibration.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"Brier {brier:.3f} vs climatology {base:.3f}; ECE {ece:.3f}; AUC {auc:.2f}; wrote", PLOTS_DIR / "hypo_calibration.png")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=4)
    ap.add_argument("--per-day", type=int, default=6)
    a = ap.parse_args()
    main(a.patients, a.per_day)
