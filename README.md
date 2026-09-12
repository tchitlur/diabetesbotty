# GlucoPilot

A personalised, mechanistic-plus-learned simulation of a Type 1 diabetic's body. Every intake and activity (food, alcohol, caffeine, insulin, exercise, sleep, illness, stress, water) goes into a physiology model, and everything you see is the output of a simulator, estimator or optimiser: a short-horizon glucose forecast with uncertainty, a permission decision ("can I have two more beers tonight?") with the condition that makes it safe, and a 10-year projection of organ risk for your current or proposed lifestyle.

All data are synthetic. There is no real patient. Decision support only; nothing doses insulin.

## Setup in five steps (Windows)

1. Install the tools if you do not have them (PowerShell):
   ```powershell
   winget install --id Git.Git -e --source winget
   winget install --id Python.Python.3.11 -e --source winget
   winget install --id OpenJS.NodeJS.LTS -e --source winget
   ```
   Then open a new PowerShell window so the PATH is refreshed.
2. Clone and enter the repository:
   ```powershell
   git clone https://github.com/tchitlur/diabetesbotty.git
   cd diabetesbotty
   ```
3. (Optional) Add a Gemini key so the parsers use `gemini-2.5-flash-lite` instead of the local fallback:
   ```powershell
   .\scripts\setup_key.ps1
   ```
   It tells you where to get the key, asks you to paste it, and writes `.env`. The demo runs without it.
4. Start everything:
   ```powershell
   .\run_demo.ps1
   ```
   First run only: creates `.venv`, installs Python packages and `npm` packages (a few minutes). Every run: starts the API on port 8000, the UI on port 5173, and opens the browser.
5. Stop it:
   ```powershell
   .\stop_demo.ps1
   ```

`pytest` runs the smoke tests (every backend package has a `test_smoke.py`). `python -m backend.validation.run_all` regenerates every validation plot and `validation/RESULTS.md`.

## The demo, in order

The twin's clock is frozen at **Friday 2025-08-29 19:00** (just after dinner, glucose in the low 90s), inside 90 days of synthetic data. It never sees anything after that moment.

1. **Now tab.** Estimated state with +-std (UKF over the last 12 h), the 8-hour forecast (median and p10-p90 band from 200 Monte Carlo runs), P(hypo) around 20 %, substance decay curves, energy gauge.
2. **Chat: `can I have two more beers tonight?`** The parsed event appears as JSON with the parser badge (Gemini or local fallback), then "simulating...", then a card: *approved with condition: eat 15 g carbs before bed, no bolus*, with the mini curve (do nothing / as proposed / best variant), the top-3 factors, the 10-year delta if repeated weekly, and the data used / missing. The card also lands in the Today tab. "Add to plan" commits the beers **and** the bedtime snack to the forecast.
3. **Chat: `fasted run tomorrow at 7 for 30 min`.** Approved: judged in its own window (06:00 to 11:30) the run carries about 2 % hypo risk. For the other two verdict paths try the tap button **lift 45 min** (approved with a condition: 15 g fast carbs at the start, plus a safe alternative window) and **`two shots of vodka at 11pm`** (denied: even the safest variant leaves P(hypo) above 20 %).
4. **`/change morning_workouts`** (also `cut_caffeine`, `drink_fridays_only`, `fasting_16_8`). The representative week is rewritten and simulated for 30 days (medium layer) and 10 years (slow layer); you get a verdict and the diff of all 22 state variables. **Body tab**: toggle "pending change" and the five organs recolour with the per-organ risk deltas.
5. **`/budget`.** Three numbers: weekly alcohol (g), caffeine (mg) and off-plan meals that keep 10-year organ risk within 5 % of the current trajectory.
6. **`/plan tomorrow`** (or `/plan tomorrow 3 drinks`). Grid search over workout start, snack placement and drink cutoff; the Today tab shows the hourly green/amber/red timeline and the pending alerts with the past event most responsible.
7. **Replay tab.** Opens on Saturday 2025-08-09 (4 wines). Drag *Alcohol x* to 0: the twin's overnight nadir rises from 69 to about 125 mg/dL and the low disappears. Other sliders: carbs, exercise, bolus insulin.
8. **Trends tab.** A1c twin estimate + 90-day projection, insulin-sensitivity drift with sleep debt, hypo hours per day, sleep-vs-sensitivity scatter.
9. **Clinician view** (header link, `/clinician`). Parameter drift from sliding refits, residual log, fitted posterior, escalation history.
10. **`/why`** prints the explanation of the last card. The tap bar (beer/wine/spirit x count, coffee, run 30 min, lift 45 min) creates proposals without typing. Remove `.env` (or set an invalid key) and the badge switches to *local fallback*; everything still works. `POST /permission?stale=30` returns a request-for-data card instead of a verdict. The photo button is enabled only when a Gemini key is configured.

`frontend/audit.spec.ts` (Playwright) walks every screen and interaction and fails on any console error, failed request, placeholder text or empty chart; `audit/FINDINGS.md` lists what it found and what was changed.

## What is in the box

```
backend/
  schema/     State (22 variables, fixed units), Event, Pydantic API models
  engine/     Hovorka 2004 + extensions (fast layer, vectorised RK4), medium layer (daily), slow layer (10 y), Monte Carlo, params.yaml with sources
  inference/  batched least-squares fitter + 30-sample bootstrap, UKF, LightGBM residual model, drift monitor
  decision/   permission, planner, change request, budget, alerts, replay (every one is a loop over simulate())
  safety/     rules.yaml, gate (proceed / request_data / escalate), explanation layer
  adapters/   Dexcom / LibreView CSV ingest + validation, Gemini text + vision parsers, local fallback parser, food table
  data/       synthetic cohort generator (30 patients), committed demo patient
  api/        FastAPI app and the Twin session object
  validation/ scripts that write validation/plots/*.png and validation/RESULTS.md
frontend/     Vite + React + Recharts (Now / Today / Body / Trends / Replay, chat, tap bar, /clinician)
```

## Why this is not an LLM wrapper

Gemini is called in exactly two places, and both return only structured JSON that is validated against the `Event` contract: photo -> nutrition items, and free text -> one event. If there is no key or the call fails, a deterministic regex + lookup-table parser produces the same contract, and the UI says so on a badge. Nothing the user sees is generated text.

Every number on screen comes from a model you can read:

- **Physiology.** The Hovorka (2004) glucose-insulin model with published parameters, plus one or two ODEs each for gut absorption (fat and fibre slow it), liver and muscle glycogen, blood alcohol (Widmark absorption, zero-order clearance, hepatic glucose output suppressed by BAC and a lingering state so the low arrives 4-10 hours after drinking), caffeine (5-hour half-life, transient insulin resistance, worse sleep), exercise (aerobic uptake and a decaying sensitivity window; anaerobic transient rise), ketones with a DKA flag, hydration, and an energy score. `params.yaml` cites every constant.
- **Personalisation.** Nine parameters are fitted per patient by least squares on 6-hour windows of their own CGM (three time-of-day sensitivities, carb bioavailability, absorption time constant, exercise and alcohol gains, basal drift, sleep-debt coefficient), with a 30-resample bootstrap for a posterior. A UKF estimates the hidden state now. A gradient-boosted residual model learns what the ODE still gets wrong at 30/60/120 min.
- **Decisions.** Every card is a Monte Carlo experiment: 200 trajectories sampled from the posterior and from the uncertainty of the logged amounts, for do-nothing, the proposal, and its variants. Approval needs P(glucose < 70) under 5 % with no hyper breach; otherwise the best passing variant becomes the condition. The planner batches hundreds of candidate days through the same integrator. Change requests loop a rewritten week through the daily and the 10-year layers. The safety gate runs first and can refuse to decide (stale CGM, bad data) or escalate (DKA pattern, repeated severe lows, model drift).
- **Long term.** Organ accumulators are cumulative hazards with DCCT/UKPDS coefficients; A1c 9 -> 7 reproduces the DCCT retinopathy reduction.

An LLM could not have produced the delayed alcohol low, the p10-p90 band, or the "eat 15 g at bedtime" condition, because those are consequences of equations fitted to this patient's data, not of a prompt.

## Validation results

Generated by `python -m backend.validation.run_all`; numbers in `validation/RESULTS.md`, plots in `validation/plots/`.

| Check | Plot | Result |
|---|---|---|
| Parameter recovery, 30 synthetic patients fitted from logged data with +-30 % carb error | `param_recovery.png` | true-vs-fitted r = 0.77 (night/day sensitivity ratio), 0.77 (carb absorption tau), 0.71 (sleep-debt coefficient), 0.63 (exercise), 0.46 (alcohol gain), 0.45 (carb bioavailability); mean fit 4.7 s, max 9 s |
| Forecast RMSE on held-out days, 30/60/120 min | `forecast_rmse.png` | demo patient at 60 min: population 15.7 -> personalised 16.2 -> +residual **14.5 mg/dL** (target < 20 met); mean over 6 patients at 60 min: 22.2 -> 16.9 -> 14.7 |
| Hypo calibration (predicted vs observed P(low within 4 h)), 700 held-out anchors, 4 patients | `hypo_calibration.png` | Brier 0.117 vs climatology 0.233, ECE 0.111, AUC 0.94; the twin is under-confident in the 0.1-0.6 range (observed rate above predicted), partly because CGM compression-low artifacts count as observed lows |
| Alcohol night overlay, demo patient 2025-08-09 | `alcohol_night.png` | twin nadir 69 mg/dL at 05:45 vs synthetic CGM 39 at 05:00; with alcohol removed the twin's overnight minimum is 125 |
| DCCT reproduction | `dcct_reproduction.png` | A1c 9 -> 7: retinopathy 22.1 % -> 5.8 %, a 73.7 % reduction (hazard ratio 0.24; DCCT 76 %) |

Sanity plots from the engine checkpoint: `sanity_alcohol.png` (4 beers at 21:00 -> nadir 61 mg/dL at +9.7 h), `sanity_exercise.png`, `sanity_montecarlo.png`.

## API

`http://127.0.0.1:8000/docs` lists everything. Main routes: `GET /state`, `GET /forecast`, `POST /permission` (`?stale=30` to test the gate), `GET|POST /plan`, `POST /change`, `GET /budget`, `GET /alerts`, `POST /replay`, `POST /parse`, `POST /parse/image`, `GET /drift`, `GET /clinician`, plus session helpers (`/events/accept`, `/cards`, `/why`, `/demo/reset`).

## Notes

`NOTES.md` records every decision, substitution and cut made while building (integrator choice, the demo clock, the escalation-episode rule, the budget baseline, and so on). The Gemini model is one constant, `GEMINI_MODEL` in `backend/config.py`.
