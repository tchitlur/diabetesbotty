"""Validation 2: forecast RMSE at 30/60/120 min on held-out days (60-89):
population model vs personalised vs personalised + residual.

Writes validation/plots/forecast_rmse.png and validation/forecast_rmse.json.
Run: python -m backend.validation.forecast_rmse [--patients N]
"""
from __future__ import annotations

import argparse
import json
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from backend.config import PLOTS_DIR, VALIDATION_DIR
from backend.engine.params import build_params
from backend.data.store import load_patient, list_cohort
from backend.inference.fitter import Fitter, fitted_params
from backend.inference.residual import build_dataset, ResidualModel, HORIZONS, HOLDOUT_DAYS, TRAIN_DAYS
from backend.inference.windows import pick_starts


def evaluate_patient(pid: str, seed: int = 11) -> Dict[str, float]:
    pt = load_patient(pid)
    pop = build_params({"body_weight_kg": pt.meta["body_weight_kg"], "basal_u_per_h": pt.true_params["basal_u_per_h"],
                        "alcohol_widmark_r": pt.true_params.get("alcohol_widmark_r", 0.62)})
    if pt.fit is None:
        res = Fitter(pt, n_windows=48, seed=0).fit(max_nfev=40, verbose=False)
        pt.fit = res
    pers = fitted_params(pt)
    rng = np.random.default_rng(seed)
    starts_tr = pick_starts(pt, TRAIN_DAYS[0], TRAIN_DAYS[1], per_day=list(range(0, 24, 2)), rng=rng)
    starts_ho = pick_starts(pt, HOLDOUT_DAYS[0], HOLDOUT_DAYS[1], per_day=list(range(1, 24, 2)), rng=rng)
    # population model errors on held-out days
    _, err_pop, _ = build_dataset(pt, pop, starts_ho)
    # personalised model: train the residual on days 0-59, evaluate on 60-89
    Xtr, err_tr, _ = build_dataset(pt, pers, starts_tr)
    model = ResidualModel()
    model.fit(Xtr, err_tr)
    Xho, err_ho, _ = build_dataset(pt, pers, starts_ho)
    pred = model.predict_batch(Xho)
    out: Dict[str, float] = {"patient": pid, "n_holdout": int(len(Xho))}
    for i, h in enumerate(HORIZONS):
        ok = ~np.isnan(err_ho[:, i]) & ~np.isnan(err_pop[:, i])
        out[f"population_{h}"] = float(np.sqrt(np.mean(err_pop[ok, i] ** 2)))
        out[f"personalised_{h}"] = float(np.sqrt(np.mean(err_ho[ok, i] ** 2)))
        out[f"full_{h}"] = float(np.sqrt(np.mean((err_ho[ok, i] - pred[ok, i]) ** 2)))
    return out


def main(n_patients: int = 6) -> Dict[str, object]:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    ids = ["demo"] + list_cohort()[: max(n_patients - 1, 0)]
    rows: List[Dict[str, float]] = []
    for pid in ids:
        r = evaluate_patient(pid)
        rows.append(r)
        print(f"  {pid}: " + "  ".join(f"{h}min pop {r[f'population_{h}']:.1f} / pers {r[f'personalised_{h}']:.1f} / full {r[f'full_{h}']:.1f}" for h in HORIZONS))
    summary = {}
    for h in HORIZONS:
        for k in ("population", "personalised", "full"):
            summary[f"{k}_{h}"] = float(np.mean([r[f"{k}_{h}"] for r in rows]))
    demo = rows[0]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    x = np.arange(len(HORIZONS))
    w = 0.26
    for j, (k, label, color) in enumerate((("population", "population model", "#8b98a8"), ("personalised", "personalised (fit)", "tab:blue"), ("full", "personalised + residual", "tab:green"))):
        vals = [summary[f"{k}_{h}"] for h in HORIZONS]
        ax.bar(x + (j - 1) * w, vals, w, label=label, color=color)
        for xi, v in zip(x + (j - 1) * w, vals):
            ax.text(xi, v + 0.4, f"{v:.1f}", ha="center", fontsize=8)
    ax.axhline(20, color="k", ls=":", lw=1)
    ax.text(x[0] - 0.4, 20.6, "target: < 20 mg/dL at 60 min", fontsize=8, ha="left")
    ax.set_xticks(x, [f"{h} min" for h in HORIZONS])
    ax.set_ylabel("RMSE (mg/dL) on held-out days 60-89")
    ax.set_title(f"Forecast error, mean over {len(rows)} patients (demo: 60 min full model = {demo['full_60']:.1f} mg/dL)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "forecast_rmse.png", dpi=110)
    out = {"summary_mean": summary, "demo": demo, "rows": rows, "target_full_60_under_20": bool(demo["full_60"] < 20.0)}
    (VALIDATION_DIR / "forecast_rmse.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("wrote", PLOTS_DIR / "forecast_rmse.png")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=6)
    main(ap.parse_args().patients)
