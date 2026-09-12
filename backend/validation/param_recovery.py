"""Validation 1: parameter recovery across the synthetic cohort.

Fits every cohort patient (plus the demo patient) from its *logged* data and
plots fitted vs true for the identifiable quantities. Writes
validation/plots/param_recovery.png and validation/param_recovery.json.

Run: python -m backend.validation.param_recovery
"""
from __future__ import annotations

import json
import time
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from backend.config import PLOTS_DIR, VALIDATION_DIR
from backend.data.store import load_patient, list_cohort
from backend.inference.fitter import Fitter
from backend.engine.params import build_params

# (label, fitted-value fn, true-value fn). The fitter works on a reduced model
# whose sensitivity bins absorb the patient's overall insulin-sensitivity
# factor, so the identifiable quantities are ratios and the direct extensions.
QUANTITIES = [
    ("night/day sensitivity ratio", lambda f, t: f["si_tod0"] / f["si_tod1"], lambda f, t: t["si_tod0"] / t["si_tod1"]),
    ("evening/day sensitivity ratio", lambda f, t: f["si_tod2"] / f["si_tod1"], lambda f, t: t["si_tod2"] / t["si_tod1"]),
    ("overall sensitivity (day bin x SI factor)", lambda f, t: f["si_tod1"], lambda f, t: t["SIT"] / 0.00512),
    ("carb bioavailability (AG)", lambda f, t: f["carb_ratio"], lambda f, t: t["AG"]),
    ("carb absorption tau (min)", lambda f, t: f["tau_carb"], lambda f, t: t["tau_carb"]),
    ("exercise multiplier", lambda f, t: f["exercise_mult"], lambda f, t: t["exercise_mult"]),
    ("alcohol gain", lambda f, t: f["alcohol_gain"], lambda f, t: t["alcohol_gain"]),
    ("sleep-debt coefficient", lambda f, t: f["sleep_debt_coef"], lambda f, t: t["sleep_debt_coef"]),
]


def main(max_patients: int = 30) -> Dict[str, object]:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    ids = ["demo"] + list_cohort()
    ids = ids[:max_patients]
    rows: List[Dict[str, object]] = []
    tic = time.time()
    for pid in ids:
        pt = load_patient(pid)
        f = Fitter(pt, n_windows=48, seed=0)
        res = f.fit(max_nfev=40, verbose=False)
        fitted = {k: v["mean"] for k, v in res["params"].items()}
        stds = {k: v["std"] for k, v in res["params"].items()}
        rows.append({"patient": pt.patient_id, "fitted": fitted, "std": stds, "true": pt.true_params,
                     "rmse": res["rmse_train_mgdl"], "elapsed_s": res["elapsed_s"]})
        print(f"  {pt.patient_id}: rmse {res['rmse_train_mgdl']:.1f}  {res['elapsed_s']:.1f} s")
    print(f"fitted {len(rows)} patients in {time.time() - tic:.0f} s")

    fig, axes = plt.subplots(2, 4, figsize=(16, 8))
    summary = {}
    for ax, (label, ffn, tfn) in zip(axes.ravel(), QUANTITIES):
        x = np.array([tfn(r["fitted"], r["true"]) for r in rows])
        y = np.array([ffn(r["fitted"], r["true"]) for r in rows])
        ax.scatter(x, y, s=28, color="tab:blue", alpha=0.8)
        lo, hi = min(x.min(), y.min()), max(x.max(), y.max())
        ax.plot([lo, hi], [lo, hi], "k--", lw=1)
        r = float(np.corrcoef(x, y)[0, 1]) if np.std(x) > 0 and np.std(y) > 0 else float("nan")
        ax.set_title(f"{label}\nr = {r:.2f}", fontsize=9)
        ax.set_xlabel("true")
        ax.set_ylabel("fitted")
        summary[label] = {"r": r, "mean_abs_err": float(np.mean(np.abs(x - y)))}
    fig.suptitle(f"Parameter recovery on {len(rows)} synthetic patients (fit on logged data with +-30 % carb error)")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "param_recovery.png", dpi=110)
    out = {"n_patients": len(rows), "summary": summary,
           "mean_rmse_train": float(np.mean([r["rmse"] for r in rows])),
           "mean_fit_seconds": float(np.mean([r["elapsed_s"] for r in rows])),
           "max_fit_seconds": float(np.max([r["elapsed_s"] for r in rows])), "rows": rows}
    (VALIDATION_DIR / "param_recovery.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print("wrote", PLOTS_DIR / "param_recovery.png")
    return out


if __name__ == "__main__":
    main()
