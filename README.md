# GlucoPilot

A personalised, mechanistic-plus-learned simulation of a Type 1 diabetic's body. Every intake and activity (food, alcohol, caffeine, insulin, exercise, sleep, illness, stress, water) goes into a physiology model, and everything you see is the output of a simulator, estimator or optimiser: a short-horizon glucose forecast with uncertainty, a permission decision ("can I have two more beers tonight?") with the condition that makes it safe, and 30-day comparisons of lifestyle changes. The screens are built for a person with no technical background: what you eat and drink, and how your body handles it.

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
3. (Optional) Add a Gemini key so the parsers use `gemini-3.5-flash-lite` instead of the local fallback:
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

The app is live: the demo person's 90 days of synthetic data are lined up with the real clock (the anchor day becomes today), so the number, the "now" marker and the plan move as the day goes on. The screens refresh every minute.

1. **Login.** Tap one of the five people (Alex, Priya, Ken, Marcus, Zara: each a virtual patient with 90 days of sensor data and a fitted twin), **🎲 Random new person**, or **Add someone by hand**: name, age, sex, weight, height, carb ratio, correction factor, target range. A new profile is matched to the closest virtual person in the 30-patient cohort and that person's model is fitted on the spot (about 10 s). Profiles are JSON files on the backend; no passwords, nothing in the browser.
2. **Home.** One big number with a trend word, coloured by your target range; 3 hours of sensor and 3 hours of forecast starting where the sensor left off. Under it the **Right now** tiles (carbs digesting, liver stores, ketones, energy, recovery, insulin working; alcohol and caffeine only when you have had some), all the same shape. Tap a tile for its next 3 hours. **Coming up**: next meal, next workout, the next risk, the best window for what you do most.
3. **Chat.** Ask anything about your body, history, forecast or plan, log what you did, or propose something: `What's my glucose?`, `Why isn't my sugar rising after lunch?`, `How many lows did I have this week?`, `I just had a large coffee`, `What if I skip dinner?`, `/plan tomorrow`. Gemini only routes and phrases: it picks from ten backend tools (current state, forecast, why-now, history, permission engine, log, planner, 30-day change, average person, what-if) and every number in the answer is checked against the tool results before it is shown; the chips under each answer say which tools were checked. Without a key a built-in reader does the routing with template sentences.
4. **Chat: `Can I have pizza for dinner?`** The line "Understood: pizza tonight at 19:00" appears under your message (JSON behind *details*), then the answer card: a headline (**Enjoy it** / **Yes, with a snack** / **Better to wait**), one or two plain sentences, and the next 6 hours as a shaded band with a marker. **Add to plan** commits it (and the snack if there is one) to the forecast and the Plan tab. The **?** button next to the input lists examples and the commands in plain words.
5. **`Run at 7 tomorrow?`** ("Go for it"), **`Large coffee now`** ("Yes, with a snack": the coffee is harmless but you are already heading low) and the **Workout** button with **Lift 45 min** (a condition plus a better time) show the other paths; drinks work the same way through the **Drink** button or free text.
6. **Quick-log buttons** (chat panel and the header's **Log something**): Meal (describe it, type the carbs, or a photo when a Gemini key is set), Snack, Coffee, Drink (how many, beer / wine / spirit), Workout.
7. **Plan tab.** Your day at a glance: one headline ("Eat by 22:40, a light workout with a snack first would be safest, watch for a low around 22:55."), one horizontal axis from wake time to bedtime with a glucose sparkline, icons for meals, snacks, coffee, workouts, insulin and sleep (solid = logged, dashed = your usual, outlined = suggested), and two thin bands: when exercise is safe / needs care / better avoided, and where glucose is or will be in range. **Suggest my day** places a workout and a snack; tap a suggestion to add it, drag the workout to move it and the bands recompute; hover anything for a one-line reason ("insulin from lunch still active").
8. **`/plan tomorrow`** and **`/change morning_workouts`** (also `cut_caffeine`, `drink_fridays_only`, `fasting_16_8`) answer as cards too; `/change` shows the 30-day comparison for time in range, predicted lows per week, average energy and how well insulin works. **`/why`** repeats the reason for the last answer in plain words.
9. **Details tab.** The numbers behind the tiles, the 8-hour chances of a low or a high, what is still in your body (insulin, caffeine, alcohol decay), sensor data quality, whether the model is still in sync with your sensor, your settings. **I'm nerdy** at the bottom opens Replay (re-run a past day with the sliders; on Sat 2025-08-09 set Alcohol to 0 and the overnight low rises from 69 to about 125 mg/dL) and Trends.

Remove `.env` (or set an invalid key) and text is read by the built-in reader instead of Gemini; everything still works. `POST /permission?stale=30` returns a "need a fresh reading first" card.

## Screenshots

From `frontend/audit.spec.ts` (Playwright walks every screen; `audit/screens_v5/` after a run). A curated set is committed under `docs/screens/`:

| Screen | File |
|---|---|
| Home: glucose, tiles, coming up | `docs/screens/home.png` |
| Chat answer card (pizza) | `docs/screens/chat-pizza.png` |
| Chat: why glucose is not rising (the explain card) | `docs/screens/chat-explain.png` |
| Chat: history and logging | `docs/screens/chat-history.png`, `docs/screens/chat-logged.png` |
| Plan: the day on one axis | `docs/screens/plan.png` |
| Plan with a suggested workout and snack | `docs/screens/plan-suggested.png` |
| Chat: the same question with and without personalisation | `docs/screens/chat-compared.png` |
| Details | `docs/screens/details.png` |
| Login (five people) and the switcher | `docs/screens/login.png`, `docs/screens/switcher.png` |
| Phone: Home, the Ask sheet, Plan | `docs/screens/phone-home.png`, `docs/screens/phone-chat.png`, `docs/screens/phone-plan.png` |

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
frontend/     Vite + React + Recharts (login, Home / Plan / Details, chat with quick-log buttons, "I'm nerdy" replay + trends)
```

## Why this is not an LLM wrapper

Gemini is called in exactly two places, and both return only structured JSON that is validated against the `Event` contract: photo -> nutrition items, and free text -> one event. If there is no key or the call fails, a deterministic regex + lookup-table parser produces the same contract, and the UI says so on a badge. Nothing the user sees is generated text.

Every number on screen comes from a model you can read:

- **Physiology.** The Hovorka (2004) glucose-insulin model with published parameters, plus one or two ODEs each for gut absorption (fat and fibre slow it), liver and muscle glycogen, blood alcohol (Widmark absorption, zero-order clearance, hepatic glucose output suppressed by BAC and a lingering state so the low arrives 4-10 hours after drinking), caffeine (5-hour half-life, transient insulin resistance, worse sleep), exercise (aerobic uptake and a decaying sensitivity window; anaerobic transient rise), ketones with a DKA flag, hydration, and an energy score. `params.yaml` cites every constant.
- **Personalisation.** Nine parameters are fitted per patient by least squares on 6-hour windows of their own CGM (three time-of-day sensitivities, carb bioavailability, absorption time constant, exercise and alcohol gains, basal drift, sleep-debt coefficient), with a 30-resample bootstrap for a posterior. A UKF estimates the hidden state now. A gradient-boosted residual model learns what the ODE still gets wrong at 30/60/120 min.
- **Decisions.** Every card is a Monte Carlo experiment: 200 trajectories sampled from the posterior and from the uncertainty of the logged amounts, for do-nothing, the proposal, and its variants. Approval needs P(glucose < 70) under 5 % with no hyper breach; otherwise the best passing variant becomes the condition. The planner batches hundreds of candidate days through the same integrator. Change requests loop a rewritten week through the daily and the 10-year layers. The safety gate runs first and can refuse to decide (stale CGM, bad data) or escalate (DKA pattern, repeated severe lows, model drift).
- **Long term.** Organ accumulators are cumulative hazards with DCCT/UKPDS coefficients; A1c 9 -> 7 reproduces the DCCT retinopathy reduction. (Computed and tested, but the 10-year numbers are kept off the screens in this version; the UI shows 30-day comparisons.)

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

`http://127.0.0.1:8000/docs` lists everything. Main routes: `GET /profiles`, `POST /profiles`, `POST /profiles/{id}/select`, `GET /home`, `POST /plan/timeline`, `GET /state`, `GET /forecast`, `POST /permission` (`?stale=30` to test the gate), `GET|POST /plan`, `POST /change`, `GET /alerts`, `POST /replay`, `POST /parse`, `POST /parse/image`, `GET /drift`, plus session helpers (`/events/accept`, `/cards`, `/why`, `/demo/reset`). `GET /budget` and `GET /clinician` still exist but are not used by the UI.

## Notes

`NOTES.md` records every decision, substitution and cut made while building (integrator choice, the demo clock, the escalation-episode rule, the budget baseline, and so on). The Gemini model is one constant, `GEMINI_MODEL` in `backend/config.py`.
