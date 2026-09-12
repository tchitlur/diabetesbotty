# GlucoPilot build notes

Running log of decisions, substitutions, cuts, and how to run. Updated at every checkpoint.

## How to run

```powershell
.\scripts\setup_key.ps1   # optional: Gemini key. Demo works without it (local fallback parser).
.\run_demo.ps1            # starts backend :8000 + frontend :5173, opens browser
.\stop_demo.ps1
```

## Environment (checkpoint 1)

- Windows 11, PowerShell. Installed via winget: GitHub CLI 2.100, Python 3.11.9, Node 24.19 LTS. Git 2.47 was present.
- `Set-ExecutionPolicy` is overridden by a machine-scope Bypass policy; venv activation is not required because every script calls `.venv\Scripts\python.exe` directly.
- Python venv: `.venv` (3.11). All packages from `requirements.txt` install cleanly (numpy<2 pinned for lightgbm/filterpy compatibility).
- Gemini model constant: `backend/config.py::GEMINI_MODEL = "gemini-2.5-flash-lite"`.

## Decisions

- `simglucose` is **not** used (per spec). The Hovorka 2004 model plus extensions is implemented in `backend/engine/`.
- Event contract gained two optional fields beyond the spec list: `water_ml` (for water events) and `label` (display-only text). Everything else is exactly as specified.
- `PermissionCard.verdict` also allows `request_data` and `escalate` so the safety gate can return through the same card shape the UI already renders.
- Frontend uses plain CSS (no Tailwind) to keep `npm install` small and fast.
- Frontend talks to the backend through the Vite proxy (`/api/*` → `127.0.0.1:8000`) so there is no hard-coded host in React; CORS for `localhost:5173` is also enabled server-side.

## Engine decisions (checkpoint 2)

- **Integrator.** The spec names `scipy.solve_ivp`; it is implemented (`fast.integrate_solve_ivp`) and used as the reference in `engine/test_smoke.py`, but the production path is a vectorised fixed-step RK4 (`fast.integrate`, 2.5-min substeps) because 200 Monte Carlo trajectories x 96 steps of `solve_ivp` cannot meet the 2-second budget. RK4 agrees with RK45 to < 0.01 mg/dL on a meal test. Monte Carlo (200 x 8 h) runs in ~0.16 s.
- **Units.** Hovorka states are per kg body weight (Q in mmol/kg, VG in L/kg). Glucose is exposed in mg/dL, insulin in mU/L. Basal `insulin_units` for `insulin_kind=basal` events is the *total* over `duration_min`; a basal event overrides the patient's configured basal rate while active.
- **Steady state.** Hovorka's published sensitivities imply a basal plasma insulin of ~5.5 mU/L (0.38 U/h for 70 kg). `fast.steady_basal_rate()` solves the balance numerically and every virtual patient's basal is set from it (times a dosing-error factor). `fast.calibrate_carb_ratio()` titrates the clinical carb ratio the same way (bisection on the bolus that returns a 60 g meal to baseline at 5 h). The default physiology gives ~33 g/U; it is a property of the model, not a claim about people.
- **Alcohol delayed low.** Two mechanisms: direct EGP suppression proportional to BAC (Widmark absorption, zero-order 0.015 g/dL/h clearance) plus a lingering suppression state that rises with tau 150 min and decays with tau 300 min (NADH redox after ethanol oxidation). Swept in `params.yaml` so that 4 beers at 21:00 give a nadir of 61 mg/dL at +9.7 h and 2 vodka shots a nadir at +4.3 h (see `validation/plots/sanity_alcohol.png`). Because the low lands after 8 h, the permission engine uses a 12 h horizon for alcohol events.
- **Hidden states.** Hovorka's Q2/S1/S2/x1-x3 and the extension memories are not part of the `State` contract; `simulate()` accepts an optional `hidden` vector (`Trajectories.hidden_final`) so consecutive simulations chain exactly, and otherwise initialises them at steady state from the observed glucose/insulin.
- Validation outputs go to the repo-root `validation/plots/` and `validation/RESULTS.md` (acceptance test wording); the scripts live in `backend/validation/`.

## Data decisions (checkpoint 3)

- Cohort dates are fixed (2025-06-02 to 2025-08-30, 90 days) so everything is reproducible; the app's "now" is the last CGM timestamp of the demo patient, not the wall clock.
- All 30 patients are integrated in one batch (B = 30) day by day, chaining hidden states and running the daily medium layer in between: ~40 s for the whole cohort. Regenerate with `python -m backend.data.cohort` (cohort dir is gitignored; the demo patient is committed).
- The three Hovorka insulin sensitivities are sampled with a shared per-patient factor (plus small own noise) instead of independently: independent sampling produced physiologies where EGP shut off at near-zero insulin while meal disposal stayed weak, giving mean glucose > 280.
- Each virtual patient's basal is `steady_basal_rate(true params, 130 mg/dL)` times a +-7 % titration error; the clinical carb ratio is found by a batched grid search over 40 candidate doses (minimise time above target + heavy penalty on dropping below 80). Logged meal carbs carry +-30 % error; boluses are computed from the *logged* carbs with a further +-20 % dosing error (so the two compound, as in life).
- Sleep debt is a bounded accumulator (`debt = 0.5*debt + shortfall`, capped at 8 h) and its insulin-sensitivity effect is applied once, in the fast layer, through the fitted `sleep_debt_coef`. An earlier version applied it twice and let debt grow unbounded, which sent glucose to 300+.
- The synthetic CGM is written as a Dexcom Clarity CSV and read back through `adapters/csv_ingest.py` (5-min grid alignment, gap detection, |RoC| > 4 mg/dL/min artifact flags, sensor-age tagging from warm-up gaps, staleness, data-quality score), so the demo patient's quality score (0.75) is the real output of the validation path.
- Basal `insulin` events with `insulin_kind=basal` are emitted once per day (total units over 1440 min) as the patient's pump setting; the fitted `basal_drift` multiplies whatever basal is active.
- Cohort spread after tuning: mean glucose 93-203 mg/dL, TIR 0.34-0.83. The demo patient (p00) drinks on ~60 % of weekend nights by design so the replay tab has Fridays to show.

## Checkpoint status

- [x] 1. Environment + contracts (stub simulator)
- [x] 2. Fast-layer physiology
- [x] 3. Synthetic cohort
- [ ] 4. Inference
- [ ] 5. Medium + slow layers
- [ ] 6. Decision + safety + API
- [ ] 7. Parsers
- [ ] 8. Frontend
- [ ] 9. Validation + docs
- [ ] 10. Final release

## Next

Checkpoint 4: fitter (batched least squares + bootstrap), UKF state estimator, LightGBM residual model, drift monitor, parameter-recovery plot.
