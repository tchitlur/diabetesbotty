# GlucoPilot validation results

Generated 2026-09-12T03:29 by `python -m backend.validation.results`. All data are synthetic (30 virtual patients, 90 days each); days 0-59 are used for fitting, days 60-89 are held out.

| # | Check | Plot | Headline |
|---|---|---|---|
| 1 | Parameter recovery | `plots/param_recovery.png` | 30 patients fitted from logged data (+-30 % carb error); correlation true vs fitted r = 0.77, 0.53, 0.61, 0.45, 0.77, 0.63, 0.46, 0.71 (8 quantities); mean fit time 4.7 s (max 9.2 s, budget 60 s) |
| 2 | Forecast RMSE (held-out days) | `plots/forecast_rmse.png` | demo patient at 60 min: population 15.7 -> personalised 16.2 -> +residual **14.5 mg/dL** (target < 20: met); cohort mean of 6 patients at 60 min: 22.2 / 16.9 / 14.7 |
| 3 | Hypo calibration | `plots/hypo_calibration.png` | 700 held-out anchors, 4 patients: Brier 0.117 vs climatology 0.233, ECE 0.111, AUC 0.94, base rate 0.37 |
| 4 | Alcohol night overlay | `plots/alcohol_night.png` | 2025-08-09: twin overnight nadir 69 mg/dL at 05:45 (synthetic CGM 39); same night with alcohol removed: 125 mg/dL; overlay RMSE 25.8 mg/dL |
| 5 | DCCT reproduction | `plots/dcct_reproduction.png` | A1c 9 -> 7: 10-year retinopathy 22.1 % -> 5.8 %, **73.7 % reduction** (hazard ratio 0.24; DCCT reported 76 %) |

## 1. Parameter recovery

| quantity | r | mean abs error |
|---|---|---|
| night/day sensitivity ratio | 0.77 | 0.095 |
| evening/day sensitivity ratio | 0.53 | 0.077 |
| overall sensitivity (day bin x SI factor) | 0.61 | 0.224 |
| carb bioavailability (AG) | 0.45 | 0.197 |
| carb absorption tau (min) | 0.77 | 6.798 |
| exercise multiplier | 0.63 | 0.277 |
| alcohol gain | 0.46 | 0.510 |
| sleep-debt coefficient | 0.71 | 0.043 |

Mean training RMSE 31.0 mg/dL over 6-hour windows. The fitter works on a reduced 9-parameter model whose time-of-day sensitivity bins absorb the patient's overall insulin-sensitivity factor, so ratios and the extension gains are the identifiable quantities. Carb bioavailability is biased low because it is confounded with the sensitivities and the +-30 % carb-logging noise.

## 2. Forecast RMSE at 30 / 60 / 120 min (held-out days 60-89)

| patient | 30 pop | 30 pers | 30 full | 60 pop | 60 pers | 60 full | 120 pop | 120 pers | 120 full |
|---|---|---|---|---|---|---|---|---|---|
| demo | 13.6 | 13.7 | 12.9 | 15.7 | 16.2 | 14.5 | 21.7 | 22.7 | 20.3 |
| p01 | 13.9 | 12.7 | 11.4 | 18.7 | 16.8 | 14.2 | 32.5 | 24.5 | 22.4 |
| p02 | 14.2 | 12.4 | 11.1 | 21.1 | 18.5 | 14.9 | 31.3 | 24.0 | 18.7 |
| p03 | 15.2 | 13.7 | 12.6 | 23.8 | 18.9 | 17.1 | 38.3 | 27.3 | 22.9 |
| p04 | 16.3 | 11.7 | 11.5 | 25.5 | 14.1 | 13.4 | 40.0 | 17.7 | 16.7 |
| p05 | 17.5 | 12.6 | 12.5 | 28.6 | 16.7 | 14.3 | 48.4 | 25.7 | 21.2 |
| **mean** | **15.1** | **12.8** | **12.0** | **22.2** | **16.9** | **14.7** | **35.4** | **23.7** | **20.4** |

Forecasts are anchored on the observed glucose at the anchor time after a 3-hour warm-up with the logged events replayed (the live twin anchors through the UKF). CGM noise alone is 8 mg/dL, and meal carbs are logged with +-30 % error, so the residual floor is well above zero.

## 3. Hypo calibration

| predicted bin | n | mean predicted | observed |
|---|---|---|---|
| 0.00-0.05 | 337 | 0.01 | 0.04 |
| 0.05-0.10 | 40 | 0.07 | 0.28 |
| 0.10-0.20 | 69 | 0.14 | 0.46 |
| 0.20-0.35 | 55 | 0.26 | 0.38 |
| 0.35-0.50 | 41 | 0.42 | 0.71 |
| 0.50-0.70 | 32 | 0.59 | 0.84 |
| 0.70-0.90 | 36 | 0.79 | 0.97 |
| 0.90-1.00 | 90 | 0.98 | 1.00 |

Predicted P(glucose < 70 within 4 h) from 150-sample Monte Carlo over the fitted posterior at held-out anchors, vs. the observed outcome. Brier 0.117 (climatology 0.233), expected calibration error 0.111, AUC 0.94.

## 4. Alcohol night

Demo patient, 2025-08-09: 4 wines at 22:06 (56 g alcohol, 16 g carbs).
Twin nadir 69 mg/dL at 05:45 vs synthetic CGM nadir 39; with alcohol removed the twin's overnight minimum is 125 mg/dL. Minutes below 70 in the twin: 70 as logged, 0 without alcohol.

## 5. DCCT reproduction

Constant A1c-equivalent weeks looped for 10 years: retinopathy probability 22.1 % at A1c 9 vs 5.8 % at A1c 7, a 73.7 % reduction (hazard ratio 0.24). DCCT (1993) reported 76 % in the primary-prevention cohort; the hazard ratio is calibrated to 0.24 exactly and the probability ratio differs only through the 1 - exp(-H) mapping.

## Sanity plots (checkpoint 2)

`plots/sanity_alcohol.png` (4 beers at 21:00 -> nadir 61 mg/dL at +9.7 h), `plots/sanity_exercise.png` (aerobic drop with lingering sensitivity; anaerobic transient rise), `plots/sanity_montecarlo.png` (200 trajectories in 0.16 s).
