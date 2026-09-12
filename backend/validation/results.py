"""Assemble validation/RESULTS.md from the JSON outputs of the five
validation scripts (run them first, or `python -m backend.validation.run_all`)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from backend.config import VALIDATION_DIR, PLOTS_DIR


def _load(name: str):
    p = VALIDATION_DIR / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main() -> str:
    pr = _load("param_recovery.json")
    fr = _load("forecast_rmse.json")
    hc = _load("hypo_calibration.json")
    an = _load("alcohol_night.json")
    dc = _load("dcct.json")
    lines = [f"# GlucoPilot validation results", "",
             f"Generated {datetime.now().isoformat(timespec='minutes')} by `python -m backend.validation.results`. All data are synthetic (30 virtual patients, 90 days each); "
             "days 0-59 are used for fitting, days 60-89 are held out.", "",
             "| # | Check | Plot | Headline |", "|---|---|---|---|"]
    if pr:
        s = pr["summary"]
        best = max(s.items(), key=lambda kv: kv[1]["r"])
        lines.append(f"| 1 | Parameter recovery | `plots/param_recovery.png` | {pr['n_patients']} patients fitted from logged data (+-30 % carb error); correlation true vs fitted r = "
                     + ", ".join(f"{v['r']:.2f}" for v in s.values()) + f" (8 quantities); mean fit time {pr['mean_fit_seconds']:.1f} s (max {pr['max_fit_seconds']:.1f} s, budget 60 s) |")
    if fr:
        m = fr["summary_mean"]; d = fr["demo"]
        lines.append(f"| 2 | Forecast RMSE (held-out days) | `plots/forecast_rmse.png` | demo patient at 60 min: population {d['population_60']:.1f} -> personalised {d['personalised_60']:.1f} -> +residual **{d['full_60']:.1f} mg/dL** "
                     f"(target < 20: {'met' if d['full_60'] < 20 else 'not met'}); cohort mean of {len(fr['rows'])} patients at 60 min: {m['population_60']:.1f} / {m['personalised_60']:.1f} / {m['full_60']:.1f} |")
    if hc:
        lines.append(f"| 3 | Hypo calibration | `plots/hypo_calibration.png` | {hc['n_anchors']} held-out anchors, {len(hc['patients'])} patients: Brier {hc['brier']:.3f} vs climatology {hc['brier_climatology']:.3f}, ECE {hc['ece']:.3f}, AUC {hc['auc']:.2f}, base rate {hc['base_rate']:.2f} |")
    if an:
        lines.append(f"| 4 | Alcohol night overlay | `plots/alcohol_night.png` | {an['date']}: twin overnight nadir {an['overnight_min_twin']:.0f} mg/dL at {an['twin_nadir_time'][11:16]} (synthetic CGM {an['overnight_min_actual']:.0f}); "
                     f"same night with alcohol removed: {an['overnight_min_twin_no_alcohol']:.0f} mg/dL; overlay RMSE {an['overlay_rmse_mgdl']:.1f} mg/dL |")
    if dc:
        lines.append(f"| 5 | DCCT reproduction | `plots/dcct_reproduction.png` | A1c 9 -> 7: 10-year retinopathy {100 * dc['p_retinopathy_a1c9']:.1f} % -> {100 * dc['p_retinopathy_a1c7']:.1f} %, "
                     f"**{dc['reduction_pct']:.1f} % reduction** (hazard ratio {dc['hazard_ratio']:.2f}; DCCT reported 76 %) |")
    lines += ["", "## 1. Parameter recovery", ""]
    if pr:
        lines += ["| quantity | r | mean abs error |", "|---|---|---|"]
        for k, v in pr["summary"].items():
            lines.append(f"| {k} | {v['r']:.2f} | {v['mean_abs_err']:.3f} |")
        lines += ["", f"Mean training RMSE {pr['mean_rmse_train']:.1f} mg/dL over 6-hour windows. The fitter works on a reduced 9-parameter model whose time-of-day sensitivity bins absorb the patient's overall insulin-sensitivity factor, so ratios and the extension gains are the identifiable quantities. Carb bioavailability is biased low because it is confounded with the sensitivities and the +-30 % carb-logging noise.", ""]
    lines += ["## 2. Forecast RMSE at 30 / 60 / 120 min (held-out days 60-89)", ""]
    if fr:
        lines += ["| patient | 30 pop | 30 pers | 30 full | 60 pop | 60 pers | 60 full | 120 pop | 120 pers | 120 full |", "|---|---|---|---|---|---|---|---|---|---|"]
        for r in fr["rows"]:
            lines.append(f"| {r['patient']} | " + " | ".join(f"{r[f'{k}_{h}']:.1f}" for h in (30, 60, 120) for k in ("population", "personalised", "full")) + " |")
        m = fr["summary_mean"]
        lines.append(f"| **mean** | " + " | ".join(f"**{m[f'{k}_{h}']:.1f}**" for h in (30, 60, 120) for k in ("population", "personalised", "full")) + " |")
        lines += ["", "Forecasts are anchored on the observed glucose at the anchor time after a 3-hour warm-up with the logged events replayed (the live twin anchors through the UKF). CGM noise alone is 8 mg/dL, and meal carbs are logged with +-30 % error, so the residual floor is well above zero.", ""]
    lines += ["## 3. Hypo calibration", ""]
    if hc:
        lines += ["| predicted bin | n | mean predicted | observed |", "|---|---|---|---|"]
        for b in hc["bins"]:
            lines.append(f"| {b['lo']:.2f}-{b['hi']:.2f} | {b['n']} | {b['pred']:.2f} | {b['obs']:.2f} |")
        lines += ["", f"Predicted P(glucose < 70 within 4 h) from 150-sample Monte Carlo over the fitted posterior at held-out anchors, vs. the observed outcome. Brier {hc['brier']:.3f} (climatology {hc['brier_climatology']:.3f}), expected calibration error {hc['ece']:.3f}, AUC {hc['auc']:.2f}.", ""]
    lines += ["## 4. Alcohol night", ""]
    if an:
        lines += [f"Demo patient, {an['date']}: " + "; ".join(f"{d['label']} at {d['start_time'][11:16]} ({d['alcohol_g']:.0f} g alcohol, {d['carbs_g']:.0f} g carbs)" for d in an["drinks"]) + ".",
                  f"Twin nadir {an['overnight_min_twin']:.0f} mg/dL at {an['twin_nadir_time'][11:16]} vs synthetic CGM nadir {an['overnight_min_actual']:.0f}; with alcohol removed the twin's overnight minimum is {an['overnight_min_twin_no_alcohol']:.0f} mg/dL. Minutes below 70 in the twin: {an['hypo_minutes_twin']:.0f} as logged, {an['hypo_minutes_no_alcohol']:.0f} without alcohol.", ""]
    lines += ["## 5. DCCT reproduction", ""]
    if dc:
        lines += [f"Constant A1c-equivalent weeks looped for 10 years: retinopathy probability {100 * dc['p_retinopathy_a1c9']:.1f} % at A1c 9 vs {100 * dc['p_retinopathy_a1c7']:.1f} % at A1c 7, a {dc['reduction_pct']:.1f} % reduction (hazard ratio {dc['hazard_ratio']:.2f}). DCCT (1993) reported 76 % in the primary-prevention cohort; the hazard ratio is calibrated to 0.24 exactly and the probability ratio differs only through the 1 - exp(-H) mapping.", ""]
    lines += ["## Sanity plots (checkpoint 2)", "", "`plots/sanity_alcohol.png` (4 beers at 21:00 -> nadir 61 mg/dL at +9.7 h), `plots/sanity_exercise.png` (aerobic drop with lingering sensitivity; anaerobic transient rise), `plots/sanity_montecarlo.png` (200 trajectories in 0.16 s).", ""]
    text = "\n".join(lines)
    (VALIDATION_DIR / "RESULTS.md").write_text(text, encoding="utf-8")
    print("wrote", VALIDATION_DIR / "RESULTS.md")
    return text


if __name__ == "__main__":
    main()
